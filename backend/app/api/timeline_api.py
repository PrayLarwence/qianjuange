"""时间线（Timeline）查询 API。

1 端点：
- GET /worlds/{id}/timeline
"""
from __future__ import annotations
import logging
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..models import (
    get_db, World, Event, CausalLink, NarrativeLog, PlotThread,
)

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/worlds/{world_id}/timeline")
def get_timeline(world_id: str, branch_id: str | None = None, include_drafts: int = 0, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    bid = branch_id or world.active_branch_id
    events = db.query(Event).filter_by(branch_id=bid, deleted=0).order_by(Event.tick).all()
    event_ids = {e.id for e in events}
    links = db.query(CausalLink).filter_by(branch_id=bid).all()
    visible_links = [l for l in links if l.cause_event_id in event_ids and l.effect_event_id in event_ids]
    narration = db.query(NarrativeLog).filter_by(branch_id=bid).order_by(NarrativeLog.tick).all()
    # 默认隐藏 director_draft（Author 改写前的粗稿，前端切到"草稿对照"才需要）。
    # editor_critique 也默认不返回——它属于 Editor 内部评注，A5 阶段会有专门端点。
    if not include_drafts:
        narration = [n for n in narration if (n.role or "narrator") not in ("director_draft", "editor_critique")]
    threads = (db.query(PlotThread)
                 .filter_by(branch_id=bid)
                 .order_by(PlotThread.opened_tick)
                 .all())
    from ..engine.state import _load_outline_block, _compute_pacing_budget
    open_count = sum(1 for t in threads if t.status == "open")
    pacing = _compute_pacing_budget(_load_outline_block(db, world), open_count)
    return {
        "events": [{
            "id": e.id, "tick": e.tick, "title": e.title, "description": e.description,
            "participants": e.participants, "location_id": e.location_id, "consequences": e.consequences,
        } for e in events],
        "links": [{"cause": l.cause_event_id, "effect": l.effect_event_id, "description": l.description, "weight": l.weight} for l in visible_links],
        "narration": [{
            "id": n.id,
            "tick": n.tick,
            "text": n.text,
            "role": n.role or "narrator",
            "parent_log_id": n.parent_log_id,
            "revision_index": n.revision_index or 0,
        } for n in narration],
        "plot_threads": [{
            "id": t.id, "title": t.title, "summary": t.summary, "status": t.status,
            "opened_tick": t.opened_tick, "closed_tick": t.closed_tick,
            "resolution": t.resolution or "",
            "related_entity_ids": t.related_entity_ids or [],
        } for t in threads],
        "pacing": pacing,  # null 当无大纲且无钩子
    }

