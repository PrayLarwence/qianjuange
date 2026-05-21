"""数据导出 / 导入 / 快照恢复 API。

5 端点：
- GET    /worlds/{id}/export
- POST   /worlds/import
- GET    /worlds/{id}/history
- POST   /worlds/{id}/restore/{snapshot_id}
- DELETE /snapshots/{id}
"""
from __future__ import annotations
import logging
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..models import (
    get_db, World, Branch, Entity, Event, CausalLink, NarrativeLog, Snapshot,
)
from ..engine import capture_branch_snapshot, restore_branch_snapshot
from ._common import _new_id, _id_prefix_for

log = logging.getLogger(__name__)
router = APIRouter()


EXPORT_VERSION = 1


@router.get("/worlds/{world_id}/export")
def export_world(world_id: str, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    branches = db.query(Branch).filter_by(world_id=world_id).all()
    branch_ids = [b.id for b in branches]
    entities = db.query(Entity).filter(Entity.branch_id.in_(branch_ids)).all() if branch_ids else []
    events = db.query(Event).filter(Event.branch_id.in_(branch_ids)).all() if branch_ids else []
    links = db.query(CausalLink).filter(CausalLink.branch_id.in_(branch_ids)).all() if branch_ids else []
    narration = db.query(NarrativeLog).filter(NarrativeLog.branch_id.in_(branch_ids)).all() if branch_ids else []
    return {
        "schema_version": EXPORT_VERSION,
        "exported_at": __import__("time").time(),
        "world": {
            "id": world.id,
            "name": world.name,
            "description": world.description,
            "current_tick": world.current_tick,
            "active_branch_id": world.active_branch_id,
            "rules": world.rules or {},
        },
        "branches": [{
            "id": b.id, "name": b.name, "description": b.description,
            "parent_branch_id": b.parent_branch_id, "diverged_at_tick": b.diverged_at_tick,
        } for b in branches],
        "entities": [{
            "id": e.id, "branch_id": e.branch_id, "type": e.type, "name": e.name,
            "summary": e.summary, "attributes": e.attributes or {}, "state": e.state or {},
            "location_id": e.location_id, "created_at_tick": e.created_at_tick, "alive": e.alive,
            "map_x": e.map_x, "map_y": e.map_y,
            "target_x": e.target_x, "target_y": e.target_y,
            "move_speed": e.move_speed, "sim_state": e.sim_state or {},
        } for e in entities],
        "events": [{
            "id": e.id, "branch_id": e.branch_id, "tick": e.tick, "title": e.title,
            "description": e.description, "location_id": e.location_id,
            "participants": e.participants or [], "consequences": e.consequences or [],
            "metadata": e.metadata_ or {}, "deleted": e.deleted,
        } for e in events],
        "causal_links": [{
            "id": l.id, "branch_id": l.branch_id,
            "cause_event_id": l.cause_event_id, "effect_event_id": l.effect_event_id,
            "description": l.description, "weight": l.weight,
        } for l in links],
        "narration": [{
            "id": n.id, "branch_id": n.branch_id, "tick": n.tick,
            "role": n.role, "text": n.text,
        } for n in narration],
    }




class WorldImport(BaseModel):
    payload: dict[str, Any]
    new_name: str | None = None


@router.post("/worlds/import")
def import_world(payload: WorldImport, db: Session = Depends(get_db)):
    p = payload.payload or {}
    if p.get("schema_version") != EXPORT_VERSION:
        raise HTTPException(400, f"unsupported schema_version: {p.get('schema_version')}")
    if "world" not in p or "branches" not in p:
        raise HTTPException(400, "invalid export payload")

    id_map: dict[str, str] = {}

    def remap(old_id: str | None) -> str | None:
        if not old_id:
            return None
        if old_id not in id_map:
            id_map[old_id] = _new_id(_id_prefix_for(old_id))
        return id_map[old_id]

    new_world_id = _new_id("world")
    id_map[p["world"]["id"]] = new_world_id

    new_world = World(
        id=new_world_id,
        name=payload.new_name or (p["world"]["name"] + " (导入)"),
        description=p["world"].get("description", ""),
        current_tick=p["world"].get("current_tick", 0),
        rules=p["world"].get("rules") or {},
    )
    db.add(new_world)
    db.flush()

    main_branch_id = None
    for b in p["branches"]:
        new_bid = remap(b["id"])
        parent_bid = remap(b.get("parent_branch_id")) if b.get("parent_branch_id") else None
        nb = Branch(
            id=new_bid, world_id=new_world_id, name=b["name"],
            description=b.get("description", ""),
            parent_branch_id=parent_bid, diverged_at_tick=b.get("diverged_at_tick", 0),
        )
        db.add(nb)
        if parent_bid is None and main_branch_id is None:
            main_branch_id = new_bid
    db.flush()

    new_world.active_branch_id = remap(p["world"].get("active_branch_id")) or main_branch_id
    db.flush()

    for e in p.get("entities", []):
        db.add(Entity(
            id=remap(e["id"]), branch_id=remap(e["branch_id"]),
            type=e["type"], name=e["name"], summary=e.get("summary", ""),
            attributes=e.get("attributes") or {}, aliases=e.get("aliases") or [], state=e.get("state") or {},
            location_id=remap(e.get("location_id")) if e.get("location_id") else None,
            created_at_tick=e.get("created_at_tick", 0), alive=e.get("alive", 1),
        ))
    for ev in p.get("events", []):
        db.add(Event(
            id=remap(ev["id"]), branch_id=remap(ev["branch_id"]),
            tick=ev["tick"], title=ev["title"], description=ev.get("description", ""),
            location_id=remap(ev.get("location_id")) if ev.get("location_id") else None,
            participants=[remap(pid) for pid in (ev.get("participants") or [])],
            consequences=ev.get("consequences") or [],
            metadata_=ev.get("metadata") or {}, deleted=ev.get("deleted", 0),
        ))
    for l in p.get("causal_links", []):
        db.add(CausalLink(
            id=remap(l["id"]), branch_id=remap(l["branch_id"]),
            cause_event_id=remap(l["cause_event_id"]),
            effect_event_id=remap(l["effect_event_id"]),
            description=l.get("description", ""), weight=l.get("weight", 1.0),
        ))
    for n in p.get("narration", []):
        db.add(NarrativeLog(
            id=remap(n["id"]), branch_id=remap(n["branch_id"]),
            tick=n["tick"], role=n.get("role", "narrator"), text=n.get("text", ""),
        ))
    db.commit()
    return {"ok": True, "world_id": new_world_id}




@router.get("/worlds/{world_id}/history")
def world_history(world_id: str, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    branch_id = world.active_branch_id
    snaps = db.query(Snapshot).filter_by(branch_id=branch_id).order_by(Snapshot.created_at.desc()).limit(80).all()
    return {
        "branch_id": branch_id,
        "current_tick": world.current_tick,
        "snapshots": [{
            "id": s.id,
            "tick": s.tick,
            "label": s.label or "",
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "counts": (s.payload or {}).get("counts", {}),
            "is_current": s.tick == world.current_tick,
        } for s in snaps],
    }


@router.post("/worlds/{world_id}/restore/{snapshot_id}")
def restore_snapshot(world_id: str, snapshot_id: str, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    snap = db.query(Snapshot).filter_by(id=snapshot_id).first()
    if not snap:
        raise HTTPException(404, "snapshot not found")
    if snap.branch_id != world.active_branch_id:
        raise HTTPException(400, "snapshot belongs to a different branch — switch branch first")
    try:
        capture_branch_snapshot(db, world, label=f"回滚前 · t{world.current_tick}")
        counts = restore_branch_snapshot(db, world, snap)
        db.commit()
        return {"ok": True, "restored_tick": world.current_tick, "counts": counts}
    except Exception as e:
        db.rollback()
        log.exception("restore failed")
        raise HTTPException(500, f"restore failed: {e}")


@router.delete("/snapshots/{snapshot_id}")
def delete_snapshot(snapshot_id: str, db: Session = Depends(get_db)):
    snap = db.query(Snapshot).filter_by(id=snapshot_id).first()
    if not snap:
        raise HTTPException(404, "snapshot not found")
    db.delete(snap)
    db.commit()
    return {"ok": True}
