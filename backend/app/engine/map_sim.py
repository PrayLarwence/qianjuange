"""Map simulation: physical movement of entities on the world grid.

This is *sim_tick* time, distinct from narrative_tick. Sim is cheap, fast,
and AI-free. It moves pinned entities toward their targets, with speed
modulated by terrain. Stage 3A only handles movement; contact detection
and event generation come in 3B.
"""

from __future__ import annotations
import logging
import math
from typing import Optional
from sqlalchemy.orm import Session

from ..models import World, Entity
from . import worldgen
from .executor import active_branch_id

log = logging.getLogger(__name__)


# Per-terrain speed multiplier (matches TERRAIN_* codes in worldgen.py)
TERRAIN_SPEED = {
    0: 0.0,   # deep ocean
    1: 0.0,   # ocean
    2: 0.5,   # coastal water (wading)
    3: 0.9,   # beach
    4: 1.0,   # plain
    5: 0.7,   # hill
    6: 0.4,   # mountain
    7: 0.2,   # peak
}


def _terrain_at(map_data: dict, x: int, y: int) -> int:
    h, w = map_data["terrain"].shape
    if not (0 <= x < w and 0 <= y < h):
        return 1  # treat OOB as ocean
    eff = worldgen.effective_terrain(map_data)
    return int(eff[y, x])


def _step_one(entity: Entity, map_data: dict) -> dict:
    """Move one entity one sim_tick. Returns event dict (or empty)."""
    if entity.map_x is None or entity.map_y is None:
        return {}
    if entity.target_x is None or entity.target_y is None:
        return {}

    dx = entity.target_x - entity.map_x
    dy = entity.target_y - entity.map_y
    dist = math.hypot(dx, dy)
    if dist < 0.5:
        # arrived
        old = (entity.map_x, entity.map_y)
        entity.map_x = entity.target_x
        entity.map_y = entity.target_y
        entity.target_x = None
        entity.target_y = None
        ss = dict(entity.sim_state or {})
        ss["status"] = "arrived"
        ss.pop("blocked_reason", None)
        entity.sim_state = ss
        return {"id": entity.id, "event": "arrived", "at": [entity.map_x, entity.map_y], "from": list(old)}

    # speed modulated by current terrain
    cur_terrain = _terrain_at(map_data, entity.map_x, entity.map_y)
    speed_mult = TERRAIN_SPEED.get(cur_terrain, 1.0)
    base_speed = max(0.1, float(entity.move_speed or 1.0))
    step = min(base_speed * speed_mult, dist)  # never overshoot

    if step <= 0.001:
        ss = dict(entity.sim_state or {})
        ss["status"] = "blocked"
        ss["blocked_reason"] = f"impassable terrain ({worldgen.TERRAIN_LABELS.get(cur_terrain,'?')})"
        entity.sim_state = ss
        return {"id": entity.id, "event": "blocked", "at": [entity.map_x, entity.map_y]}

    # normalize direction
    nx = entity.map_x + (dx / dist) * step
    ny = entity.map_y + (dy / dist) * step

    # Try to step. If next cell is impassable (water for now), try axis-aligned
    # alternatives so we slide along coastline instead of getting stuck.
    candidates = [
        (nx, ny),
        (entity.map_x + (1 if dx > 0 else -1 if dx < 0 else 0) * step, entity.map_y),
        (entity.map_x, entity.map_y + (1 if dy > 0 else -1 if dy < 0 else 0) * step),
    ]
    moved = False
    h, w = map_data["terrain"].shape
    for cx, cy in candidates:
        ix, iy = int(round(cx)), int(round(cy))
        if not (0 <= ix < w and 0 <= iy < h):
            continue
        if ix == entity.map_x and iy == entity.map_y:
            continue  # not actually moving — try next candidate
        t = _terrain_at(map_data, ix, iy)
        if TERRAIN_SPEED.get(t, 1.0) <= 0.001:
            continue
        entity.map_x = ix
        entity.map_y = iy
        moved = True
        break

    # If no axis-aligned candidate moved us forward, snap to target if it's
    # within one tile (last-mile case where rounding zeros out the step).
    if not moved and dist <= 1.5:
        tt = _terrain_at(map_data, entity.target_x, entity.target_y)
        if TERRAIN_SPEED.get(tt, 1.0) > 0.001:
            entity.map_x = entity.target_x
            entity.map_y = entity.target_y
            entity.target_x = None
            entity.target_y = None
            ss = dict(entity.sim_state or {})
            ss["status"] = "arrived"
            ss.pop("blocked_reason", None)
            entity.sim_state = ss
            return {"id": entity.id, "event": "arrived", "at": [entity.map_x, entity.map_y]}

    ss = dict(entity.sim_state or {})
    if moved:
        ss["status"] = "moving"
        ss.pop("blocked_reason", None)
    else:
        ss["status"] = "blocked"
        ss["blocked_reason"] = "no passable neighbor"
    entity.sim_state = ss
    return {} if moved else {"id": entity.id, "event": "blocked", "at": [entity.map_x, entity.map_y]}


def sim_tick(db: Session, world: World, n: int = 1) -> dict:
    """Advance the map simulation by N ticks.

    Returns a summary including any per-entity events that occurred and the
    final positions of all entities with pins. Significant state changes
    (arrived, first-time blocked) are also persisted as narrative events
    so future LLM steps can see what happened on the map.
    """
    map_data = worldgen.load(world.id)
    if map_data is None:
        return {"ok": False, "error": "no map"}

    bid = active_branch_id(world)
    entities = (
        db.query(Entity)
        .filter(Entity.branch_id == bid, Entity.alive == 1)
        .filter(Entity.map_x.isnot(None), Entity.map_y.isnot(None))
        .all()
    )

    # Track prior status per entity so we only emit on transitions.
    prior_status: dict[str, str] = {
        e.id: (e.sim_state or {}).get("status", "idle") for e in entities
    }
    events: list[dict] = []
    significant: list[dict] = []  # events worth persisting to narrative

    for _ in range(max(1, min(1000, int(n)))):
        for e in entities:
            ev = _step_one(e, map_data)
            if not ev:
                continue
            events.append(ev)
            kind = ev.get("event")
            new_status = (e.sim_state or {}).get("status", "idle")
            old = prior_status.get(e.id, "idle")
            if kind == "arrived" and old != "arrived":
                significant.append({
                    "kind": "arrived",
                    "entity_id": e.id,
                    "entity_name": e.name,
                    "at": ev.get("at"),
                    "from": ev.get("from"),
                })
            elif kind == "blocked" and old != "blocked":
                significant.append({
                    "kind": "blocked",
                    "entity_id": e.id,
                    "entity_name": e.name,
                    "at": ev.get("at"),
                    "reason": (e.sim_state or {}).get("blocked_reason", ""),
                })
            prior_status[e.id] = new_status

    _persist_sim_events(db, bid, world, map_data, significant)
    db.commit()

    return {
        "ok": True,
        "ticks": int(n),
        "events": events[-50:],
        "auto_events": [s["kind"] for s in significant],
        "positions": [
            {
                "id": e.id, "name": e.name, "x": e.map_x, "y": e.map_y,
                "target_x": e.target_x, "target_y": e.target_y,
                "status": (e.sim_state or {}).get("status", "idle"),
            }
            for e in entities
        ],
    }


def _persist_sim_events(db: Session, branch_id: str, world: World,
                         map_data: dict, sig: list[dict]) -> None:
    """Write significant sim transitions as narrative Event rows."""
    if not sig:
        return
    from ..models import Event
    from .executor import _new_id
    tick = world.current_tick
    for s in sig:
        x, y = s.get("at") or [None, None]
        terrain = ""
        if x is not None and y is not None:
            try:
                t = _terrain_at(map_data, int(x), int(y))
                terrain = worldgen.TERRAIN_LABELS.get(t, "")
            except Exception:
                pass
        if s["kind"] == "arrived":
            title = f"{s['entity_name']} 抵达 ({x},{y})"
            desc = f"{s['entity_name']} 抵达坐标 ({x},{y})"
            if terrain:
                desc += f"，地形：{terrain}"
            consequences = []
        else:  # blocked
            title = f"{s['entity_name']} 受阻"
            reason = s.get("reason") or ""
            desc = f"{s['entity_name']} 在 ({x},{y}) 处被{('（' + reason + '）') if reason else '地形'}阻挡"
            if terrain:
                desc += f"，所处地形：{terrain}"
            consequences = ["移动暂停"]
        ev = Event(
            id=_new_id("evt"),
            branch_id=branch_id,
            tick=tick,
            title=title,
            description=desc,
            location_id=None,
            participants=[s["entity_id"]],
            consequences=consequences,
            metadata_={"auto": True, "source": "map_sim", "kind": s["kind"]},
            deleted=0,
        )
        db.add(ev)


def set_target(entity: Entity, x: Optional[int], y: Optional[int]) -> None:
    """Set or clear a movement target."""
    if x is None or y is None:
        entity.target_x = None
        entity.target_y = None
        ss = dict(entity.sim_state or {})
        ss["status"] = "idle"
        entity.sim_state = ss
    else:
        entity.target_x = int(x)
        entity.target_y = int(y)
        ss = dict(entity.sim_state or {})
        ss["status"] = "moving"
        ss.pop("blocked_reason", None)
        entity.sim_state = ss
