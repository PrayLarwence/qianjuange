"""A5 Editor agent 测试。

用 monkeypatch 把 consistency.get_provider 替换为 fake，让扫描走可控 JSON。
"""
from __future__ import annotations
import json
import pytest

from app.models import (
    ChapterMarker, ConsistencyIssue, NarrativeLog, Event, Entity,
)


def _make_branch_state(db, world_factory):
    """造一个有几个 tick 事件 + 实体 + 一个章节标记的世界。"""
    w, br = world_factory()
    w.current_tick = 6
    db.add_all([
        Entity(id="e_a", branch_id=br.id, type="character", name="阿离",
               summary="少年", attributes={}, state={}, created_at_tick=0, alive=1),
        Entity(id="e_b", branch_id=br.id, type="character", name="老掌柜",
               summary="客栈老板", attributes={}, state={}, created_at_tick=0, alive=1),
    ])
    for t in range(1, 7):
        db.add(Event(
            id=f"ev{t}", branch_id=br.id, tick=t, title=f"事件{t}",
            description=f"第 {t} 个事件描述", participants=["e_a"],
            consequences=[], metadata_={}, deleted=0,
        ))
        db.add(NarrativeLog(
            id=f"n{t}", branch_id=br.id, tick=t, role="narrator",
            text=f"第 {t} 段叙事文字。",
        ))
    cm = ChapterMarker(id="ch_1", branch_id=br.id, tick=5, title="第一回")
    db.add(cm)
    db.commit()
    return w, br, cm


class FakeProvider:
    """返回固定 issue JSON 的 provider。"""
    def __init__(self, issues=None):
        self._issues = issues if issues is not None else [
            {
                "category": "personality",
                "severity": "high",
                "title": "阿离前后判若两人",
                "description": "前一段还沉默寡言，后一段突然说教三百字",
                "suggestion": "插入一段心理转折",
                "entity_ids": ["e_a"],
                "tick_start": 2,
                "tick_end": 4,
            },
            {
                "category": "rule",
                "severity": "low",
                "title": "时代背景细节",
                "description": "宋代情景里出现了清代器物",
                "suggestion": "替换为对应朝代物件",
                "entity_ids": [],
                "tick_start": 3,
                "tick_end": 3,
            },
        ]
        self.calls = 0

    def chat(self, *, system, messages, tools, max_tokens, temperature):
        self.calls += 1
        class R:
            text = json.dumps({"issues": self._issues}, ensure_ascii=False)
        return R()


def _patch_provider(monkeypatch, provider):
    from app.engine import consistency
    monkeypatch.setattr(consistency, "get_provider", lambda _=None: provider)


# ---- run_editor_for_chapter ----

def test_run_editor_writes_critique_log_and_issues(db, world_factory, monkeypatch):
    from app.engine.editor import run_editor_for_chapter
    w, br, cm = _make_branch_state(db, world_factory)
    fake = FakeProvider()
    _patch_provider(monkeypatch, fake)

    res = run_editor_for_chapter(db, w, cm)

    assert res.ok is True
    assert res.tick_from == 0 and res.tick_to == 5  # 第一章覆盖 0..5
    assert res.issue_count == 2
    assert fake.calls == 1

    log = db.query(NarrativeLog).filter_by(
        branch_id=br.id, tick=5, role="editor_critique",
    ).first()
    assert log is not None
    assert "编辑评注" in log.text
    assert "阿离前后判若两人" in log.text  # high 优先排在前

    issues = db.query(ConsistencyIssue).filter_by(scan_id=res.scan_id).all()
    assert len(issues) == 2


def test_run_editor_second_chapter_uses_correct_range(db, world_factory, monkeypatch):
    from app.engine.editor import run_editor_for_chapter
    w, br, _ = _make_branch_state(db, world_factory)
    cm2 = ChapterMarker(id="ch_2", branch_id=br.id, tick=6, title="第二回")
    db.add(cm2); db.commit()

    fake = FakeProvider(issues=[])
    _patch_provider(monkeypatch, fake)

    res = run_editor_for_chapter(db, w, cm2)

    assert res.ok is True
    # 上一章 tick=5，本章 tick=6，所以扫描范围是 6..6
    assert res.tick_from == 6 and res.tick_to == 6
    assert res.issue_count == 0
    log = db.query(NarrativeLog).filter_by(branch_id=br.id, tick=6, role="editor_critique").first()
    assert log is not None
    assert "未发现" in log.text  # 空 issues 也写一条正面评语


def test_run_editor_replaces_old_critique_on_rerun(db, world_factory, monkeypatch):
    from app.engine.editor import run_editor_for_chapter
    w, br, cm = _make_branch_state(db, world_factory)

    _patch_provider(monkeypatch, FakeProvider())
    res1 = run_editor_for_chapter(db, w, cm)
    assert res1.ok

    _patch_provider(monkeypatch, FakeProvider(issues=[]))
    res2 = run_editor_for_chapter(db, w, cm)
    assert res2.ok and res2.issue_count == 0

    logs = db.query(NarrativeLog).filter_by(
        branch_id=br.id, tick=5, role="editor_critique",
    ).all()
    assert len(logs) == 1, "重审必须替换旧评注，不能堆叠"
    assert "未发现" in logs[0].text


def test_run_editor_handles_provider_failure_gracefully(db, world_factory, monkeypatch):
    from app.engine.editor import run_editor_for_chapter
    from app.engine import consistency
    w, br, cm = _make_branch_state(db, world_factory)

    class Boom:
        def chat(self, **k):
            raise RuntimeError("LLM 挂了")
    monkeypatch.setattr(consistency, "get_provider", lambda _=None: Boom())

    res = run_editor_for_chapter(db, w, cm)

    assert res.ok is False
    assert "扫描失败" in res.reason or "LLM" in res.reason
    log = db.query(NarrativeLog).filter_by(
        branch_id=br.id, tick=5, role="editor_critique",
    ).first()
    assert log is None


# ---- get_chapter_critique ----

def test_get_critique_before_run_returns_empty(db, world_factory):
    from app.engine.editor import get_chapter_critique
    w, br, cm = _make_branch_state(db, world_factory)
    out = get_chapter_critique(db, cm)
    assert out["has_critique"] is False
    assert out["critique_text"] == ""
    assert out["tick_from"] == 0 and out["tick_to"] == 5


def test_get_critique_after_run_returns_text_and_issues(db, world_factory, monkeypatch):
    from app.engine.editor import run_editor_for_chapter, get_chapter_critique
    w, br, cm = _make_branch_state(db, world_factory)
    _patch_provider(monkeypatch, FakeProvider())
    run_editor_for_chapter(db, w, cm)

    out = get_chapter_critique(db, cm)
    assert out["has_critique"] is True
    assert "编辑评注" in out["critique_text"]
    assert len(out["issues"]) == 2
    titles = [i["title"] for i in out["issues"]]
    assert "阿离前后判若两人" in titles


# ---- routes ----

def test_route_critique_creates_and_returns(client, db, world_factory, monkeypatch):
    w, br, cm = _make_branch_state(db, world_factory)
    _patch_provider(monkeypatch, FakeProvider())

    r = client.post(f"/api/chapters/{cm.id}/critique", json={})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["issue_count"] == 2
    assert "编辑评注" in data["critique_text"]


def test_route_critique_404_for_unknown_chapter(client):
    r = client.post("/api/chapters/ch_nope/critique", json={})
    assert r.status_code == 404


def test_route_get_critique_returns_state(client, db, world_factory, monkeypatch):
    w, br, cm = _make_branch_state(db, world_factory)

    r = client.get(f"/api/chapters/{cm.id}/critique")
    assert r.status_code == 200
    assert r.json()["has_critique"] is False

    _patch_provider(monkeypatch, FakeProvider())
    client.post(f"/api/chapters/{cm.id}/critique", json={})

    r2 = client.get(f"/api/chapters/{cm.id}/critique")
    assert r2.status_code == 200
    body = r2.json()
    assert body["has_critique"] is True
    assert body["issue_count"] if False else len(body["issues"]) == 2


def test_timeline_default_hides_editor_critique(client, db, world_factory, monkeypatch):
    """A3 已设的契约：default 不暴露 editor_critique；include_drafts=1 才出现。"""
    w, br, cm = _make_branch_state(db, world_factory)
    _patch_provider(monkeypatch, FakeProvider())
    client.post(f"/api/chapters/{cm.id}/critique", json={})

    r = client.get(f"/api/worlds/{w.id}/timeline")
    roles = {n["role"] for n in r.json()["narration"]}
    assert "editor_critique" not in roles

    r2 = client.get(f"/api/worlds/{w.id}/timeline?include_drafts=1")
    roles2 = {n["role"] for n in r2.json()["narration"]}
    assert "editor_critique" in roles2
