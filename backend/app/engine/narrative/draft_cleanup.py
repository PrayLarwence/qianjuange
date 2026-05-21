"""草稿清理工具。

阶段 0 已建好 NarrativeLog.role 字段后，每个回合可能产生多种 role：
- director_draft (Director 粗稿，临时材料)
- author_final   (Author 定稿，长期保留)
- editor_critique(Editor 评注，用户决定是否保留)
- reader_feedback(Reader 读后感，下回合喂给 Director 后即可清理)

director_draft 是"短期生产副产品"，按用户决定只保留最近 3 个 tick 的草稿。
A3 阶段 Author 落地后会在 step 流程结束时调一次本工具。
"""
from __future__ import annotations
from sqlalchemy.orm import Session
from sqlalchemy import distinct
from ...models import NarrativeLog


# 用户决策：草稿最多保留 3 轮
DRAFT_RETENTION_TICKS = 3


def cleanup_old_drafts(db: Session, branch_id: str, retention: int = DRAFT_RETENTION_TICKS) -> int:
    """清理某分支下过期的 director_draft。

    保留策略：保留 tick 最大的 retention 个 distinct tick 上的所有草稿，
    其余全部删除。返回删除的草稿条数。

    用 distinct tick 而非"最近 N 条"是因为同一 tick 可能产生多条 draft
    （比如多次 narrate 调用），按 tick 分组才能正确保留"最近 3 个回合"。
    """
    if retention < 0:
        retention = 0

    # 该分支所有 draft 的 distinct tick，降序
    rows = (
        db.query(distinct(NarrativeLog.tick))
        .filter(
            NarrativeLog.branch_id == branch_id,
            NarrativeLog.role == "director_draft",
        )
        .order_by(NarrativeLog.tick.desc())
        .all()
    )
    ticks_desc = [r[0] for r in rows]
    if len(ticks_desc) <= retention:
        return 0

    keep_ticks = set(ticks_desc[:retention])
    delete_q = db.query(NarrativeLog).filter(
        NarrativeLog.branch_id == branch_id,
        NarrativeLog.role == "director_draft",
        ~NarrativeLog.tick.in_(keep_ticks) if keep_ticks else True,
    )
    deleted = delete_q.count()
    delete_q.delete(synchronize_session=False)
    db.commit()
    return deleted


def cleanup_old_reader_feedback(db: Session, branch_id: str, retention: int = 1) -> int:
    """清理过期的 reader_feedback。

    Reader Critic 的反馈只在"下回合 Director prompt"里被消费一次，之后
    就是历史档案。默认只保留最新 1 条；老的删掉防止 narrative_logs 膨胀。
    """
    rows = (
        db.query(NarrativeLog.id)
        .filter(
            NarrativeLog.branch_id == branch_id,
            NarrativeLog.role == "reader_feedback",
        )
        .order_by(NarrativeLog.tick.desc(), NarrativeLog.created_at.desc())
        .all()
    )
    if len(rows) <= retention:
        return 0
    keep_ids = {r[0] for r in rows[:retention]}
    delete_q = db.query(NarrativeLog).filter(
        NarrativeLog.branch_id == branch_id,
        NarrativeLog.role == "reader_feedback",
        ~NarrativeLog.id.in_(keep_ids) if keep_ids else True,
    )
    deleted = delete_q.count()
    delete_q.delete(synchronize_session=False)
    db.commit()
    return deleted
