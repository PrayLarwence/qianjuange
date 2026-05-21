"""分支 (Branch) 与甘特图 / 切换分支 API。

4 端点：
- GET    /worlds/{id}/branches
- GET    /worlds/{id}/gantt
- PATCH  /branches/{id}
- DELETE /branches/{id}
- POST   /worlds/{id}/switch_branch/{id}
"""
from __future__ import annotations
import logging
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..models import (
    get_db, World, Branch, Entity, Event, CausalLink, NarrativeLog, ChapterMarker,
)

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/worlds/{world_id}/branches")
def list_branches(world_id: str, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    branches = db.query(Branch).filter_by(world_id=world_id).order_by(Branch.created_at).all()
    out = []
    for b in branches:
        event_count = db.query(Event).filter_by(branch_id=b.id, deleted=0).count()
        deleted_count = db.query(Event).filter_by(branch_id=b.id, deleted=1).count()
        max_tick = db.query(Event.tick).filter_by(branch_id=b.id, deleted=0).order_by(Event.tick.desc()).first()
        entity_count = db.query(Entity).filter_by(branch_id=b.id).count()
        out.append({
            "id": b.id,
            "name": b.name,
            "description": b.description,
            "parent_branch_id": b.parent_branch_id,
            "diverged_at_tick": b.diverged_at_tick,
            "is_active": b.id == world.active_branch_id,
            "is_main": b.parent_branch_id is None,
            "event_count": event_count,
            "deleted_event_count": deleted_count,
            "entity_count": entity_count,
            "max_tick": (max_tick[0] if max_tick else 0),
            "created_at": b.created_at.isoformat() if b.created_at else None,
        })
    return out


@router.get("/worlds/{world_id}/gantt")
def world_gantt(
    world_id: str,
    branch_ids: str | None = None,  # comma-separated; default = all
    db: Session = Depends(get_db),
):
    """Compact snapshot for the multi-branch timeline view.

    Returns events, causal links and chapter markers across the requested
    branches in a flat structure. Designed to be cheap (no entity/state) so
    we can re-poll on every step without redrawing the whole world.
    """
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    all_branches = db.query(Branch).filter_by(world_id=world_id).order_by(Branch.created_at).all()
    if branch_ids:
        wanted = {b.strip() for b in branch_ids.split(",") if b.strip()}
        branches = [b for b in all_branches if b.id in wanted]
    else:
        branches = all_branches
    bids = [b.id for b in branches]
    if not bids:
        return {"branches": [], "events": [], "causal_links": [], "chapters": []}

    events = db.query(Event).filter(Event.branch_id.in_(bids), Event.deleted == 0).all()
    links = db.query(CausalLink).filter(CausalLink.branch_id.in_(bids)).all()
    chapters = db.query(ChapterMarker).filter(ChapterMarker.branch_id.in_(bids)).all()
    return {
        "branches": [{
            "id": b.id, "name": b.name,
            "parent_branch_id": b.parent_branch_id,
            "diverged_at_tick": b.diverged_at_tick,
            "is_active": b.id == world.active_branch_id,
        } for b in branches],
        "events": [{
            "id": e.id, "branch_id": e.branch_id, "tick": e.tick,
            "title": e.title, "description": e.description or "",
            "participants": e.participants or [],
            "consequences": e.consequences or [],
        } for e in events],
        "causal_links": [{
            "id": l.id, "branch_id": l.branch_id,
            "cause_event_id": l.cause_event_id, "effect_event_id": l.effect_event_id,
            "weight": l.weight,
        } for l in links],
        "chapters": [{
            "id": cm.id, "branch_id": cm.branch_id,
            "tick": cm.tick, "title": cm.title or "",
        } for cm in chapters],
        "current_tick": world.current_tick,
        "active_branch_id": world.active_branch_id,
    }


class BranchPatch(BaseModel):
    name: str | None = None
    description: str | None = None


@router.patch("/branches/{branch_id}")
def patch_branch(branch_id: str, payload: BranchPatch, db: Session = Depends(get_db)):
    b = db.query(Branch).filter_by(id=branch_id).first()
    if not b:
        raise HTTPException(404, "branch not found")
    if payload.name is not None and payload.name.strip():
        b.name = payload.name.strip()
    if payload.description is not None:
        b.description = payload.description
    db.commit()
    return {"ok": True}


@router.delete("/branches/{branch_id}")
def delete_branch(branch_id: str, db: Session = Depends(get_db)):
    b = db.query(Branch).filter_by(id=branch_id).first()
    if not b:
        raise HTTPException(404, "branch not found")
    if b.parent_branch_id is None:
        raise HTTPException(400, "cannot delete main branch")
    children = db.query(Branch).filter_by(parent_branch_id=branch_id).count()
    if children > 0:
        raise HTTPException(400, f"branch has {children} child branches; delete them first")
    world = db.query(World).filter_by(id=b.world_id).first()
    if world and world.active_branch_id == branch_id:
        main = db.query(Branch).filter_by(world_id=b.world_id, parent_branch_id=None).first()
        if main:
            world.active_branch_id = main.id
    db.query(NarrativeLog).filter_by(branch_id=branch_id).delete(synchronize_session=False)
    db.query(CausalLink).filter_by(branch_id=branch_id).delete(synchronize_session=False)
    db.query(Event).filter_by(branch_id=branch_id).delete(synchronize_session=False)
    db.query(Entity).filter_by(branch_id=branch_id).delete(synchronize_session=False)
    db.delete(b)
    db.commit()
    return {"ok": True}


@router.post("/worlds/{world_id}/switch_branch/{branch_id}")
def switch_branch(world_id: str, branch_id: str, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    branch = db.query(Branch).filter_by(id=branch_id, world_id=world_id).first()
    if not branch:
        raise HTTPException(404, "branch not found")
    world.active_branch_id = branch_id
    db.commit()
    return {"ok": True, "active_branch_id": branch_id}
