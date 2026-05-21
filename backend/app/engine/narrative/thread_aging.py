"""C4: 标记 opened 太久仍未 closed 的 plot thread。

纯本地计算，不调 LLM。规则：
- age = current_tick - opened_tick
- stale 阈值：默认 10 tick，可参数化
- 已 closed 的 thread 不参与
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from ...models import World, PlotThread


DEFAULT_STALE_AFTER = 10
DEFAULT_WARN_AFTER = 5


def aging_threads(
    db: Session, world: World,
    branch_id: Optional[str] = None,
    stale_after: int = DEFAULT_STALE_AFTER,
    warn_after: int = DEFAULT_WARN_AFTER,
) -> dict:
    bid = branch_id or world.active_branch_id
    if not bid:
        return {"current_tick": 0, "stale_after": stale_after, "warn_after": warn_after,
                "threads": [], "counts": {"fresh": 0, "warn": 0, "stale": 0}}

    current_tick = max(world.current_tick or 0, world.max_tick or 0)
    threads = (db.query(PlotThread)
               .filter_by(branch_id=bid, status="open")
               .order_by(PlotThread.opened_tick).all())

    out: list[dict] = []
    counts = {"fresh": 0, "warn": 0, "stale": 0}
    for t in threads:
        age = max(0, current_tick - (t.opened_tick or 0))
        if age >= stale_after:
            level = "stale"
        elif age >= warn_after:
            level = "warn"
        else:
            level = "fresh"
        counts[level] += 1
        out.append({
            "id": t.id,
            "title": t.title or "",
            "summary": (t.summary or "")[:300],
            "opened_tick": t.opened_tick or 0,
            "age": age,
            "level": level,
            "related_entity_ids": list(t.related_entity_ids or []),
        })

    out.sort(key=lambda r: (-r["age"], r["opened_tick"]))
    return {
        "current_tick": current_tick,
        "stale_after": stale_after,
        "warn_after": warn_after,
        "threads": out,
        "counts": counts,
    }
