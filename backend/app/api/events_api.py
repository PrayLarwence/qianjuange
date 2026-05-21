"""事件 / 因果链 / reconcile 相关 API。

8 端点：
- POST   /worlds/{id}/events
- PATCH  /events/{id}
- DELETE /events/{id}
- POST   /events/{id}/restore
- POST   /worlds/{id}/causality
- PATCH  /causality
- DELETE /causality
- POST   /worlds/{id}/reconcile
"""
from __future__ import annotations
import logging
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..models import (
    get_db, World, Branch, Entity, Event, CausalLink, NarrativeLog,
)
from ..engine import run_reconcile
from ..providers import get_provider
from ._common import _new_id

log = logging.getLogger(__name__)
router = APIRouter()


class EventIn(BaseModel):
    title: str
    description: str = ""
    tick: int | None = None
    participants: list[str] = Field(default_factory=list)
    location_id: str | None = None


@router.post("/worlds/{world_id}/events")
def add_event(world_id: str, payload: EventIn, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    e = Event(
        id=_new_id("evt"), branch_id=world.active_branch_id,
        tick=payload.tick if payload.tick is not None else world.current_tick,
        title=payload.title, description=payload.description,
        participants=payload.participants, location_id=payload.location_id, consequences=[], metadata_={},
        deleted=0,
    )
    db.add(e); db.flush()
    from ..engine.executor import _append_event_to_participant_memories
    _append_event_to_participant_memories(db, world.active_branch_id, e)
    db.commit()
    return {"id": e.id, "tick": e.tick}


class EventPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    tick: int | None = None
    participants: list[str] | None = None
    location_id: str | None = None
    consequences: list[str] | None = None


@router.patch("/events/{event_id}")
def patch_event(event_id: str, payload: EventPatch, db: Session = Depends(get_db)):
    e = db.query(Event).filter_by(id=event_id).first()
    if not e:
        raise HTTPException(404, "event not found")
    if payload.title is not None: e.title = payload.title
    if payload.description is not None: e.description = payload.description
    if payload.tick is not None: e.tick = int(payload.tick)
    if payload.participants is not None: e.participants = payload.participants
    if payload.location_id is not None: e.location_id = payload.location_id
    if payload.consequences is not None: e.consequences = payload.consequences
    meta = dict(e.metadata_ or {})
    meta["user_edited"] = True
    e.metadata_ = meta
    db.commit()
    return {"ok": True}


@router.delete("/events/{event_id}")
def delete_event(event_id: str, db: Session = Depends(get_db)):
    e = db.query(Event).filter_by(id=event_id).first()
    if not e:
        raise HTTPException(404, "event not found")
    e.deleted = 1
    meta = dict(e.metadata_ or {})
    meta["user_deleted"] = True
    e.metadata_ = meta
    db.commit()
    return {"ok": True, "soft_deleted": True}


@router.post("/events/{event_id}/restore")
def restore_event(event_id: str, db: Session = Depends(get_db)):
    e = db.query(Event).filter_by(id=event_id).first()
    if not e:
        raise HTTPException(404, "event not found")
    e.deleted = 0
    db.commit()
    return {"ok": True}


class CausalityIn(BaseModel):
    cause_event_id: str
    effect_event_id: str
    description: str = ""
    weight: float = 1.0


@router.post("/worlds/{world_id}/causality")
def add_causality(world_id: str, payload: CausalityIn, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    bid = world.active_branch_id
    cause = db.query(Event).filter_by(id=payload.cause_event_id, branch_id=bid).first()
    effect = db.query(Event).filter_by(id=payload.effect_event_id, branch_id=bid).first()
    if not cause or not effect:
        raise HTTPException(400, "cause/effect event not found in active branch")
    if cause.id == effect.id:
        raise HTTPException(400, "cannot link an event to itself")
    existing = db.query(CausalLink).filter_by(
        branch_id=bid, cause_event_id=cause.id, effect_event_id=effect.id
    ).first()
    if existing:
        if payload.description: existing.description = payload.description
        existing.weight = payload.weight
        db.commit()
        return {"ok": True, "id": existing.id, "updated": True}
    link = CausalLink(
        id=_new_id("cau"), branch_id=bid,
        cause_event_id=cause.id, effect_event_id=effect.id,
        description=payload.description, weight=payload.weight,
    )
    db.add(link); db.commit()
    return {"ok": True, "id": link.id}


class CausalityPatch(BaseModel):
    description: str | None = None
    weight: float | None = None


@router.patch("/causality")
def patch_causality(cause: str, effect: str, payload: CausalityPatch, db: Session = Depends(get_db)):
    link = db.query(CausalLink).filter_by(cause_event_id=cause, effect_event_id=effect).first()
    if not link:
        raise HTTPException(404, "link not found")
    if payload.description is not None: link.description = payload.description
    if payload.weight is not None: link.weight = payload.weight
    db.commit()
    return {"ok": True}


@router.delete("/causality")
def delete_causality(cause: str, effect: str, db: Session = Depends(get_db)):
    n = db.query(CausalLink).filter_by(cause_event_id=cause, effect_event_id=effect).delete()
    db.commit()
    return {"ok": True, "deleted": n}


class ReconcileRequest(BaseModel):
    user_changes: list[str] = Field(default_factory=list, description="人话描述用户的改动")
    seed_event_ids: list[str] = Field(default_factory=list, description="被直接改动的事件 id（用于 BFS 找下游）")
    branch: bool = True
    branch_name: str | None = None
    provider: str | None = None


@router.post("/worlds/{world_id}/reconcile")
def reconcile(world_id: str, payload: ReconcileRequest, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")

    new_branch_id: str | None = None
    if payload.branch:
        parent_id = world.active_branch_id
        new_branch = Branch(
            id=_new_id("br"),
            world_id=world.id,
            name=payload.branch_name or f"reconcile@t{world.current_tick}",
            description="AI 调和分支",
            parent_branch_id=parent_id,
            diverged_at_tick=world.current_tick,
        )
        db.add(new_branch); db.flush()
        for entity in db.query(Entity).filter_by(branch_id=parent_id).all():
            db.add(Entity(
                id=_new_id("ent"), branch_id=new_branch.id, type=entity.type, name=entity.name,
                summary=entity.summary, attributes=dict(entity.attributes or {}), aliases=list(entity.aliases or []),
                state=dict(entity.state or {}), location_id=entity.location_id,
                created_at_tick=entity.created_at_tick, alive=entity.alive,
            ))
        old_to_new: dict[str, str] = {}
        for ev in db.query(Event).filter_by(branch_id=parent_id).all():
            new_id = _new_id("evt")
            old_to_new[ev.id] = new_id
            db.add(Event(
                id=new_id, branch_id=new_branch.id, tick=ev.tick, title=ev.title,
                description=ev.description, location_id=ev.location_id,
                participants=list(ev.participants or []), consequences=list(ev.consequences or []),
                metadata_=dict(ev.metadata_ or {}), deleted=ev.deleted,
            ))
        for l in db.query(CausalLink).filter_by(branch_id=parent_id).all():
            db.add(CausalLink(
                id=_new_id("cau"), branch_id=new_branch.id,
                cause_event_id=old_to_new.get(l.cause_event_id, l.cause_event_id),
                effect_event_id=old_to_new.get(l.effect_event_id, l.effect_event_id),
                description=l.description, weight=l.weight,
            ))
        for n in db.query(NarrativeLog).filter_by(branch_id=parent_id).all():
            db.add(NarrativeLog(
                id=_new_id("nar"), branch_id=new_branch.id, tick=n.tick, role=n.role, text=n.text,
            ))
        world.active_branch_id = new_branch.id
        new_branch_id = new_branch.id
        seed_event_ids = [old_to_new.get(eid, eid) for eid in payload.seed_event_ids]
        db.commit()
    else:
        seed_event_ids = list(payload.seed_event_ids)

    provider = get_provider(payload.provider) if payload.provider else None
    try:
        result = run_reconcile(db, world, payload.user_changes, seed_event_ids, provider=provider)
    except Exception as e:
        raise HTTPException(500, f"reconcile failed: {e}")

    result["branch_id"] = world.active_branch_id
    result["new_branch_created"] = new_branch_id is not None
    return result
