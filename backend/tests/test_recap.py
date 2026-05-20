"""B1 章节回顾测试：生成 + prompt 拼装。"""
from __future__ import annotations
import uuid
import pytest

from app.models import ChapterMarker, NarrativeLog
from app.providers.base import LLMResponse


def _add_log(db, branch_id: str, tick: int, text: str, role: str = "narrator", **kw):
    log = NarrativeLog(
        id=f"nl_{uuid.uuid4().hex[:8]}",
        branch_id=branch_id, tick=tick, text=text, role=role, **kw,
    )
    db.add(log); db.flush()
    return log


def _add_chapter(db, branch_id: str, tick: int, title: str, summary: str = "", **kw):
    cm = ChapterMarker(
        id=f"ch_{uuid.uuid4().hex[:8]}",
        branch_id=branch_id, tick=tick, title=title, summary=summary, **kw,
    )
    db.add(cm); db.flush()
    return cm


# ---- _collect_chapter_text ----

def test_collect_text_prefers_author_final(db, world_factory):
    from app.engine.recap import _collect_chapter_text
    w, br = world_factory()
    _add_log(db, br.id, 1, "粗稿1", role="director_draft")
    _add_log(db, br.id, 1, "定稿1", role="author_final")
    _add_log(db, br.id, 2, "纯叙事2", role="narrator")
    db.commit()

    text = _collect_chapter_text(db, br.id, 0, 5)
    assert "定稿1" in text
    assert "纯叙事2" in text
    assert "粗稿1" not in text


def test_collect_text_respects_range(db, world_factory):
    from app.engine.recap import _collect_chapter_text
    w, br = world_factory()
    _add_log(db, br.id, 1, "在范围内", role="narrator")
    _add_log(db, br.id, 10, "超出范围", role="narrator")
    db.commit()

    text = _collect_chapter_text(db, br.id, 0, 5)
    assert "在范围内" in text
    assert "超出范围" not in text


# ---- generate_chapter_summary ----

def test_generate_summary_writes_back(db, world_factory):
    from app.engine.recap import generate_chapter_summary
    from tests.conftest import FakeProvider
    w, br = world_factory()
    _add_log(db, br.id, 1, "阿离踏出村庄走向北山。", role="narrator")
    cm = _add_chapter(db, br.id, 5, "出村")
    db.commit()

    provider = FakeProvider([LLMResponse(text="阿离离开了出生的村庄前往北山寻找师父。")])
    out = generate_chapter_summary(db, w, cm, provider)
    assert out == "阿离离开了出生的村庄前往北山寻找师父。"
    assert cm.summary == out


def test_generate_summary_strips_prefix(db, world_factory):
    from app.engine.recap import generate_chapter_summary
    from tests.conftest import FakeProvider
    w, br = world_factory()
    _add_log(db, br.id, 1, "原文", role="narrator")
    cm = _add_chapter(db, br.id, 1, "标题")
    db.commit()

    provider = FakeProvider([LLMResponse(text="本章：阿离做了某事。")])
    out = generate_chapter_summary(db, w, cm, provider)
    assert out == "阿离做了某事。"


def test_generate_summary_empty_chapter_returns_empty(db, world_factory):
    from app.engine.recap import generate_chapter_summary
    from tests.conftest import FakeProvider
    w, br = world_factory()
    cm = _add_chapter(db, br.id, 5, "空章")
    db.commit()

    provider = FakeProvider([LLMResponse(text="不该被调用")])
    out = generate_chapter_summary(db, w, cm, provider)
    assert out == ""
    assert cm.summary == ""
    # 没文本 → 不该消耗 LLM 配额
    assert len(provider.calls) == 0


def test_generate_summary_llm_failure_returns_none(db, world_factory):
    from app.engine.recap import generate_chapter_summary
    w, br = world_factory()
    _add_log(db, br.id, 1, "原文", role="narrator")
    cm = _add_chapter(db, br.id, 5, "")
    db.commit()

    class BoomProvider:
        name = "boom"
        def chat(self, **_): raise RuntimeError("boom")

    out = generate_chapter_summary(db, w, cm, BoomProvider())
    assert out is None
    # 失败时 chapter.summary 不被改写为脏值
    assert cm.summary == ""


# ---- regenerate_all_summaries ----

def test_regenerate_all_processes_every_chapter(db, world_factory):
    from app.engine.recap import regenerate_all_summaries
    from tests.conftest import FakeProvider
    w, br = world_factory()
    w.active_branch_id = br.id
    _add_log(db, br.id, 1, "文本1", role="narrator")
    _add_log(db, br.id, 5, "文本2", role="narrator")
    _add_chapter(db, br.id, 3, "ch1")
    _add_chapter(db, br.id, 7, "ch2")
    db.commit()

    provider = FakeProvider([
        LLMResponse(text="第一章摘要。"),
        LLMResponse(text="第二章摘要。"),
    ])
    res = regenerate_all_summaries(db, w, provider)
    assert res.ok and res.chapters_processed == 2
    assert res.chapters_succeeded == 2 and res.chapters_failed == 0


def test_regenerate_all_only_missing_skips_existing(db, world_factory):
    from app.engine.recap import regenerate_all_summaries
    from tests.conftest import FakeProvider
    w, br = world_factory()
    w.active_branch_id = br.id
    _add_log(db, br.id, 1, "文本1", role="narrator")
    _add_log(db, br.id, 5, "文本2", role="narrator")
    _add_chapter(db, br.id, 3, "ch1", summary="已有摘要")
    _add_chapter(db, br.id, 7, "ch2")
    db.commit()

    provider = FakeProvider([LLMResponse(text="第二章摘要。")])
    res = regenerate_all_summaries(db, w, provider, only_missing=True)
    assert res.chapters_succeeded == 1
    # 已有摘要的不被重写
    ch1 = db.query(ChapterMarker).filter_by(tick=3).first()
    assert ch1.summary == "已有摘要"


# ---- build_chapter_recap_block ----

def test_recap_block_empty_when_no_chapters(db, world_factory):
    from app.engine.recap import build_chapter_recap_block
    w, br = world_factory()
    assert build_chapter_recap_block(db, w) == ""


def test_recap_block_skips_empty_summary(db, world_factory):
    from app.engine.recap import build_chapter_recap_block
    w, br = world_factory()
    _add_chapter(db, br.id, 1, "无摘要章")  # summary=""
    db.commit()
    assert build_chapter_recap_block(db, w) == ""


def test_recap_block_renders_in_tick_order(db, world_factory):
    from app.engine.recap import build_chapter_recap_block
    w, br = world_factory()
    _add_chapter(db, br.id, 10, "晚章", summary="第二段。")
    _add_chapter(db, br.id, 3, "早章", summary="第一段。")
    db.commit()

    out = build_chapter_recap_block(db, w)
    assert "章节回顾" in out
    p_early = out.index("第一段")
    p_late = out.index("第二段")
    assert p_early < p_late
    assert "「早章」" in out and "(至 t3)" in out


def test_recap_block_disabled_via_rules(db, world_factory):
    from app.engine.recap import build_chapter_recap_block
    w, br = world_factory(rules={"disable_chapter_recap": True})
    _add_chapter(db, br.id, 5, "章", summary="不该出现")
    db.commit()
    assert build_chapter_recap_block(db, w) == ""


# ---- _build_user_prompt 集成 ----

def test_user_prompt_includes_recap_block(db, world_factory):
    from app.engine.simulator import _build_user_prompt
    from app.engine.state import build_state_snapshot
    w, br = world_factory()
    _add_chapter(db, br.id, 5, "ch1", summary="阿离离开村庄。")
    db.commit()

    snap = build_state_snapshot(db, w)
    prompt = _build_user_prompt(db, snap, None, w)
    assert "章节回顾" in prompt
    assert "阿离离开村庄。" in prompt
