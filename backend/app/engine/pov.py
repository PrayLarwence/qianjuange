"""角色 POV 视角重写。

把已有章节从指定角色的第一人称视角重写：
- 只保留该角色当时在场或合理知道的信息
- 第一人称叙述
- 加入符合角色性格的内心活动
- 严禁复制改写任何受版权保护的现有作品段落
"""
from __future__ import annotations
import logging
from typing import Optional

from sqlalchemy.orm import Session

from ..models import World, Entity, NarrativeLog, ChapterMarker, Event
from ..providers import get_provider
from ..providers.base import Message
from .executor import active_branch_id
from .manuscript import _gather_chapters, _join_raw

log = logging.getLogger(__name__)


POV_SYSTEM = """你是小说编辑，负责把第三人称叙事改写成指定角色的第一人称视角。

# 严格规则
* 用第一人称（"我"）叙述，过去时为主
* 只保留 POV 角色当时在场或能合理知道的信息
* 角色不在场的部分：可简略带过、用传闻/听说处理，或干脆跳过
* 适度加入符合角色性格的内心活动、感受、判断
* 不引入新情节、不扭曲已有事实
* 保留所有人名、地名、设定术语
* 严禁复制、改写任何受版权保护的现有作品段落
* 输出纯叙事文本，不要章节标题
"""


def _entity_brief(e: Entity) -> str:
    bits = [f"姓名：{e.name}", f"类型：{e.type}"]
    if e.summary:
        bits.append(f"简介：{e.summary[:200]}")
    if e.attributes:
        attrs = "、".join(f"{k}={v}" for k, v in list(e.attributes.items())[:10])
        bits.append(f"属性：{attrs}")
    return "\n".join(bits)


def _rewrite_chapter(
    char: Entity, title: str, raw_text: str,
    style_hint: str,
    provider_key: Optional[str],
) -> str:
    if not raw_text.strip():
        return ""
    user = (
        f"# POV 角色\n{_entity_brief(char)}\n\n"
        f"# 章节：{title}\n\n"
        f"# 风格要求\n{style_hint or '自然口语化、有内心活动、第一人称、过去时'}\n\n"
        f"# 原始第三人称叙事\n{raw_text}\n\n"
        f"# 输出要求\n直接输出该角色第一人称视角的章节正文（不要标题、不要前言）。"
        f"角色不在场的部分用'后来我才听说'之类的方式带过，或省略。"
    )
    provider = get_provider(provider_key) if provider_key else get_provider()
    try:
        resp = provider.chat(
            system=POV_SYSTEM,
            messages=[Message(role="user", content=user)],
            tools=[],
            max_tokens=3500,
            temperature=0.6,
        )
        text = getattr(resp, "text", None) or getattr(resp, "content", None) or ""
        return text.strip()
    except Exception as e:
        log.warning("pov rewrite failed: %s", e)
        return ""


def build_pov_manuscript(
    db: Session, world: World,
    entity_id: str,
    fmt: str = "markdown",
    style_hint: str = "",
    chapter_range: Optional[tuple[int, int]] = None,
    provider_key: Optional[str] = None,
) -> dict:
    branch_id = active_branch_id(world)
    char = db.query(Entity).filter_by(id=entity_id, branch_id=branch_id).first()
    if not char:
        raise ValueError("entity not found in active branch")

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
        body = _rewrite_chapter(char, ch["title"], raw, style_hint, provider_key)
        if not body:
            continue
        total_chars += len(body)
        rendered.append({
            "title": ch["title"],
            "tick_start": ch["tick_start"],
            "tick_end": ch["tick_end"],
            "body": body,
        })

    if fmt == "json":
        return {
            "format": "json",
            "world_name": world.name,
            "pov_name": char.name,
            "pov_id": char.id,
            "chapters": rendered,
            "total_chars": total_chars,
            "chapter_count": len(rendered),
        }

    if fmt == "text":
        lines = [f"{world.name} —— {char.name} 视角", "=" * 40, ""]
        for ch in rendered:
            lines.append(ch["title"])
            lines.append("-" * 20)
            lines.append(ch["body"])
            lines.append("")
        return {
            "format": "text",
            "world_name": world.name,
            "pov_name": char.name,
            "pov_id": char.id,
            "content": "\n".join(lines),
            "total_chars": total_chars,
            "chapter_count": len(rendered),
        }

    md = [f"# {world.name}", f"> {char.name} 视角", ""]
    for ch in rendered:
        md.append(f"## {ch['title']}")
        md.append("")
        md.append(ch["body"])
        md.append("")
    return {
        "format": "markdown",
        "world_name": world.name,
        "pov_name": char.name,
        "pov_id": char.id,
        "content": "\n".join(md),
        "total_chars": total_chars,
        "chapter_count": len(rendered),
    }
