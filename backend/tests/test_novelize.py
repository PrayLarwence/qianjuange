"""novelize 测试 —— 重点测 list_chapters 切片逻辑（纯函数，无 LLM）。"""
from __future__ import annotations

from app.engine.core.executor import execute_tool
from app.engine.narrative.novelize import (
    list_chapters,
    STRATEGY_SINGLE, STRATEGY_BY_TICK, STRATEGY_BY_COUNT, STRATEGY_MANUAL,
)
from app.models import ChapterMarker
import uuid


def _add_event(db, w, title: str, tick: int):
    """直接落事件并指定 tick（绕过 world.current_tick）。"""
    res = execute_tool(db, w, "add_event",
                       {"title": title, "description": "", "tick": tick})
    return res["id"]


# ---- 空分支 ----

def test_list_chapters_empty_branch_returns_empty(db, world_factory):
    w, br = world_factory()
    assert list_chapters(db, w, br.id, strategy=STRATEGY_SINGLE) == []


# ---- single ----

def test_single_strategy_packs_all(db, world_factory):
    w, br = world_factory()
    for i in range(5):
        _add_event(db, w, f"e{i}", tick=i)
    chs = list_chapters(db, w, br.id, strategy=STRATEGY_SINGLE)
    assert len(chs) == 1
    assert chs[0].title == "全文"
    assert len(chs[0].event_ids) == 5


# ---- by_tick ----

def test_by_tick_groups_by_window(db, world_factory):
    w, br = world_factory()
    # tick 0..9 共 10 个事件
    for i in range(10):
        _add_event(db, w, f"e{i}", tick=i)
    chs = list_chapters(db, w, br.id, strategy=STRATEGY_BY_TICK, chapter_size=3)
    # 0-2 / 3-5 / 6-8 / 9 → 4 章
    assert len(chs) == 4
    assert all(ch.event_ids for ch in chs)


def test_by_tick_skips_empty_windows(db, world_factory):
    """若 tick 跨度大但中间没事件，应跳过空章。"""
    w, br = world_factory()
    _add_event(db, w, "early", tick=0)
    _add_event(db, w, "late", tick=20)
    chs = list_chapters(db, w, br.id, strategy=STRATEGY_BY_TICK, chapter_size=5)
    # 不应有空 chapter
    for ch in chs:
        assert len(ch.event_ids) > 0


def test_by_tick_default_size_when_zero(db, world_factory):
    w, br = world_factory()
    for i in range(7):
        _add_event(db, w, f"e{i}", tick=i)
    chs = list_chapters(db, w, br.id, strategy=STRATEGY_BY_TICK, chapter_size=0)
    # 0 → 走默认 5
    assert sum(len(c.event_ids) for c in chs) == 7


# ---- by_count ----

def test_by_count_groups_by_event_count(db, world_factory):
    w, br = world_factory()
    for i in range(10):
        _add_event(db, w, f"e{i}", tick=i)
    chs = list_chapters(db, w, br.id, strategy=STRATEGY_BY_COUNT, chapter_size=4)
    # 10 个事件，每章 4 个 → 4 / 4 / 2
    assert len(chs) == 3
    assert len(chs[0].event_ids) == 4
    assert len(chs[2].event_ids) == 2


# ---- manual ----

def test_manual_no_markers_falls_back_to_single(db, world_factory):
    w, br = world_factory()
    for i in range(3):
        _add_event(db, w, f"e{i}", tick=i)
    chs = list_chapters(db, w, br.id, strategy=STRATEGY_MANUAL)
    assert len(chs) == 1
    assert chs[0].title == "全文"


def test_manual_with_markers_creates_chapters(db, world_factory):
    w, br = world_factory()
    for i in range(10):
        _add_event(db, w, f"e{i}", tick=i)
    # 在 tick=3 和 tick=7 各下一个章节标记
    db.add(ChapterMarker(id=f"chm_{uuid.uuid4().hex[:8]}", branch_id=br.id,
                         tick=3, title="第二幕"))
    db.add(ChapterMarker(id=f"chm_{uuid.uuid4().hex[:8]}", branch_id=br.id,
                         tick=7, title="第三幕"))
    db.commit()

    chs = list_chapters(db, w, br.id, strategy=STRATEGY_MANUAL)
    # 序章 (tick<3) + 第二幕 (3-6) + 第三幕 (7-9) = 3 章
    assert len(chs) == 3
    titles = [c.title for c in chs]
    assert "序章" in titles
    assert "第二幕" in titles
    assert "第三幕" in titles


def test_manual_first_marker_at_zero_no_prologue(db, world_factory):
    """marker 落在 tick=0 时不应再造一个空序章。"""
    w, br = world_factory()
    for i in range(5):
        _add_event(db, w, f"e{i}", tick=i)
    db.add(ChapterMarker(id=f"chm_{uuid.uuid4().hex[:8]}", branch_id=br.id,
                         tick=0, title="开篇"))
    db.commit()

    chs = list_chapters(db, w, br.id, strategy=STRATEGY_MANUAL)
    titles = [c.title for c in chs]
    assert "序章" not in titles
    assert chs[0].title == "开篇"


# ---- tick_lo / tick_hi 过滤 ----

def test_list_chapters_respects_tick_range(db, world_factory):
    w, br = world_factory()
    for i in range(10):
        _add_event(db, w, f"e{i}", tick=i)
    chs = list_chapters(db, w, br.id, strategy=STRATEGY_SINGLE,
                        tick_lo=3, tick_hi=6)
    # 只保留 tick 3..6 的 4 个事件
    assert len(chs) == 1
    assert len(chs[0].event_ids) == 4
