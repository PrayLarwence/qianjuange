"""B8: 场景连续性扫描端到端。"""
from __future__ import annotations
import json
from unittest.mock import patch as _mp

import pytest

from app.providers.base import LLMResponse
from app.models import Entity, Event, NarrativeLog, ConsistencyIssue


class FakeProvider:
    def __init__(self, payload):
        self.payload = payload

    def chat(self, system, messages, tools=None, max_tokens=None, temperature=None):
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload, ensure_ascii=False)
        return LLMResponse(text=text, raw={}, usage={})


@pytest.fixture
def fake_scene_provider():
    def _f(payload):
        return _mp("app.engine.manuscript.scene_continuity.get_provider", return_value=FakeProvider(payload))
    return _f


def _mk_entity(db, branch_id, eid, name):
    e = Entity(id=eid, branch_id=branch_id, name=name, type="character",
               attributes={}, alive=1)
    db.add(e); db.flush()
    return e


def _setup(db, world_factory):
    w, br = world_factory()
    w.current_tick = 5
    e1 = _mk_entity(db, br.id, "ent_alice", "爱丽丝")
    e2 = _mk_entity(db, br.id, "ent_bob", "鲍勃")
    db.add_all([
        Event(id="e1", branch_id=br.id, tick=1, title="酒馆相遇",
              description="他们在酒馆碰头", participants=[e1.id, e2.id],
              consequences=[], metadata_={}, deleted=0),
        Event(id="e2", branch_id=br.id, tick=2, title="山顶对话",
              description="他们站在山顶", participants=[e1.id, e2.id],
              consequences=[], metadata_={}, deleted=0),
    ])
    db.add_all([
        NarrativeLog(id="n1", branch_id=br.id, tick=1, role="narrator",
                     text="酒馆里灯火通明。"),
        NarrativeLog(id="n2", branch_id=br.id, tick=2, role="narrator",
                     text="山风呼啸。"),
    ])
    db.commit()
    return w, br, e1, e2


def test_scene_scan_creates_issues(client, db, world_factory, fake_scene_provider):
    w, _, e1, _ = _setup(db, world_factory)
    payload = {"issues": [
        {"kind": "location", "title": "酒馆到山顶",
         "description": "上一拍还在酒馆，下一拍直接山顶，缺转场",
         "suggestion": "补一句他们离开酒馆向山上走的过渡",
         "tick_start": 1, "tick_end": 2, "entity_ids": [e1.id]},
    ]}
    with fake_scene_provider(payload):
        r = client.post(f"/api/worlds/{w.id}/scene_continuity/scan",
                        json={"scope": "all"})
    assert r.status_code == 200
    body = r.json()
    assert body["scan"]["status"] == "completed"
    assert body["scan"]["issue_count"] == 1
    assert body["scan"]["scope"].startswith("scene:")
    assert len(body["issues"]) == 1
    iss = body["issues"][0]
    assert iss["category"] == "continuity"
    assert "位置跳跃" in iss["title"]
    assert iss["entity_ids"] == [e1.id]


def test_scene_scan_drops_unknown_kinds(client, db, world_factory, fake_scene_provider):
    w, _, _, _ = _setup(db, world_factory)
    payload = {"issues": [
        {"kind": "personality", "description": "应该被丢弃", "tick_start": 1, "tick_end": 2},
        {"kind": "location", "description": "保留", "tick_start": 1, "tick_end": 2},
        {"kind": "", "description": "也丢", "tick_start": 1, "tick_end": 2},
    ]}
    with fake_scene_provider(payload):
        r = client.post(f"/api/worlds/{w.id}/scene_continuity/scan",
                        json={"scope": "all"}).json()
    assert r["scan"]["issue_count"] == 1


def test_scene_scan_drops_empty_description(client, db, world_factory, fake_scene_provider):
    w, _, _, _ = _setup(db, world_factory)
    payload = {"issues": [
        {"kind": "location", "description": "", "tick_start": 1, "tick_end": 2},
    ]}
    with fake_scene_provider(payload):
        r = client.post(f"/api/worlds/{w.id}/scene_continuity/scan",
                        json={"scope": "all"}).json()
    assert r["scan"]["issue_count"] == 0


def test_scene_scan_clamps_ticks_into_range(client, db, world_factory, fake_scene_provider):
    w, _, _, _ = _setup(db, world_factory)
    payload = {"issues": [
        {"kind": "presence", "description": "x", "tick_start": -100, "tick_end": 9999},
    ]}
    with fake_scene_provider(payload):
        body = client.post(f"/api/worlds/{w.id}/scene_continuity/scan",
                           json={"scope": "all"}).json()
    iss = body["issues"][0]
    assert iss["tick_start"] >= 0
    assert iss["tick_end"] <= w.current_tick


def test_scene_scan_filters_unknown_entity_ids(client, db, world_factory, fake_scene_provider):
    w, _, e1, _ = _setup(db, world_factory)
    payload = {"issues": [
        {"kind": "presence", "description": "x", "tick_start": 1, "tick_end": 2,
         "entity_ids": [e1.id, "ghost_id", 123]},
    ]}
    with fake_scene_provider(payload):
        body = client.post(f"/api/worlds/{w.id}/scene_continuity/scan",
                           json={"scope": "all"}).json()
    assert body["issues"][0]["entity_ids"] == [e1.id]


def test_scene_scan_garbage_response(client, db, world_factory, fake_scene_provider):
    w, _, _, _ = _setup(db, world_factory)
    with fake_scene_provider("not json"):
        body = client.post(f"/api/worlds/{w.id}/scene_continuity/scan",
                           json={"scope": "all"}).json()
    assert body["scan"]["status"] == "completed"
    assert body["scan"]["issue_count"] == 0


def test_scene_scan_no_content_skips_llm(client, db, world_factory, fake_scene_provider):
    w, br = world_factory()
    w.current_tick = 3
    db.commit()
    # provider 即便给响应也不该被调
    with fake_scene_provider({"issues": [{"kind": "location", "description": "x",
                                          "tick_start": 0, "tick_end": 3}]}):
        body = client.post(f"/api/worlds/{w.id}/scene_continuity/scan",
                           json={"scope": "all"}).json()
    assert body["scan"]["issue_count"] == 0


def test_scene_scan_world_404(client):
    r = client.post("/api/worlds/nope/scene_continuity/scan",
                    json={"scope": "all"})
    assert r.status_code == 404


def test_scene_scan_caps_at_10_issues(client, db, world_factory, fake_scene_provider):
    w, _, _, _ = _setup(db, world_factory)
    payload = {"issues": [
        {"kind": "location", "description": f"问题{i}", "tick_start": 1, "tick_end": 2}
        for i in range(20)
    ]}
    with fake_scene_provider(payload):
        body = client.post(f"/api/worlds/{w.id}/scene_continuity/scan",
                           json={"scope": "all"}).json()
    assert body["scan"]["issue_count"] == 10


def test_scene_scan_severity_by_kind(client, db, world_factory, fake_scene_provider):
    w, _, _, _ = _setup(db, world_factory)
    payload = {"issues": [
        {"kind": "location", "description": "x", "tick_start": 1, "tick_end": 2},
        {"kind": "item_state", "description": "y", "tick_start": 1, "tick_end": 2},
    ]}
    with fake_scene_provider(payload):
        body = client.post(f"/api/worlds/{w.id}/scene_continuity/scan",
                           json={"scope": "all"}).json()
    sevs = {i["title"]: i["severity"] for i in body["issues"]}
    # location / presence → medium, item_state / time_weather → low
    assert any(v == "medium" for v in sevs.values())
    assert any(v == "low" for v in sevs.values())


def test_scene_scan_listed_in_issues_endpoint(client, db, world_factory, fake_scene_provider):
    """场景 issue 应能从 GET /worlds/{wid}/issues 读到（验证复用主流程）。"""
    w, _, _, _ = _setup(db, world_factory)
    payload = {"issues": [{"kind": "location", "description": "x",
                           "tick_start": 1, "tick_end": 2}]}
    with fake_scene_provider(payload):
        client.post(f"/api/worlds/{w.id}/scene_continuity/scan", json={"scope": "all"})
    r = client.get(f"/api/worlds/{w.id}/issues")
    body = r.json()
    cats = {i["category"] for i in body["issues"]}
    assert "continuity" in cats
