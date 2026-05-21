"""Editor agent：章节切换时的连贯性审稿。

它不重新发明扫描——内核就是 consistency.run_scan，做章节级范围扫描。
A5 的新东西：
1. 章节级触发：从 ChapterMarker 反推 (tick_from, tick_to)
2. 把 issue 列表合成一段"编辑评注"文字写 NarrativeLog(role=editor_critique)
3. 第二次审同一章会清旧评注（不重复堆叠），但旧 ConsistencyIssue 保留
   （issues 是历史记录，评注只该有一份当前版本）

设计取舍：
- 没绑 style_profile_id 也照跑——Editor 是世界级的，跟风格无关
- LLM 失败 → 返回 ok=False，不抛错。理由：章节创建本身已成功，编辑失败不该
  让用户的章节标记消失；前端可以拿到 reason 决定要不要重试
- 不动 ChapterMarker 表——评注只落 NarrativeLog；章节本身只是"位置标尺"
"""
from __future__ import annotations
import logging
import uuid
from dataclasses import dataclass
from typing import Optional, Any

from sqlalchemy.orm import Session

from ...models import (
    World, Branch, ChapterMarker, ConsistencyIssue, NarrativeLog, ScanRun,
)
from ..consistency import consistency

log = logging.getLogger(__name__)


@dataclass
class EditorResult:
    ok: bool
    reason: str = ""
    scan_id: str = ""
    issue_count: int = 0
    critique_log_id: str = ""
    critique_text: str = ""
    tick_from: int = 0
    tick_to: int = 0


SEVERITY_EMOJI = {"high": "🔴", "medium": "🟡", "low": "🟢"}
SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _previous_chapter_tick(db: Session, branch_id: str, this_tick: int) -> int:
    """返回上一章节 marker 的 tick。没上一章则返回 -1（让本章覆盖 [0, this_tick]）。"""
    prev = (
        db.query(ChapterMarker)
        .filter(ChapterMarker.branch_id == branch_id, ChapterMarker.tick < this_tick)
        .order_by(ChapterMarker.tick.desc())
        .first()
    )
    return prev.tick if prev else -1


def _format_critique(chapter: ChapterMarker, issues: list[ConsistencyIssue]) -> str:
    """把 issue 列表合成一段人话评注。

    没有 issue 时也写一句正面评语——这一章过审了，给用户一个明确信号。
    """
    title = chapter.title or f"第 {chapter.tick} tick"
    if not issues:
        return f"【编辑评注 · {title}】本章未发现明显的连贯性问题，可以放心进入下一章。"

    issues_sorted = sorted(issues, key=lambda i: SEVERITY_RANK.get(i.severity or "medium", 1))
    head = f"【编辑评注 · {title}】发现 {len(issues_sorted)} 处需要关注："
    lines = [head]
    for i in issues_sorted:
        emoji = SEVERITY_EMOJI.get(i.severity or "medium", "🟡")
        cat = consistency.CATEGORY_LABELS.get(i.category or "other", i.category or "其它")
        body = (i.description or "").strip()
        sug = (i.suggestion or "").strip()
        line = f"{emoji} [{cat}] {i.title or '（未命名）'}"
        if body:
            line += f"\n   · {body}"
        if sug:
            line += f"\n   建议：{sug}"
        lines.append(line)
    return "\n\n".join(lines)


def _delete_old_critique(db: Session, branch_id: str, tick: int) -> None:
    """删除该 tick 上的旧 editor_critique 日志（重审场景）。"""
    db.query(NarrativeLog).filter_by(
        branch_id=branch_id, tick=tick, role="editor_critique"
    ).delete(synchronize_session=False)


def run_editor_for_chapter(
    db: Session,
    world: World,
    chapter: ChapterMarker,
    *,
    provider_key: Optional[str] = None,
) -> EditorResult:
    """对一个章节执行 Editor 审稿。

    会：
    1. 计算 (tick_from, tick_to) = (上一章 tick + 1, 本章 tick)
    2. 调 consistency.run_scan(scope='custom', ...)
    3. 把 issues 合成评注，落 NarrativeLog(role=editor_critique)
    4. 返回 EditorResult
    """
    branch_id = chapter.branch_id
    this_tick = int(chapter.tick or 0)
    prev_tick = _previous_chapter_tick(db, branch_id, this_tick)
    tick_from = prev_tick + 1 if prev_tick >= 0 else 0
    tick_to = this_tick

    if tick_from > tick_to:
        return EditorResult(
            ok=False,
            reason=f"章节范围非法：tick_from={tick_from} > tick_to={tick_to}",
            tick_from=tick_from, tick_to=tick_to,
        )

    try:
        run = consistency.run_scan(
            db, world,
            scope="custom",
            tick_from=tick_from,
            tick_to=tick_to,
            provider_key=provider_key,
        )
    except Exception as e:
        log.exception("editor scan crashed")
        return EditorResult(
            ok=False, reason=f"扫描失败: {str(e)[:200]}",
            tick_from=tick_from, tick_to=tick_to,
        )

    if run.status == "failed":
        return EditorResult(
            ok=False, reason=run.error or "扫描失败",
            scan_id=run.id, tick_from=tick_from, tick_to=tick_to,
        )

    issues = (
        db.query(ConsistencyIssue)
        .filter_by(scan_id=run.id)
        .order_by(ConsistencyIssue.created_at.asc())
        .all()
    )

    critique_text = _format_critique(chapter, issues)

    _delete_old_critique(db, branch_id, this_tick)
    log_row = NarrativeLog(
        id=f"nar_{uuid.uuid4().hex[:10]}",
        branch_id=branch_id,
        tick=this_tick,
        role="editor_critique",
        text=critique_text,
        revision_index=0,
    )
    db.add(log_row)
    db.commit()

    return EditorResult(
        ok=True,
        scan_id=run.id,
        issue_count=len(issues),
        critique_log_id=log_row.id,
        critique_text=critique_text,
        tick_from=tick_from,
        tick_to=tick_to,
    )


def get_chapter_critique(db: Session, chapter: ChapterMarker) -> dict[str, Any]:
    """取该章节当前的评注 + issues。没审过则 has_critique=False。"""
    branch_id = chapter.branch_id
    this_tick = int(chapter.tick or 0)
    prev_tick = _previous_chapter_tick(db, branch_id, this_tick)
    tick_from = prev_tick + 1 if prev_tick >= 0 else 0

    log_row = (
        db.query(NarrativeLog)
        .filter_by(branch_id=branch_id, tick=this_tick, role="editor_critique")
        .first()
    )
    issues = (
        db.query(ConsistencyIssue)
        .filter(
            ConsistencyIssue.branch_id == branch_id,
            ConsistencyIssue.tick_start >= tick_from,
            ConsistencyIssue.tick_end <= this_tick,
        )
        .order_by(ConsistencyIssue.created_at.desc())
        .all()
    )
    return {
        "chapter_id": chapter.id,
        "chapter_title": chapter.title or "",
        "tick_from": tick_from,
        "tick_to": this_tick,
        "has_critique": log_row is not None,
        "critique_text": log_row.text if log_row else "",
        "critique_log_id": log_row.id if log_row else "",
        "issues": [
            {
                "id": i.id,
                "category": i.category,
                "severity": i.severity,
                "title": i.title,
                "description": i.description,
                "suggestion": i.suggestion,
                "status": i.status,
                "tick_start": i.tick_start,
                "tick_end": i.tick_end,
                "entity_ids": i.entity_ids or [],
            }
            for i in issues
        ],
    }
