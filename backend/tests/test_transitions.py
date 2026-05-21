"""C3: 章节过渡评估端到端。"""
from __future__ import annotations
from unittest.mock import patch as _mp

import pytest

from app.providers.base import LLMResponse
from app.models import ChapterMarker, Event, NarrativeLog


class FakeProvider:
    def __init__(self, payload):
        self.payload = payload

    def chat(self, system, messages, tools=None, max_tokens=None, temperature=None):
        import json
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload, ensure_ascii=False)
        return LLMResponse(text=text, raw={}, usage={})


@pytest.fixture
def fake_trans_provider():
    def _f(payload):
        return _mp("app.engine.narrative.transitions.get_provider", return_value=FakeProvider(payload))
    return _f


def _setup_two_chapters(db, world_factory):
    w, br = world_factory()
    w.current_tick = 8
    db.add_all([
        ChapterMarker(id="m1", branch_id=br.id, tick=1, title="第一章 启程"),
        ChapterMarker(id="m2", branch_id=br.id, tick=5, title="第二章 抵达"),
    ])
    db.add_all([
        Event(id="e1", branch_id=br.id, tick=1, title="出发",
              description="爱丽丝离开家", participants=[], consequences=[], metadata_={}, deleted=0),
        Event(id="e2", branch_id=br.id, tick=2, title="路上",
              description="她经过森林", participants=[], consequences=[], metadata_={}, deleted=0),
        Event(id="e3", branch_id=br.id, tick=4, title="夜宿",
              description="她在小镇歇脚", participants=[], consequences=[], metadata_={}, deleted=0),
        Event(id="e4", branch_id=br.id, tick=5, title="抵达紫霜城",
              description="城门在前", participants=[], consequences=[], metadata_={}, deleted=0),
        Event(id="e5", branch_id=br.id, tick=6, title="议会接见",
              description="议长出现", participants=[], consequences=[], metadata_={}, deleted=0),
    ])
    db.add_all([
        NarrativeLog(id="n1", branch_id=br.id, tick=4, role="narrator", text="夜风带着寒意。"),
        NarrativeLog(id="n2", branch_id=br.id, tick=5, role="narrator", text="紫霜城的门楼在晨光中显出轮廓。"),
    ])
    db.commit()
    return w, br


def test_evaluate_transition_basic(client, db, world_factory, fake_trans_provider):
    w, _ = _setup_two_chapters(db, world_factory)
    payload = {"score": 78, "issues": ["夜宿到城门之间缺一段路程描述"],
               "suggested_bridge": "她披衣启程，朝紫霜城方向走去。"}
    with fake_trans_provider(payload):
        r = client.post(f"/api/worlds/{w.id}/storyboard/transitions/evaluate",
                        json={"from_index": 0, "to_index": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["score"] == 78
    assert body["issues"] == ["夜宿到城门之间缺一段路程描述"]
    assert body["suggested_bridge"].startswith("她披衣启程")
    assert body["from_chapter"]["title"] == "第一章 启程"
    assert body["to_chapter"]["title"] == "第二章 抵达"
    assert body["skipped"] is False


def test_evaluate_transition_clamps_score(client, db, world_factory, fake_trans_provider):
    w, _ = _setup_two_chapters(db, world_factory)
    with fake_trans_provider({"score": 200, "issues": [], "suggested_bridge": ""}):
        body = client.post(f"/api/worlds/{w.id}/storyboard/transitions/evaluate",
                           json={"from_index": 0, "to_index": 1}).json()
    assert body["score"] == 100

    with fake_trans_provider({"score": -5, "issues": [], "suggested_bridge": ""}):
        body = client.post(f"/api/worlds/{w.id}/storyboard/transitions/evaluate",
                           json={"from_index": 0, "to_index": 1}).json()
    assert body["score"] == 0


def test_evaluate_transition_invalid_score_becomes_null(client, db, world_factory, fake_trans_provider):
    w, _ = _setup_two_chapters(db, world_factory)
    with fake_trans_provider({"score": "bad", "issues": [], "suggested_bridge": ""}):
        body = client.post(f"/api/worlds/{w.id}/storyboard/transitions/evaluate",
                           json={"from_index": 0, "to_index": 1}).json()
    assert body["score"] is None


def test_evaluate_transition_garbage_response(client, db, world_factory, fake_trans_provider):
    w, _ = _setup_two_chapters(db, world_factory)
    with fake_trans_provider("not json"):
        body = client.post(f"/api/worlds/{w.id}/storyboard/transitions/evaluate",
                           json={"from_index": 0, "to_index": 1}).json()
    assert body["score"] is None
    assert body["issues"] == []
    assert body["suggested_bridge"] == ""
    assert body["skipped"] is False


def test_evaluate_transition_index_out_of_range(client, db, world_factory):
    w, _ = _setup_two_chapters(db, world_factory)
    r = client.post(f"/api/worlds/{w.id}/storyboard/transitions/evaluate",
                    json={"from_index": 0, "to_index": 99})
    assert r.status_code == 400


def test_evaluate_transition_to_index_must_be_greater(client, db, world_factory):
    w, _ = _setup_two_chapters(db, world_factory)
    r = client.post(f"/api/worlds/{w.id}/storyboard/transitions/evaluate",
                    json={"from_index": 1, "to_index": 0})
    assert r.status_code == 400
    r = client.post(f"/api/worlds/{w.id}/storyboard/transitions/evaluate",
                    json={"from_index": 0, "to_index": 0})
    assert r.status_code == 400


def test_evaluate_transition_skipped_when_empty_chapters(client, db, world_factory, fake_trans_provider):
    """两章都没事件、没叙事 → 直接 skipped，不调 LLM。"""
    w, br = world_factory()
    w.current_tick = 5
    db.add_all([
        ChapterMarker(id="m1", branch_id=br.id, tick=1, title="A"),
        ChapterMarker(id="m2", branch_id=br.id, tick=3, title="B"),
    ])
    db.commit()
    # provider 即便给响应，也不该被调（skipped=True）
    with fake_trans_provider({"score": 50, "issues": [], "suggested_bridge": "x"}):
        body = client.post(f"/api/worlds/{w.id}/storyboard/transitions/evaluate",
                           json={"from_index": 0, "to_index": 1}).json()
    assert body["skipped"] is True
    assert body["score"] is None


def test_evaluate_transition_world_404(client):
    r = client.post("/api/worlds/nope/storyboard/transitions/evaluate",
                    json={"from_index": 0, "to_index": 1})
    assert r.status_code == 404


def test_evaluate_transition_no_active_branch(client, db, world_factory):
    w, br = world_factory()
    w.active_branch_id = None
    db.commit()
    r = client.post(f"/api/worlds/{w.id}/storyboard/transitions/evaluate",
                    json={"from_index": 0, "to_index": 1})
    assert r.status_code == 400


def test_evaluate_transition_truncates_issues(client, db, world_factory, fake_trans_provider):
    w, _ = _setup_two_chapters(db, world_factory)
    payload = {"score": 60, "issues": [f"问题{i}" for i in range(20)], "suggested_bridge": "x" * 500}
    with fake_trans_provider(payload):
        body = client.post(f"/api/worlds/{w.id}/storyboard/transitions/evaluate",
                           json={"from_index": 0, "to_index": 1}).json()
    assert len(body["issues"]) == 8
    assert len(body["suggested_bridge"]) <= 300
