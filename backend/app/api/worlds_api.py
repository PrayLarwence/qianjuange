"""世界（World）CRUD API。

4 端点：
- POST   /worlds
- GET    /worlds
- GET    /worlds/{id}
- DELETE /worlds/{id}
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
from ..engine import build_state_snapshot
from ._common import _new_id

log = logging.getLogger(__name__)
router = APIRouter()




class WorldCreate(BaseModel):
    name: str
    description: str = ""
    outline: str = ""
    rules: dict[str, Any] = Field(default_factory=dict)




@router.post("/worlds")
def create_world(payload: WorldCreate, db: Session = Depends(get_db)):
    world = World(
        id=_new_id("w"), name=payload.name,
        description=payload.description, outline=payload.outline,
        rules=payload.rules, current_tick=0,
    )
    db.add(world)
    db.flush()
    main = Branch(id=_new_id("br"), world_id=world.id, name="main", description="主世界线", parent_branch_id=None, diverged_at_tick=0)
    db.add(main)
    db.flush()
    world.active_branch_id = main.id
    db.commit()
    return {"id": world.id, "active_branch_id": main.id}


@router.get("/worlds")
def list_worlds(db: Session = Depends(get_db)):
    worlds = db.query(World).order_by(World.created_at.desc()).all()
    return [{"id": w.id, "name": w.name, "description": w.description, "current_tick": w.current_tick, "active_branch_id": w.active_branch_id} for w in worlds]


@router.get("/worlds/{world_id}")
def get_world(world_id: str, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    return build_state_snapshot(db, world)


@router.delete("/worlds/{world_id}")
def delete_world(world_id: str, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    branches = db.query(Branch).filter_by(world_id=world_id).all()
    bids = [b.id for b in branches]
    if bids:
        db.query(NarrativeLog).filter(NarrativeLog.branch_id.in_(bids)).delete(synchronize_session=False)
        db.query(CausalLink).filter(CausalLink.branch_id.in_(bids)).delete(synchronize_session=False)
        db.query(Event).filter(Event.branch_id.in_(bids)).delete(synchronize_session=False)
        db.query(Entity).filter(Entity.branch_id.in_(bids)).delete(synchronize_session=False)
    world.active_branch_id = None
    db.flush()
    db.query(Branch).filter_by(world_id=world_id).delete(synchronize_session=False)
    db.delete(world)
    db.commit()
    try:
        from ..engine import worldgen
        worldgen.delete(world_id)
    except Exception as e:
        log.warning("failed to delete map for %s: %s", world_id, e)
    return {"ok": True}

