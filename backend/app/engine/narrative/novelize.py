"""Turn raw event/state data into a readable novel-style markdown document.

Pipeline:
  1. slice the timeline into chapters (manual ChapterMarker, by-tick, by-count, or one chunk)
  2. for each chapter, ask the LLM to weave events into prose, with persona/voice context
  3. concatenate, prepend a frontmatter, return markdown

The LLM call is the expensive part. We expose `on_progress` so callers can
stream chapter-by-chapter status. In mock mode (no provider) we fall back to
a template renderer so the export feature still works end-to-end without keys.
"""

from __future__ import annotations
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from sqlalchemy.orm import Session

from ...models import World, Branch, Entity, Event, ChapterMarker, NarrativeLog
from ...providers import LLMProvider, Message, get_provider

log = logging.getLogger(__name__)


# Chapter slicing strategies.
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


# How many trailing characters of the previous chapter to keep as context.
PREV_TAIL_CHARS = 600

# Per-chapter LLM cap.
CHAPTER_MAX_TOKENS = 3000


SYSTEM_PROMPT = """你是一个小说改写者。你的工作是把【世界推演产生的事件流】改写成连贯、可读的中文小说章节。

铁律：
1. 不增不减剧情。事件清单里发生的事必须全都出现；事件清单里没发生的事不许编造（包括人物没说过的话、没去过的地方）。
2. 允许的"润色"只包括：把对白复原成具体台词、补全场景的天气/光线/动作细节、调整语序使叙述流畅、合并琐碎事件为一段动作描写。
3. 视角与口吻请贴合 persona：每个角色的台词必须符合其 voice（语气）字段；不要让一个"豪迈"的人说出"谨慎"的话。
4. 输出纯散文 Markdown：以 # 章节标题 开头，正文段落以空行分隔。不要列出事件编号、不要写"事件 1:"这样的元信息。
5. 不要给章节加摘要、不要写"上回提要 / 总结"。
6. 严格使用简体中文（除非世界规则另有规定）。
"""


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
            # Fall back to single chapter when user hasn't placed markers.
            return [_make_slice(1, "全文", events, None, None)]
        slices: list[ChapterSlice] = []
        # Boundary: events with tick < first marker form an "前章" prologue if any.
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
) -> dict:
    """Render a branch into novel-style markdown, chapter by chapter."""
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
        }

    if on_progress:
        on_progress({"phase": "start", "chapter_total": len(chapters)})

    # gather entity/event corpus once — cheaper than per-chapter queries
    all_event_ids = [eid for ch in chapters for eid in ch.event_ids]
    events_by_id = {
        e.id: e for e in
        db.query(Event).filter(Event.id.in_(all_event_ids)).all()
    } if all_event_ids else {}
    entities_by_id = {
        e.id: e for e in
        db.query(Entity).filter_by(branch_id=branch_id).all()
    }

    llm = provider
    if llm is None and (os.getenv("LLM_PROVIDER", "") or "").strip().lower() != "mock":
        try:
            llm = get_provider()
        except Exception:
            llm = None

    rendered: list[ChapterOutput] = []
    prev_tail = ""
    for ch in chapters:
        if on_progress:
            on_progress({
                "phase": "chapter_start",
                "index": ch.index,
                "chapter_total": len(chapters),
                "title": ch.title,
            })
        ch_events = [events_by_id[eid] for eid in ch.event_ids if eid in events_by_id]
        cast = _cast_for_chapter(ch_events, entities_by_id)
        try:
            md = _render_chapter(world, branch, ch, ch_events, cast, prev_tail, llm)
        except Exception as e:
            log.exception("chapter %d render failed", ch.index)
            md = _render_chapter_fallback(ch, ch_events, cast, error=str(e))
        rendered.append(ChapterOutput(
            index=ch.index,
            title=ch.title,
            tick_lo=ch.tick_lo,
            tick_hi=ch.tick_hi,
            markdown=md,
            event_count=len(ch_events),
        ))
        prev_tail = md[-PREV_TAIL_CHARS:]
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
        "chapters": [c.__dict__ for c in rendered],
        "markdown": full_md,
    }


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


def _cast_for_chapter(events: list[Event], entities_by_id: dict[str, Entity]) -> list[Entity]:
    """Distinct entities involved in this chapter (participants + locations)."""
    seen: set[str] = set()
    cast: list[Entity] = []
    for ev in events:
        for pid in (ev.participants or []):
            if pid in entities_by_id and pid not in seen:
                seen.add(pid)
                cast.append(entities_by_id[pid])
        if ev.location_id and ev.location_id in entities_by_id and ev.location_id not in seen:
            seen.add(ev.location_id)
            cast.append(entities_by_id[ev.location_id])
    return cast


def _render_chapter(world: World, branch: Branch, ch: ChapterSlice,
                    events: list[Event], cast: list[Entity],
                    prev_tail: str, llm: Optional[LLMProvider]) -> str:
    if llm is None:
        return _render_chapter_fallback(ch, events, cast)

    user_prompt = _build_chapter_prompt(world, branch, ch, events, cast, prev_tail)
    resp = llm.chat(
        system=SYSTEM_PROMPT,
        messages=[Message(role="user", content=user_prompt)],
        tools=[],
        max_tokens=CHAPTER_MAX_TOKENS,
        temperature=0.7,
    )
    text = (resp.text or "").strip()
    if not text:
        return _render_chapter_fallback(ch, events, cast)
    if not text.startswith("#"):
        text = f"# {ch.title}\n\n{text}"
    return text


def _build_chapter_prompt(world: World, branch: Branch, ch: ChapterSlice,
                          events: list[Event], cast: list[Entity],
                          prev_tail: str) -> str:
    parts = [
        f"## 章节：{ch.title}（tick {ch.tick_lo}–{ch.tick_hi}，共 {len(events)} 事件）",
        f"## 世界  {world.name} · 分支 {branch.name}",
        f"{world.description or ''}",
    ]
    rules = world.rules or {}
    if rules.get("tone"):
        parts.append(f"\n叙事基调：{rules['tone']}")
    if rules.get("language"):
        parts.append(f"语言风格：{rules['language']}")

    parts.append("\n## 出场人物（请贴合每个人的 voice 写台词）")
    cast_lines = []
    for e in cast:
        if e.type == "location":
            line = f"- 【地】{e.name}"
            if e.summary:
                line += f" — {e.summary}"
        else:
            persona = e.persona or {}
            voice = persona.get("voice") or ""
            drives = persona.get("drives") or []
            line = f"- {e.name}"
            if e.summary:
                line += f"（{e.summary}）"
            if voice:
                line += f"  语气：{voice}"
            if drives:
                line += f"  驱动：{','.join(drives)}"
        cast_lines.append(line)
    parts.append("\n".join(cast_lines) if cast_lines else "（无）")

    parts.append("\n## 必须改写的事件（按时间顺序，全都要在章节里出现）")
    for ev in events:
        ev_line = f"- t={ev.tick} 《{ev.title}》"
        if ev.description:
            ev_line += f"：{ev.description}"
        if ev.participants:
            names = []
            for pid in ev.participants:
                ent = next((c for c in cast if c.id == pid), None)
                if ent:
                    names.append(ent.name)
            if names:
                ev_line += f"  [参与：{', '.join(names)}]"
        if ev.consequences:
            ev_line += f"  [后果：{'; '.join(ev.consequences)}]"
        parts.append(ev_line)

    if prev_tail:
        parts.append("\n## 上一章尾段（仅供你保持笔触连贯，不要重复写出）")
        parts.append(prev_tail)

    parts.append(
        "\n现在请把上述事件改写成本章正文。开头是 `# " + ch.title + "`，"
        "正文要让事件自然地依次发生，不要列编号，不要做章末总结。"
    )
    return "\n".join(parts)


def _render_chapter_fallback(ch: ChapterSlice, events: list[Event],
                             cast: list[Entity], *, error: str = "") -> str:
    """No-LLM rendering: list events as plain prose blocks."""
    lines = [f"# {ch.title}", ""]
    if error:
        lines.append(f"> （LLM 调用失败，使用模板渲染：{error}）")
        lines.append("")
    name_by_id = {e.id: e.name for e in cast}
    for ev in events:
        lines.append(f"**t{ev.tick} · {ev.title}**")
        if ev.description:
            lines.append(ev.description)
        if ev.participants:
            who = "、".join(name_by_id.get(p, p) for p in ev.participants)
            lines.append(f"*出场：{who}*")
        if ev.consequences:
            lines.append("*后果：* " + "；".join(ev.consequences))
        lines.append("")
    return "\n".join(lines)
