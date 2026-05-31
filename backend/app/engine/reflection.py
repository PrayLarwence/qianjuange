from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..models import ReflectionMemory

_REFLECTION_CAP = 2000


def build_reflection_block(db: Session, world_id: str, agent_type: str) -> str:
    rows = (
        db.query(ReflectionMemory)
        .filter(
            or_(
                ReflectionMemory.world_id == world_id,
                ReflectionMemory.world_id.is_(None),
            ),
            ReflectionMemory.agent_type == agent_type,
            ReflectionMemory.enabled == 1,
        )
        .order_by(
            # global entries first, then world-specific
            ReflectionMemory.world_id.is_(None).desc(),
            ReflectionMemory.created_at.desc(),
        )
        .all()
    )
    if not rows:
        return ""
    lines = ["# 反思记忆（历史经验）"]
    total = 0
    for r in rows:
        scope = "【全局】" if r.world_id is None else ""
        entry = f"- {scope}**{r.title}**: {r.content}"
        if total + len(entry) > _REFLECTION_CAP:
            break
        lines.append(entry)
        total += len(entry)
    return "\n".join(lines)
