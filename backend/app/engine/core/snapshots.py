from __future__ import annotations
import uuid
from typing import Any
from sqlalchemy.orm import Session
from ...models import World, Branch, Entity, Event, CausalLink, NarrativeLog, Snapshot
from .executor import active_branch_id


def capture_branch_snapshot(db: Session, world: World, label: str = "") -> Snapshot:
    branch_id = active_branch_id(world)
    if not branch_id:
        raise ValueError("no active branch")

    entities = db.query(Entity).filter_by(branch_id=branch_id).all()
    events = db.query(Event).filter_by(branch_id=branch_id).all()
    links = db.query(CausalLink).filter_by(branch_id=branch_id).all()
    narration = db.query(NarrativeLog).filter_by(branch_id=branch_id).all()

    payload = {
        "world": {
            "id": world.id,
            "current_tick": world.current_tick,
            "active_branch_id": world.active_branch_id,
        },
        "entities": [{
            "id": e.id, "type": e.type, "name": e.name, "summary": e.summary,
            "attributes": e.attributes or {}, "state": e.state or {},
            "location_id": e.location_id, "created_at_tick": e.created_at_tick,
            "alive": e.alive,
        } for e in entities],
        "events": [{
            "id": ev.id, "tick": ev.tick, "title": ev.title,
            "description": ev.description, "location_id": ev.location_id,
            "participants": ev.participants or [], "consequences": ev.consequences or [],
            "metadata": ev.metadata_ or {}, "deleted": ev.deleted,
        } for ev in events],
        "causal_links": [{
            "id": l.id, "cause_event_id": l.cause_event_id,
            "effect_event_id": l.effect_event_id,
            "description": l.description, "weight": l.weight,
        } for l in links],
        "narration": [{
            "id": n.id, "tick": n.tick, "role": n.role, "text": n.text,
        } for n in narration],
        "counts": {
            "entities": len(entities),
            "events": len([ev for ev in events if not ev.deleted]),
            "links": len(links),
            "narration": len(narration),
        },
    }

    snap = Snapshot(
        id=f"snap_{uuid.uuid4().hex[:12]}",
        branch_id=branch_id,
        tick=world.current_tick,
        label=label,
        payload=payload,
    )
    db.add(snap)
    db.flush()
    return snap


def restore_branch_snapshot(db: Session, world: World, snapshot: Snapshot) -> dict:
    if snapshot.branch_id != active_branch_id(world):
        raise ValueError("snapshot belongs to a different branch than the active one")
    branch_id = snapshot.branch_id
    payload = snapshot.payload or {}

    db.query(NarrativeLog).filter_by(branch_id=branch_id).delete(synchronize_session=False)
    db.query(CausalLink).filter_by(branch_id=branch_id).delete(synchronize_session=False)
    db.query(Event).filter_by(branch_id=branch_id).delete(synchronize_session=False)
    for e in db.query(Entity).filter_by(branch_id=branch_id).all():
        e.location_id = None
    db.flush()
    db.query(Entity).filter_by(branch_id=branch_id).delete(synchronize_session=False)
    db.flush()

    for e in payload.get("entities", []):
        db.add(Entity(
            id=e["id"], branch_id=branch_id, type=e["type"], name=e["name"],
            summary=e.get("summary", ""), attributes=e.get("attributes") or {},
            state=e.get("state") or {}, location_id=None,
            created_at_tick=e.get("created_at_tick", 0), alive=e.get("alive", 1),
        ))
    db.flush()
    for e in payload.get("entities", []):
        if e.get("location_id"):
            db.query(Entity).filter_by(id=e["id"]).update({"location_id": e["location_id"]})

    for ev in payload.get("events", []):
        db.add(Event(
            id=ev["id"], branch_id=branch_id, tick=ev["tick"], title=ev["title"],
            description=ev.get("description", ""), location_id=ev.get("location_id"),
            participants=ev.get("participants") or [],
            consequences=ev.get("consequences") or [],
            metadata_=ev.get("metadata") or {}, deleted=ev.get("deleted", 0),
        ))
    for l in payload.get("causal_links", []):
        db.add(CausalLink(
            id=l["id"], branch_id=branch_id,
            cause_event_id=l["cause_event_id"],
            effect_event_id=l["effect_event_id"],
            description=l.get("description", ""), weight=l.get("weight", 1.0),
        ))
    for n in payload.get("narration", []):
        db.add(NarrativeLog(
            id=n["id"], branch_id=branch_id, tick=n["tick"],
            role=n.get("role", "narrator"), text=n.get("text", ""),
        ))

    world_payload = payload.get("world") or {}
    if "current_tick" in world_payload:
        world.current_tick = world_payload["current_tick"]

    db.flush()
    return payload.get("counts", {})
