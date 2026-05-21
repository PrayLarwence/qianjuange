"""B4: chapters/auto 顺带生成 summary。"""
from __future__ import annotations
import uuid

from app.models import Entity, Event, NarrativeLog
from app.providers.base import LLMResponse
from tests.conftest import FakeProvider


AUTO_JSON = (
    '{"chapters":['
    '{"end_tick":3,"title":"开端"},'
    '{"end_tick":7,"title":"高潮"}'
    ']}'
)


def _seed_events(db, branch_id):
    for tick in [1, 2, 3, 5, 7]:
        ev = Event(
            id=f"ev_{uuid.uuid4().hex[:8]}",
            branch_id=branch_id, tick=tick,
            title=f"事件 t{tick}", description="…",
            participants=[],
        )
        db.add(ev)
        db.add(NarrativeLog(
            id=f"nl_{uuid.uuid4().hex[:8]}",
            branch_id=branch_id, tick=tick,
            role="narrator", text=f"t{tick} 那夜风大。",
        ))
    db.commit()


def test_auto_chapter_also_generates_summaries(client, db, world_factory, monkeypatch):
    w, br = world_factory()
    _seed_events(db, br.id)
    fake = FakeProvider([
        LLMResponse(text=AUTO_JSON),
        LLMResponse(text="开端摘要：三件小事。"),
        LLMResponse(text="高潮摘要：风暴来临。"),
    ])
    from app.api import chapters_api as r
    monkeypatch.setattr(r, "get_provider", lambda _=None: fake)

    resp = client.post(f"/api/worlds/{w.id}/chapters/auto", json={"target_count": 2})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["chapters"]) == 2
    assert data["summaries_generated"] == 2
    assert data["summaries_failed"] == 0
    assert data["summaries_skipped_reason"] is None

    # DB 里 summary 已落
    from app.models import ChapterMarker
    chs = db.query(ChapterMarker).filter_by(branch_id=br.id).order_by(ChapterMarker.tick).all()
    assert [c.summary for c in chs] == ["开端摘要：三件小事。", "高潮摘要：风暴来临。"]


def test_auto_chapter_skips_summaries_when_rule_disables(client, db, world_factory, monkeypatch):
    w, br = world_factory(rules={"disable_chapter_recap": True})
    _seed_events(db, br.id)
    # 只排一条响应：分章；如果 recap 被错误调用会 IndexError
    fake = FakeProvider([LLMResponse(text=AUTO_JSON)])
    from app.api import chapters_api as r
    monkeypatch.setattr(r, "get_provider", lambda _=None: fake)

    data = client.post(f"/api/worlds/{w.id}/chapters/auto", json={"target_count": 2}).json()
    assert len(data["chapters"]) == 2
    assert data["summaries_generated"] == 0
    assert data["summaries_skipped_reason"] == "disabled_by_rule"
    # 真没调
    assert len(fake.calls) == 1


def test_auto_chapter_partial_summary_failure_doesnt_break(client, db, world_factory, monkeypatch):
    w, br = world_factory()
    _seed_events(db, br.id)

    class FlakyProvider:
        name = "flaky"
        def __init__(self):
            self.n = 0
        def chat(self, system, messages, tools, max_tokens=2048, temperature=0.7, timeout=120.0):
            self.n += 1
            if self.n == 1:
                return LLMResponse(text=AUTO_JSON)        # 分章
            if self.n == 2:
                raise RuntimeError("LLM hiccup")          # 第一章 summary 失败
            return LLMResponse(text="第二章好")            # 第二章 ok

    flaky = FlakyProvider()
    from app.api import chapters_api as r
    monkeypatch.setattr(r, "get_provider", lambda _=None: flaky)

    data = client.post(f"/api/worlds/{w.id}/chapters/auto", json={"target_count": 2}).json()
    assert len(data["chapters"]) == 2          # 章节本体不受影响
    assert data["summaries_generated"] == 1
    assert data["summaries_failed"] == 1


def test_auto_chapter_without_chapters_skips_recap(client, db, world_factory, monkeypatch):
    w, br = world_factory()
    # 只放一个事件——auto_chapter 内有 "len(events) < 2 不分章" 的早返
    ev = Event(id=f"ev_{uuid.uuid4().hex[:8]}", branch_id=br.id, tick=1,
               title="孤事", description="", participants=[])
    db.add(ev); db.commit()
    fake = FakeProvider([])  # 不该被调
    from app.api import chapters_api as r
    monkeypatch.setattr(r, "get_provider", lambda _=None: fake)

    data = client.post(f"/api/worlds/{w.id}/chapters/auto", json={"target_count": 2}).json()
    assert data["chapters"] == []
    assert "reason" in data
    # 早返没碰 recap 字段
    assert "summaries_generated" not in data
