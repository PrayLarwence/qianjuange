"""B1 章节回顾（recap）：每章一两句话，Director 推演下一段时一并塞进 prompt。

为什么要这个：
LLM 写到第十章时，前文太长塞不进上下文窗口；recent_events 是事件标题
（细粒度），章节回顾是"时间跨度更长但更精炼"的视角，两者互补。

设计取舍：
- summary 直接存在 ChapterMarker.summary 字段（一一对应，不开新表）
- 生成入口是手动批量（POST /worlds/{id}/chapters/regenerate-summaries），
  不在创建章节时同步阻塞——LLM 调用 10-30 秒会让标记体验崩溃
- 渲染时按 tick 升序，跳过没 summary 的章节（兼容老数据）
- world.rules.disable_chapter_recap = True 时关闭
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from ..models import World, Branch, ChapterMarker, NarrativeLog
from ..providers import LLMProvider
from ..providers.base import Message
from .executor import active_branch_id
from .editor import _previous_chapter_tick

log = logging.getLogger(__name__)


SUMMARY_SYSTEM_PROMPT = """你是小说凝练编辑。任务：把一段连续叙事压缩成一句话回顾，
60-100 个汉字。要求：
- 只保留'谁/做了什么/到达什么状态'三要素
- 不写过程细节、不写心理描写、不写对话
- 一句话写完，不分段，不带'本章'/'第X章'前缀
- 输出纯文本，不要前后引导语
"""


@dataclass
class RecapResult:
    ok: bool
    reason: str = ""
    chapters_processed: int = 0
    chapters_succeeded: int = 0
    chapters_failed: int = 0


def _collect_chapter_text(db: Session, branch_id: str, tick_from: int, tick_to: int) -> str:
    """取章节范围内能展示的叙事文本：author_final 优先，没有则 narrator。"""
    rows = (
        db.query(NarrativeLog)
        .filter(
            NarrativeLog.branch_id == branch_id,
            NarrativeLog.tick >= tick_from,
            NarrativeLog.tick <= tick_to,
        )
        .order_by(NarrativeLog.tick.asc(), NarrativeLog.created_at.asc())
        .all()
    )
    by_tick: dict[int, list[NarrativeLog]] = {}
    for r in rows:
        by_tick.setdefault(r.tick, []).append(r)
    out: list[str] = []
    for tick in sorted(by_tick.keys()):
        items = by_tick[tick]
        finals = [x for x in items if x.role == "author_final" and (x.text or "").strip()]
        if finals:
            out.extend(x.text for x in finals)
            continue
        narrators = [x for x in items if x.role in ("narrator", None) and (x.text or "").strip()]
        out.extend(x.text for x in narrators)
    return "\n\n".join(out)


def generate_chapter_summary(
    db: Session, world: World, chapter: ChapterMarker, provider: LLMProvider
) -> Optional[str]:
    """单章生成 summary，写回 chapter.summary 并 commit。

    返回生成的字符串；失败返 None（不抛异常）。
    """
    branch_id = chapter.branch_id
    prev_tick = _previous_chapter_tick(db, branch_id, chapter.tick)
    tick_from = prev_tick + 1 if prev_tick >= 0 else 0
    tick_to = chapter.tick

    text = _collect_chapter_text(db, branch_id, tick_from, tick_to)
    if not text.strip():
        # 空章节也算"处理过"——写一句占位，后续 prompt 就跳过空字符串
        chapter.summary = ""
        db.flush()
        return ""

    user_prompt = (
        f"章节标题：{chapter.title or '（无题）'}\n"
        f"时间范围：t{tick_from} — t{tick_to}\n\n"
        f"原文：\n{text[:6000]}\n\n"
        f"请输出一句话回顾。"
    )
    try:
        resp = provider.chat(
            system=SUMMARY_SYSTEM_PROMPT,
            messages=[Message(role="user", content=user_prompt)],
            tools=[],
            max_tokens=200,
            temperature=0.3,
        )
    except Exception as e:
        log.warning("chapter summary LLM failed for %s: %s", chapter.id, e)
        return None

    summary = (resp.text or "").strip()
    # 防御：模型偶尔会带前缀'本章：'之类，截掉
    for prefix in ["本章：", "回顾：", "概要：", "摘要："]:
        if summary.startswith(prefix):
            summary = summary[len(prefix):].strip()
    summary = summary[:300]  # 强制 cap，再有的字也不要
    chapter.summary = summary
    db.flush()
    return summary


def regenerate_all_summaries(
    db: Session, world: World, provider: LLMProvider, only_missing: bool = False
) -> RecapResult:
    """批量生成本世界 active branch 所有章节的 summary。

    only_missing=True 时跳过已有 summary 的章节。
    """
    branch_id = active_branch_id(world)
    if not branch_id:
        return RecapResult(ok=False, reason="no active branch")

    chapters = (
        db.query(ChapterMarker)
        .filter_by(branch_id=branch_id)
        .order_by(ChapterMarker.tick.asc())
        .all()
    )
    if not chapters:
        return RecapResult(ok=True, chapters_processed=0)

    succeeded = 0
    failed = 0
    for ch in chapters:
        if only_missing and (ch.summary or "").strip():
            continue
        out = generate_chapter_summary(db, world, ch, provider)
        if out is None:
            failed += 1
        else:
            succeeded += 1
    db.commit()
    return RecapResult(
        ok=True,
        chapters_processed=succeeded + failed,
        chapters_succeeded=succeeded,
        chapters_failed=failed,
    )


def build_chapter_recap_block(db: Session, world: World) -> str:
    """渲染章节回顾块给 Director 的 prompt。

    跳过没 summary 的章节。world.rules.disable_chapter_recap=True 时返空。
    """
    if (world.rules or {}).get("disable_chapter_recap"):
        return ""
    branch_id = active_branch_id(world)
    if not branch_id:
        return ""

    chapters = (
        db.query(ChapterMarker)
        .filter_by(branch_id=branch_id)
        .order_by(ChapterMarker.tick.asc())
        .all()
    )
    items = [c for c in chapters if (c.summary or "").strip()]
    if not items:
        return ""

    lines = ["\n# 章节回顾（前文凝练，按时间顺序）"]
    for c in items:
        title = (c.title or "（无题）").strip()
        lines.append(f"- 「{title}」(至 t{c.tick})：{c.summary.strip()}")
    return "\n".join(lines)
