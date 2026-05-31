"""Assemble novel manuscript from author_final narrative logs.

Pipeline:
  1. slice the timeline into chapters (manual ChapterMarker, by-tick, by-count, or one chunk)
  2. for each chapter, collect author_final logs (produced during simulation by the Author agent)
  3. LLM editorial pass: unify voice, smooth seams, adjust pacing, fill micro-gaps
  4. fallback: direct concatenation when no LLM is available (marked as unedited)

The editorial pass does NOT invent new plot events — it reshapes existing prose into
a cohesive chapter that reads as continuous narrative rather than stitched fragments.
"""

from __future__ import annotations
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Optional

from sqlalchemy.orm import Session

from ...models import World, Branch, Entity, Event, ChapterMarker, NarrativeLog
from ...providers import LLMProvider, Message, get_provider

log = logging.getLogger(__name__)


STRATEGY_MANUAL = "manual"
STRATEGY_BY_TICK = "by_tick"
STRATEGY_BY_COUNT = "by_count"
STRATEGY_SINGLE = "single"


@dataclass
class ChapterSlice:
    index: int           # 1-based
    title: str
    tick_lo: int
    tick_hi: int
    event_ids: list[str]


@dataclass
class ChapterOutput:
    index: int
    title: str
    tick_lo: int
    tick_hi: int
    markdown: str
    event_count: int
    gap_ticks: list[int] = field(default_factory=list)
    edited: bool = False


CHAPTER_EDIT_SYSTEM = """你是一名专业小说编辑。你收到的是同一章节内、按时间顺序排列的若干段定稿文字（来自不同回合的创作）。

你的任务是将这些片段编辑成一个连贯、流畅、可直接出版的章节。

## 你必须做的
1. **统一叙事视角和时态**：消除片段之间的视角跳跃
2. **补充场景转换**：在时间/空间跳跃处加入自然的过渡（1-3 句）
3. **调整节奏**：合并过于碎片化的短段，拆分过于臃肿的长段
4. **消除拼接痕迹**：删除重复的背景交代、重复的人物介绍、段落间的割裂感
5. **统一文风**：如果不同片段风格有差异，统一到最好的那个水准
6. **保持章节完整性**：开头要有代入感，结尾要有余韵或悬念

## 你绝对不能做的
1. 不能新增情节事件（没发生的事不能编造）
2. 不能删除已发生的关键事件
3. 不能改变人物关系和情节走向
4. 不能改变人物性格和说话方式

## 输出
直接输出编辑后的完整章节正文。以 # 章节标题 开头。不要加任何编辑说明。"""


def list_chapters(
    db: Session,
    world: World,
    branch_id: str,
    *,
    strategy: str = STRATEGY_MANUAL,
    chapter_size: int = 5,
    tick_lo: Optional[int] = None,
    tick_hi: Optional[int] = None,
) -> list[ChapterSlice]:
    """Return the list of chapter slices (no LLM calls)."""
    q = db.query(Event).filter_by(branch_id=branch_id, deleted=0).order_by(Event.tick, Event.created_at)
    if tick_lo is not None:
        q = q.filter(Event.tick >= tick_lo)
    if tick_hi is not None:
        q = q.filter(Event.tick <= tick_hi)
    events = q.all()
    if not events:
        return []

    if strategy == STRATEGY_MANUAL:
        markers = (db.query(ChapterMarker)
                     .filter_by(branch_id=branch_id)
                     .order_by(ChapterMarker.tick).all())
        if not markers:
            return [_make_slice(1, "全文", events, None, None)]
        slices: list[ChapterSlice] = []
        first_tick = markers[0].tick
        if events[0].tick < first_tick:
            pro = [e for e in events if e.tick < first_tick]
            slices.append(_make_slice(len(slices) + 1, "序章", pro, None, first_tick - 1))
        for i, m in enumerate(markers):
            lo = m.tick
            hi = markers[i + 1].tick - 1 if i + 1 < len(markers) else max(e.tick for e in events)
            chunk = [e for e in events if lo <= e.tick <= hi]
            if not chunk:
                continue
            title = (m.title or "").strip() or f"第{len(slices) + 1}章"
            slices.append(_make_slice(len(slices) + 1, title, chunk, lo, hi))
        return slices

    if strategy == STRATEGY_SINGLE:
        return [_make_slice(1, "全文", events, None, None)]

    if strategy == STRATEGY_BY_TICK:
        if chapter_size <= 0:
            chapter_size = 5
        slices = []
        lo = events[0].tick
        hi_total = events[-1].tick
        idx = 1
        while lo <= hi_total:
            hi = lo + chapter_size - 1
            chunk = [e for e in events if lo <= e.tick <= hi]
            if chunk:
                slices.append(_make_slice(idx, f"第{idx}章 · t{lo}–t{min(hi, hi_total)}",
                                          chunk, lo, min(hi, hi_total)))
                idx += 1
            lo = hi + 1
        return slices

    if strategy == STRATEGY_BY_COUNT:
        if chapter_size <= 0:
            chapter_size = 8
        slices = []
        for i in range(0, len(events), chapter_size):
            chunk = events[i:i + chapter_size]
            idx = len(slices) + 1
            slices.append(_make_slice(idx, f"第{idx}章",
                                      chunk, chunk[0].tick, chunk[-1].tick))
        return slices

    raise ValueError(f"unknown strategy: {strategy}")


def _make_slice(idx: int, title: str, events: list[Event],
                lo: Optional[int], hi: Optional[int]) -> ChapterSlice:
    if lo is None:
        lo = events[0].tick
    if hi is None:
        hi = events[-1].tick
    return ChapterSlice(idx, title, lo, hi, [e.id for e in events])


def novelize_branch(
    db: Session,
    world: World,
    branch_id: str,
    *,
    strategy: str = STRATEGY_MANUAL,
    chapter_size: int = 5,
    tick_lo: Optional[int] = None,
    tick_hi: Optional[int] = None,
    provider: Optional[LLMProvider] = None,
    on_progress: Optional[Callable[[dict], None]] = None,
    smooth_transitions: bool = True,
) -> dict:
    """Assemble a branch into publishable novel markdown from author_final logs.

    When a provider is available, each chapter goes through an LLM editorial pass
    that unifies voice, smooths seams, and adjusts pacing. No new plot is invented.
    Without LLM, chapters are concatenated raw (marked edited=False).
    """
    branch = db.query(Branch).filter_by(id=branch_id).first()
    if not branch:
        raise ValueError(f"branch {branch_id} not found")

    chapters = list_chapters(db, world, branch_id,
                             strategy=strategy, chapter_size=chapter_size,
                             tick_lo=tick_lo, tick_hi=tick_hi)
    if not chapters:
        return {
            "world_name": world.name,
            "branch_name": branch.name,
            "chapters": [],
            "markdown": _frontmatter(world, branch) + "\n（这条分支还没有事件可改写）\n",
            "gaps": [],
        }

    if on_progress:
        on_progress({"phase": "start", "chapter_total": len(chapters)})

    # Collect all author_final logs for this branch in the relevant tick range
    global_lo = min(ch.tick_lo for ch in chapters)
    global_hi = max(ch.tick_hi for ch in chapters)
    _ROLE_PRIORITY = ["author_final", "narrator", "director_draft"]
    finals: list[NarrativeLog] = []
    for role in _ROLE_PRIORITY:
        finals = (
            db.query(NarrativeLog)
            .filter(
                NarrativeLog.branch_id == branch_id,
                NarrativeLog.role == role,
                NarrativeLog.tick >= global_lo,
                NarrativeLog.tick <= global_hi,
            )
            .order_by(NarrativeLog.tick.asc(), NarrativeLog.created_at.desc())
            .all()
        )
        if finals:
            break

    if not finals:
        log.warning("novelize: no narrative logs found for branch %s ticks %d-%d", branch_id, global_lo, global_hi)

    # Group by tick, keep only the latest revision per tick
    finals_by_tick: dict[int, NarrativeLog] = {}
    for f in finals:
        if f.tick not in finals_by_tick:
            finals_by_tick[f.tick] = f

    # Resolve LLM for editorial pass
    llm: Optional[LLMProvider] = None
    if smooth_transitions and provider:
        llm = provider
    elif smooth_transitions:
        try:
            llm = get_provider()
        except Exception:
            log.warning("no LLM provider available for novelize editorial pass, falling back to raw concatenation")
            llm = None

    # Build reflection block for editorial pass
    reflection_block = ""
    if llm:
        from ..reflection import build_reflection_block
        reflection_block = build_reflection_block(db, world.id, "author")

    rendered: list[ChapterOutput] = []
    for ch in chapters:
        if on_progress:
            on_progress({
                "phase": "chapter_start",
                "index": ch.index,
                "chapter_total": len(chapters),
                "title": ch.title,
            })

        # Collect author_final texts for this chapter's tick range
        tick_texts: list[tuple[int, str]] = []
        for t in range(ch.tick_lo, ch.tick_hi + 1):
            if t in finals_by_tick:
                text = (finals_by_tick[t].text or "").strip()
                if text:
                    tick_texts.append((t, text))

        # Fallback: synthesize from event descriptions if no narrative logs
        if not tick_texts:
            ev_parts: list[str] = []
            for eid in ch.event_ids:
                ev = db.query(Event).filter_by(id=eid).first()
                if ev:
                    desc = (ev.description or ev.title or "").strip()
                    if desc:
                        ev_parts.append(desc)
            if ev_parts:
                tick_texts = [(ch.tick_lo, "\n\n".join(ev_parts))]

        if not tick_texts:
            continue

        md, edited = _assemble_chapter(ch, tick_texts, llm, reflection_block)
        rendered.append(ChapterOutput(
            index=ch.index,
            title=ch.title,
            tick_lo=ch.tick_lo,
            tick_hi=ch.tick_hi,
            markdown=md,
            event_count=len(ch.event_ids),
            gap_ticks=[],
            edited=edited,
        ))

        if on_progress:
            on_progress({
                "phase": "chapter_done",
                "index": ch.index,
                "chapter_total": len(chapters),
                "chars": len(md),
            })

    full_md = _frontmatter(world, branch) + "\n" + "\n\n".join(c.markdown for c in rendered) + "\n"
    if on_progress:
        on_progress({"phase": "done", "chars": len(full_md)})

    return {
        "world_name": world.name,
        "branch_name": branch.name,
        "chapters": [
            {
                "index": c.index, "title": c.title,
                "tick_lo": c.tick_lo, "tick_hi": c.tick_hi,
                "markdown": c.markdown, "event_count": c.event_count,
                "edited": c.edited,
            }
            for c in rendered
        ],
        "markdown": full_md,
    }


def _strip_leading_title(text: str, title: str) -> str:
    """去掉文本开头的章节标题行（# 第X章 或纯文字标题）。"""
    lines = text.split("\n", 1)
    first = lines[0].strip().lstrip("#").strip()
    if first == title.strip() or first.startswith(title.strip()):
        return lines[1].lstrip("\n") if len(lines) > 1 else ""
    return text


def _assemble_chapter(
    ch: ChapterSlice,
    tick_texts: list[tuple[int, str]],
    llm: Optional[LLMProvider],
    reflection_block: str = "",
) -> tuple[str, bool]:
    """Assemble a chapter from per-tick author_final texts.

    Returns (markdown, edited) where edited=True means LLM editorial pass succeeded.
    """
    if not tick_texts:
        return f"# {ch.title}", False

    # Try LLM editorial pass
    if llm:
        edited = _edit_chapter_llm(ch, tick_texts, llm, reflection_block)
        if edited:
            body = _strip_leading_title(edited, ch.title)
            return f"# {ch.title}\n\n{body}", True

    # Fallback: direct concatenation
    parts: list[str] = [f"# {ch.title}"]
    for _tick, text in tick_texts:
        parts.append("")
        parts.append(_strip_leading_title(text, ch.title))
    return "\n".join(parts), False


def _edit_chapter_llm(
    ch: ChapterSlice,
    tick_texts: list[tuple[int, str]],
    llm: LLMProvider,
    reflection_block: str = "",
) -> Optional[str]:
    """LLM editorial pass: reshape tick fragments into a cohesive chapter."""
    segments = []
    for i, (tick, text) in enumerate(tick_texts):
        segments.append(f"--- 片段 {i+1}（tick {tick}）---\n{text}")

    total_chars = sum(len(t) for _, t in tick_texts)
    user_parts = []
    if reflection_block:
        user_parts.append(reflection_block)
    user_parts.append(
        f"章节标题：{ch.title}\n\n"
        f"以下是本章 {len(tick_texts)} 个片段的原始定稿（共约 {total_chars} 字），"
        f"请编辑为一个连贯的章节：\n\n"
        + "\n\n".join(segments)
    )
    user_prompt = "\n\n".join(user_parts)
    max_tokens = max(8192, int(total_chars * 1.3))
    try:
        resp = llm.chat(
            system=CHAPTER_EDIT_SYSTEM,
            messages=[Message(role="user", content=user_prompt)],
            tools=[],
            max_tokens=max_tokens,
            temperature=0.4,
        )
        text = (resp.text or "").strip()
        if not text:
            return None
        if not text.startswith("#"):
            text = f"# {ch.title}\n\n{text}"
        return text
    except Exception as e:
        log.warning("chapter edit failed for chapter %d: %s", ch.index, e)
        return None


def _frontmatter(world: World, branch: Branch) -> str:
    rules = world.rules or {}
    tone = rules.get("tone") or ""
    return (
        f"---\n"
        f"title: {world.name}\n"
        f"branch: {branch.name}\n"
        f"description: {world.description or ''}\n"
        + (f"tone: {tone}\n" if tone else "")
        + "---\n"
    )
