"""把世界的章节+叙事整合成成稿。

输出格式：markdown / text / json
润色级别：raw（原样拼接）/ light（润色衔接句）/ unified（全文风格统一）
"""
from __future__ import annotations
import logging
from typing import Optional

from sqlalchemy.orm import Session

from ...models import World, NarrativeLog, ChapterMarker, Entity, Event
from ...providers import get_provider
from ...providers.base import Message
from ..core.executor import active_branch_id

log = logging.getLogger(__name__)


POLISH_SYSTEM = """你是小说编辑，负责把零散的叙事段落整合成连贯章节。

# 严格要求
* 不引入新情节、不删除关键事件
* 仅做语句衔接、风格统一、删除明显的记述化表述
* 保留所有已有的人名、地名、设定术语
* 输出纯叙事文本，不要章节标题（标题已由系统提供）
* 严禁复制、改写任何受版权保护的现有作品段落
* 用第三人称叙述，过去时为主
"""


def _gather_chapters(db: Session, branch_id: str) -> list[dict]:
    """按 tick 切分章节，每章带 narration 列表。

    展示规则：只取 author_final。如果某 tick 没有 author_final，跳过该 tick
    （不 fallback 到 narrator 原始事件流）。
    """
    markers = (
        db.query(ChapterMarker)
        .filter_by(branch_id=branch_id)
        .order_by(ChapterMarker.tick.asc())
        .all()
    )
    all_rows = (
        db.query(NarrativeLog)
        .filter_by(branch_id=branch_id)
        .filter(NarrativeLog.role == "author_final")
        .order_by(NarrativeLog.tick.asc(), NarrativeLog.created_at.asc())
        .all()
    )

    # 每 tick 取最新的 author_final
    by_tick: dict[int, list[NarrativeLog]] = {}
    for r in all_rows:
        by_tick.setdefault(r.tick, []).append(r)
    narrations: list[NarrativeLog] = []
    for tick in sorted(by_tick.keys()):
        items = by_tick[tick]
        finals = [x for x in items if (x.text or "").strip()]
        if finals:
            narrations.append(finals[-1])

    if not markers:
        return [{
            "title": "第一章",
            "tick_start": 0,
            "tick_end": narrations[-1].tick if narrations else 0,
            "narrations": narrations,
        }]

    chapters = []
    boundaries = [m.tick for m in markers] + [10**9]
    for i, m in enumerate(markers):
        lo = m.tick
        hi = boundaries[i + 1]
        seg = [n for n in narrations if lo <= n.tick < hi]
        chapters.append({
            "title": m.title or f"第{i+1}章",
            "tick_start": lo,
            "tick_end": seg[-1].tick if seg else lo,
            "narrations": seg,
            "note": m.note or "",
        })
    pre = [n for n in narrations if n.tick < markers[0].tick]
    if pre:
        chapters.insert(0, {
            "title": "序章",
            "tick_start": 0,
            "tick_end": pre[-1].tick,
            "narrations": pre,
        })
    return chapters


def _join_raw(narrations: list[NarrativeLog]) -> str:
    parts = []
    for n in narrations:
        text = (n.text or "").strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _polish_chapter(
    title: str, raw_text: str,
    style_hint: str,
    provider_key: Optional[str],
) -> str:
    if not raw_text.strip():
        return ""
    user = (
        f"# 章节：{title}\n\n"
        f"# 风格要求\n{style_hint or '简洁、自然、第三人称、过去时'}\n\n"
        f"# 原始素材（请整合为一章连贯叙事）\n{raw_text}\n\n"
        f"# 输出\n直接输出章节正文（不要标题、不要前言）。"
    )
    provider = get_provider(provider_key) if provider_key else get_provider()
    try:
        resp = provider.chat(
            system=POLISH_SYSTEM,
            messages=[Message(role="user", content=user)],
            tools=[],
            max_tokens=3500,
            temperature=0.55,
        )
        text = getattr(resp, "text", None) or getattr(resp, "content", None) or ""
        return text.strip() or raw_text
    except Exception as e:
        log.warning("polish chapter failed, fallback to raw: %s", e)
        return raw_text


def build_manuscript(
    db: Session, world: World,
    fmt: str = "markdown",
    polish: str = "raw",
    style_hint: str = "",
    chapter_range: Optional[tuple[int, int]] = None,
    provider_key: Optional[str] = None,
) -> dict:
    branch_id = active_branch_id(world)
    chapters = _gather_chapters(db, branch_id)

    if chapter_range:
        lo, hi = chapter_range
        chapters = chapters[max(0, lo): max(0, hi) + 1]

    rendered = []
    total_chars = 0
    for ch in chapters:
        raw = _join_raw(ch["narrations"])
        if not raw.strip():
            continue
        if polish == "raw":
            body = raw
        else:
            body = _polish_chapter(ch["title"], raw, style_hint, provider_key)
        total_chars += len(body)
        rendered.append({
            "title": ch["title"],
            "tick_start": ch["tick_start"],
            "tick_end": ch["tick_end"],
            "body": body,
        })

    # 检查是否有 narrator 但没有 author_final（提示用户需要重新推演）
    has_narrator_only = False
    if not rendered:
        narrator_count = (
            db.query(NarrativeLog)
            .filter_by(branch_id=branch_id)
            .filter(NarrativeLog.role == "narrator")
            .count()
        )
        has_narrator_only = narrator_count > 0

    if fmt == "json":
        result = {
            "format": "json",
            "world_name": world.name,
            "chapters": rendered,
            "total_chars": total_chars,
            "chapter_count": len(rendered),
        }
        if has_narrator_only:
            result["hint"] = "存在未经 Author 改写的事件记录，请重新推演以生成定稿"
        return result

    if fmt == "text":
        lines = [world.name, "=" * 40, ""]
        if has_narrator_only:
            lines.append("[提示] 存在未经 Author 改写的事件记录，请重新推演以生成定稿")
            lines.append("")
        for ch in rendered:
            lines.append(ch["title"])
            lines.append("-" * 20)
            lines.append(ch["body"])
            lines.append("")
        return {
            "format": "text",
            "world_name": world.name,
            "content": "\n".join(lines),
            "total_chars": total_chars,
            "chapter_count": len(rendered),
            **({"hint": "存在未经 Author 改写的事件记录，请重新推演以生成定稿"} if has_narrator_only else {}),
        }

    md = [f"# {world.name}", ""]
    if world.description:
        md.append(f"> {world.description}")
        md.append("")
    if has_narrator_only:
        md.append("> ⚠️ 存在未经 Author 改写的事件记录，请重新推演以生成定稿\n")
    for ch in rendered:
        md.append(f"## {ch['title']}")
        md.append("")
        md.append(ch["body"])
        md.append("")
    return {
        "format": "markdown",
        "world_name": world.name,
        "content": "\n".join(md),
        "total_chars": total_chars,
        "chapter_count": len(rendered),
        **({"hint": "存在未经 Author 改写的事件记录，请重新推演以生成定稿"} if has_narrator_only else {}),
    }
