"""Character-perspective state snapshot.

Where `state.build_state_snapshot` shows the LLM the world from a director's
chair (everything alive, all recent events), this module shows the world
through ONE character's eyes:

  - their own persona and full memory log
  - other entities they can plausibly perceive (same map area, or named
    in their memories)
  - events they participated in or that happened at their current location
  - explicitly NOT shown: other characters' inner persona, distant events
    they wouldn't have heard about, full attribute dumps of strangers

Every visible entity is annotated with `_visibility` so the prompt layer
can phrase things truthfully ("you see a man in black armor" rather than
"you see Lu Junyi, the Jade Qilin").
"""

from __future__ import annotations
import json
from typing import Optional

from sqlalchemy.orm import Session

from ..models import Entity, Event, World
from .executor import active_branch_id


# How many tiles around the focus character are considered "visible".
DEFAULT_SIGHT_RADIUS = 8

# Cap memory rows pushed into the prompt.
MEMORY_PROMPT_LIMIT = 40


def build_character_view(
    db: Session,
    world: World,
    character_id: str,
    *,
    sight_radius: int = DEFAULT_SIGHT_RADIUS,
    max_events: int = 25,
) -> dict:
    """Return the world as `character_id` would experience it.

    Output dict has the same top-level shape as build_state_snapshot but
    with a `viewer` block, filtered entities/events, and per-entity
    visibility annotations.
    """
    branch_id = active_branch_id(world)
    me = db.query(Entity).filter_by(id=character_id, branch_id=branch_id).first()
    if me is None:
        raise ValueError(f"character {character_id} not in active branch")

    all_alive = (db.query(Entity)
                   .filter_by(branch_id=branch_id, alive=1)
                   .all())

    # 1. recall — entity ids that show up in my memories or persona.knowledge_of
    recalled_ids: set[str] = set()
    for m in (me.memories or []):
        # event memories carry event_id; we'll resolve participants below
        pass
    persona = me.persona or {}
    for k in (persona.get("knowledge_of") or []):
        if isinstance(k, str):
            recalled_ids.add(k)

    # 2. spatial visibility — entities within sight_radius of me on the map
    visible_by_sight: set[str] = set()
    if me.map_x is not None and me.map_y is not None:
        for e in all_alive:
            if e.id == me.id or e.map_x is None or e.map_y is None:
                continue
            if abs(e.map_x - me.map_x) <= sight_radius and abs(e.map_y - me.map_y) <= sight_radius:
                visible_by_sight.add(e.id)

    # 3. event scoping — events I participated in, plus recent events at my location
    my_events = (db.query(Event)
                   .filter(Event.branch_id == branch_id, Event.deleted == 0)
                   .order_by(Event.tick.desc(), Event.created_at.desc())
                   .limit(max_events * 4)  # over-fetch then filter
                   .all())
    visible_events: list[Event] = []
    for ev in my_events:
        ps = ev.participants or []
        if me.id in ps:
            visible_events.append(ev)
        elif ev.location_id and me.location_id and ev.location_id == me.location_id:
            visible_events.append(ev)
        # spatial co-location for map-pinned events would need event coords,
        # which we don't store yet — punt.
        if len(visible_events) >= max_events:
            break

    # Pull event participants into recalled set so we can describe who was there.
    for ev in visible_events:
        for pid in (ev.participants or []):
            recalled_ids.add(pid)

    visible_ids = visible_by_sight | recalled_ids | {me.id}

    # 4. emit entities with visibility tag
    entities_view: list[dict] = []
    for e in all_alive:
        if e.id not in visible_ids:
            continue
        ev_dict = _entity_for_view(e, viewer=me,
                                    in_sight=(e.id in visible_by_sight),
                                    recalled=(e.id in recalled_ids))
        entities_view.append(ev_dict)

    return {
        "world": {
            "id": world.id,
            "name": world.name,
            "current_tick": world.current_tick,
            "branch_id": branch_id,
        },
        "viewer": {
            "id": me.id,
            "name": me.name,
            "summary": me.summary,
            "persona": persona,
            "memories": list(me.memories or [])[-MEMORY_PROMPT_LIMIT:],
            "pos": [me.map_x, me.map_y] if me.map_x is not None else None,
            "location_id": me.location_id,
            "attributes": me.attributes or {},
            "state": me.state or {},
        },
        "visible_entities": entities_view,
        "visible_events": [
            {
                "id": ev.id,
                "tick": ev.tick,
                "title": ev.title,
                "description": ev.description,
                "participants": ev.participants or [],
                "location_id": ev.location_id,
                "first_hand": me.id in (ev.participants or []),
            }
            for ev in reversed(visible_events)
        ],
    }


def _entity_for_view(e: Entity, *, viewer: Entity,
                     in_sight: bool, recalled: bool) -> dict:
    """Annotate one entity for character-view consumption."""
    out: dict = {
        "id": e.id,
        "type": e.type,
        "name": e.name if (recalled or e.id == viewer.id) else _obscure_name(e),
    }
    if e.id == viewer.id:
        # self — full info, no need for visibility filtering
        if e.summary:
            out["summary"] = e.summary
        if e.attributes:
            out["attributes"] = e.attributes
    elif recalled:
        # Person I know — give the LLM enough to act in character.
        if e.summary:
            out["summary"] = e.summary
        if e.attributes:
            out["attributes"] = e.attributes
    elif in_sight:
        # I see you but don't know you — reveal only outwardly visible info.
        if e.attributes:
            out["visible_attrs"] = _public_attributes(e.attributes)
    if e.map_x is not None and e.map_y is not None:
        out["pos"] = [e.map_x, e.map_y]
    out["_visibility"] = (
        "self" if e.id == viewer.id else
        "known" if recalled and in_sight else
        "remembered" if recalled else
        "stranger_in_sight"
    )
    return out


def _obscure_name(e: Entity) -> str:
    """Generic descriptor for unknown entities."""
    t = (e.type or "").lower()
    if t == "character":
        return "陌生人"
    if t == "location":
        return e.name  # locations are landmarks; their names are public
    if t in ("item", "object"):
        return "某物"
    return "未知"


# Attributes considered outwardly observable. Conservative whitelist —
# add to it as we surface more attrs in the engine.
_PUBLIC_ATTR_KEYS = {
    "outfit", "appearance", "weapon", "banner", "uniform",
    "landmark_kind", "size", "visible_marks",
}


def _public_attributes(attrs: dict) -> dict:
    return {k: v for k, v in attrs.items() if k in _PUBLIC_ATTR_KEYS}


def view_as_prompt(view: dict) -> str:
    """Render a character view as a prompt block, written in 2nd person."""
    v = view["viewer"]
    persona = v.get("persona") or {}
    parts = [
        f"## 你是谁",
        f"你是【{v['name']}】（{v.get('summary') or ''}）。",
    ]
    drives = persona.get("drives") or []
    if drives:
        parts.append(f"你的动机：{', '.join(drives)}")
    voice = persona.get("voice")
    if voice:
        parts.append(f"你的语气与性格：{voice}")
    blind = persona.get("knowledge_blindspots") or []
    if blind:
        parts.append(f"你不知道的事：{', '.join(blind)}（不要在思考或行动中表现出对它们的了解）")

    parts.append(f"\n## 你的现况  tick={view['world']['current_tick']}")
    if v.get("pos"):
        parts.append(f"你在地图坐标 {v['pos']}")
    if v.get("attributes"):
        parts.append(f"你的属性：{json.dumps(v['attributes'], ensure_ascii=False)}")
    if v.get("state"):
        parts.append(f"你的状态：{json.dumps(v['state'], ensure_ascii=False)}")

    mems = v.get("memories") or []
    if mems:
        parts.append(f"\n## 你的记忆（最近 {len(mems)} 条，按时间顺序）")
        for m in mems:
            parts.append(f"- t={m.get('tick','?')}  {m.get('summary','')}")

    parts.append(f"\n## 你眼中的他人（{len(view['visible_entities'])}）")
    parts.append("已知 = 你认识；陌生人 = 你看到但不认识。")
    parts.append(json.dumps(view["visible_entities"], ensure_ascii=False, indent=2))

    parts.append(f"\n## 你经历或听闻的事件（{len(view['visible_events'])}）")
    parts.append(json.dumps(view["visible_events"], ensure_ascii=False, indent=2))

    return "\n".join(parts)
