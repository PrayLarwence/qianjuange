from __future__ import annotations
import uuid
from typing import Any
from sqlalchemy.orm import Session
from ..models import World, Branch, Entity, Event, CausalLink, NarrativeLog


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def active_branch_id(world: World) -> str:
    return getattr(world, "_override_branch_id", None) or world.active_branch_id


class ToolError(Exception):
    pass


def execute_tool(db: Session, world: World, name: str, args: dict[str, Any]) -> dict[str, Any]:
    branch_id = active_branch_id(world)
    if name == "create_entity":
        return _create_entity(db, branch_id, world.current_tick, args)
    if name == "update_entity":
        return _update_entity(db, branch_id, args)
    if name == "add_event":
        return _add_event(db, branch_id, world.current_tick, args)
    if name == "update_event":
        return _update_event(db, branch_id, args)
    if name == "delete_event":
        return _delete_event(db, branch_id, args)
    if name == "link_causality":
        return _link_causality(db, branch_id, args)
    if name == "advance_time":
        return _advance_time(db, world, args)
    if name == "branch_world":
        return _branch_world(db, world, args)
    if name == "narrate":
        return _narrate(db, branch_id, world.current_tick, args)
    if name == "end_turn":
        return {"ok": True, "ended": True}
    if name == "set_position":
        return _set_position(db, world, branch_id, args)
    if name == "move_entity":
        return _move_entity(db, world, branch_id, args)
    raise ToolError(f"unknown tool: {name}")


def _create_entity(db: Session, branch_id: str, tick: int, args: dict[str, Any]) -> dict[str, Any]:
    if not args.get("type") or not args.get("name"):
        raise ToolError("create_entity: type and name required")
    entity = Entity(
        id=_new_id("ent"),
        branch_id=branch_id,
        type=args["type"],
        name=args["name"],
        summary=args.get("summary", ""),
        attributes=args.get("attributes", {}) or {},
        state={},
        location_id=args.get("location_id"),
        created_at_tick=tick,
        alive=1,
    )
    db.add(entity)
    db.commit()
    return {"ok": True, "id": entity.id}


def _update_entity(db: Session, branch_id: str, args: dict[str, Any]) -> dict[str, Any]:
    eid = args.get("id")
    if not eid:
        raise ToolError("update_entity: id required")
    entity = db.query(Entity).filter_by(id=eid, branch_id=branch_id).first()
    if not entity:
        raise ToolError(f"entity not found: {eid}")
    if "summary" in args and args["summary"] is not None:
        entity.summary = args["summary"]
    if "attributes" in args and isinstance(args["attributes"], dict):
        merged = dict(entity.attributes or {})
        merged.update(args["attributes"])
        entity.attributes = merged
    if "state" in args and isinstance(args["state"], dict):
        merged = dict(entity.state or {})
        merged.update(args["state"])
        entity.state = merged
        if "alive" in args["state"]:
            entity.alive = 1 if args["state"]["alive"] else 0
        if "location_id" in args["state"]:
            entity.location_id = args["state"]["location_id"]
    db.commit()
    return {"ok": True, "id": entity.id}


def _add_event(db: Session, branch_id: str, tick: int, args: dict[str, Any]) -> dict[str, Any]:
    if not args.get("title"):
        raise ToolError("add_event: title required")
    event = Event(
        id=_new_id("evt"),
        branch_id=branch_id,
        tick=int(args.get("tick", tick)),
        title=args["title"],
        description=args.get("description", ""),
        location_id=args.get("location_id"),
        participants=args.get("participants", []) or [],
        consequences=args.get("consequences", []) or [],
        metadata_=args.get("metadata", {}) or {},
        deleted=0,
    )
    db.add(event)
    db.flush()
    _append_event_to_participant_memories(db, branch_id, event)
    db.commit()
    return {"ok": True, "id": event.id, "tick": event.tick}


def _append_event_to_participant_memories(db: Session, branch_id: str, event: Event) -> None:
    """When an event lists participants, append it to each participant's
    memories. This is the auto-track for character sub-agents — they remember
    what they were involved in. Bystanders/onlookers are NOT auto-tracked
    here; the LLM is expected to record observation via separate tool calls.
    """
    pids = [p for p in (event.participants or []) if isinstance(p, str)]
    if not pids:
        return
    parts = (db.query(Entity)
               .filter(Entity.branch_id == branch_id, Entity.id.in_(pids))
               .all())
    summary = (event.title or "")[:80]
    for ent in parts:
        if ent.type != "character":
            continue
        mem = list(ent.memories or [])
        # Cap memory list to keep snapshot bounded; oldest fall off.
        mem.append({
            "event_id": event.id,
            "tick": event.tick,
            "summary": summary,
            "certainty": "experienced",
        })
        if len(mem) > 200:
            mem = mem[-200:]
        ent.memories = mem


def _update_event(db: Session, branch_id: str, args: dict[str, Any]) -> dict[str, Any]:
    eid = args.get("id")
    if not eid:
        raise ToolError("update_event: id required")
    event = db.query(Event).filter_by(id=eid, branch_id=branch_id).first()
    if not event:
        raise ToolError(f"event not found: {eid}")
    for field in ("title", "description", "location_id"):
        if field in args and args[field] is not None:
            setattr(event, field, args[field])
    if "tick" in args and args["tick"] is not None:
        event.tick = int(args["tick"])
    if "participants" in args and isinstance(args["participants"], list):
        event.participants = args["participants"]
    if "consequences" in args and isinstance(args["consequences"], list):
        event.consequences = args["consequences"]
    if args.get("reason"):
        meta = dict(event.metadata_ or {})
        history = meta.get("edit_history", [])
        history.append({"reason": args["reason"]})
        meta["edit_history"] = history[-10:]
        event.metadata_ = meta
    db.commit()
    return {"ok": True, "id": event.id}


def _delete_event(db: Session, branch_id: str, args: dict[str, Any]) -> dict[str, Any]:
    eid = args.get("id")
    if not eid:
        raise ToolError("delete_event: id required")
    event = db.query(Event).filter_by(id=eid, branch_id=branch_id).first()
    if not event:
        raise ToolError(f"event not found: {eid}")
    event.deleted = 1
    if args.get("reason"):
        meta = dict(event.metadata_ or {})
        meta["delete_reason"] = args["reason"]
        event.metadata_ = meta
    db.commit()
    return {"ok": True, "id": event.id, "soft_deleted": True}


def _link_causality(db: Session, branch_id: str, args: dict[str, Any]) -> dict[str, Any]:
    cause = args.get("cause_event_id")
    effect = args.get("effect_event_id")
    if not cause or not effect:
        raise ToolError("link_causality: cause_event_id and effect_event_id required")
    if not db.query(Event).filter_by(id=cause, branch_id=branch_id).first():
        raise ToolError(f"cause event not found: {cause}")
    if not db.query(Event).filter_by(id=effect, branch_id=branch_id).first():
        raise ToolError(f"effect event not found: {effect}")
    link = CausalLink(
        id=_new_id("cau"),
        branch_id=branch_id,
        cause_event_id=cause,
        effect_event_id=effect,
        description=args.get("description", ""),
        weight=float(args.get("weight", 1.0)),
    )
    db.add(link)
    db.commit()
    return {"ok": True, "id": link.id}


def _advance_time(db: Session, world: World, args: dict[str, Any]) -> dict[str, Any]:
    ticks = int(args.get("ticks", 1))
    if ticks < 1:
        raise ToolError("advance_time: ticks must be >= 1")
    world.current_tick = (world.current_tick or 0) + ticks
    db.commit()
    return {"ok": True, "current_tick": world.current_tick}


def _branch_world(db: Session, world: World, args: dict[str, Any]) -> dict[str, Any]:
    if not args.get("name"):
        raise ToolError("branch_world: name required")
    parent_id = active_branch_id(world)
    new_branch = Branch(
        id=_new_id("br"),
        world_id=world.id,
        name=args["name"],
        description=args.get("description", ""),
        parent_branch_id=parent_id,
        diverged_at_tick=world.current_tick,
    )
    db.add(new_branch)
    db.flush()
    for entity in db.query(Entity).filter_by(branch_id=parent_id).all():
        db.add(Entity(
            id=_new_id("ent"),
            branch_id=new_branch.id,
            type=entity.type,
            name=entity.name,
            summary=entity.summary,
            attributes=dict(entity.attributes or {}),
            state=dict(entity.state or {}),
            location_id=entity.location_id,
            created_at_tick=entity.created_at_tick,
            alive=entity.alive,
        ))
    db.commit()
    return {"ok": True, "branch_id": new_branch.id}


def _narrate(db: Session, branch_id: str, tick: int, args: dict[str, Any]) -> dict[str, Any]:
    text = args.get("text", "")
    if not text:
        raise ToolError("narrate: text required")
    log = NarrativeLog(id=_new_id("nar"), branch_id=branch_id, tick=tick, role="narrator", text=text)
    db.add(log)
    db.commit()
    return {"ok": True, "id": log.id}


def _load_map_or_raise(world: World):
    from . import worldgen
    data = worldgen.load(world.id)
    if data is None:
        raise ToolError("no map for this world — generate one first")
    return data


def _set_position(db: Session, world: World, branch_id: str, args: dict[str, Any]) -> dict[str, Any]:
    eid = args.get("id")
    if not eid or "x" not in args or "y" not in args:
        raise ToolError("set_position: id, x, y required")
    map_data = _load_map_or_raise(world)
    w, h = int(map_data["width"]), int(map_data["map_h"])
    x, y = int(args["x"]), int(args["y"])
    if not (0 <= x < w and 0 <= y < h):
        raise ToolError(f"set_position: ({x},{y}) out of {w}x{h}")
    entity = db.query(Entity).filter_by(id=eid, branch_id=branch_id).first()
    if not entity:
        raise ToolError(f"entity not found: {eid}")
    entity.map_x = x
    entity.map_y = y
    entity.target_x = None
    entity.target_y = None
    ss = dict(entity.sim_state or {})
    ss["status"] = "idle"
    ss.pop("blocked_reason", None)
    entity.sim_state = ss
    db.commit()
    return {"ok": True, "id": entity.id, "pos": [x, y]}


def _move_entity(db: Session, world: World, branch_id: str, args: dict[str, Any]) -> dict[str, Any]:
    from .map_sim import set_target
    eid = args.get("id")
    if not eid:
        raise ToolError("move_entity: id required")
    entity = db.query(Entity).filter_by(id=eid, branch_id=branch_id).first()
    if not entity:
        raise ToolError(f"entity not found: {eid}")

    x, y = args.get("x"), args.get("y")
    if x is None or y is None:
        set_target(entity, None, None)
        db.commit()
        return {"ok": True, "id": entity.id, "stopped": True}

    map_data = _load_map_or_raise(world)
    w, h = int(map_data["width"]), int(map_data["map_h"])
    if entity.map_x is None or entity.map_y is None:
        raise ToolError(f"entity {eid} has no position — call set_position first")
    xi, yi = int(x), int(y)
    if not (0 <= xi < w and 0 <= yi < h):
        raise ToolError(f"move_entity: ({xi},{yi}) out of {w}x{h}")
    if "speed" in args and args["speed"] is not None:
        entity.move_speed = max(0.1, float(args["speed"]))
    set_target(entity, xi, yi)
    db.commit()
    return {"ok": True, "id": entity.id, "from": [entity.map_x, entity.map_y], "to": [xi, yi]}

