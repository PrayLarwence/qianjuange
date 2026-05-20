"""Multi-agent step: each focal character has its own LLM turn.

Flow:
  1. pick a roster of focal characters (caller passes ids, or "auto").
  2. for each focal, build a character_view, run a SHORT LLM turn with a
     restricted tool set that only lets them express intent — speak,
     move_to, propose_action, observe. They cannot directly add_event,
     create_entity, or otherwise mutate world state.
  3. collect all intents into a single bundle.
  4. hand the bundle to a "director" pass which runs the normal
     simulator.run_step with a directive like "resolve these intents
     into actual events". The director sees the full state and picks
     winners, decides outcomes, etc.

Why not just let each character call add_event directly?
  - Conflicts: two characters say "I attack first" — someone has to
    arbitrate. The director is that someone.
  - Memory bookkeeping: events created by the director go through the
    existing _append_event_to_participant_memories hook, so participant
    memories update consistently for the *resolved* outcome, not each
    side's wishful intent.
  - Truth vs claim: a character's `speak` may be a lie. We record it as
    a claim; the director decides what actually happened in narration.
"""

from __future__ import annotations
import json
import logging
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from ..models import World, Entity
from ..providers import LLMProvider, Message, ToolSpec, get_provider
from .character_view import build_character_view, view_as_prompt
from .executor import active_branch_id
from . import simulator

log = logging.getLogger(__name__)


# Restricted tool surface for character sub-agents. Each call expresses
# an INTENT — what the character wants/says/notices — never a world fact.
SUBAGENT_TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="speak",
        description="说一句话或一段话。这是你公开的发言（旁人可听见）。如果你在撒谎，请如实写下你想说的内容；导演会决定旁人是否相信。",
        parameters={
            "type": "object",
            "properties": {
                "text":      {"type": "string"},
                "to":        {"type": "array", "items": {"type": "string"}, "description": "目标实体 id 列表（可选）"},
                "is_lie":    {"type": "boolean", "description": "你是否清楚自己在说谎"},
            },
            "required": ["text"],
        },
    ),
    ToolSpec(
        name="move_to",
        description="表达『我要去某个坐标/地点』的意图。导演会处理实际移动与冲突。",
        parameters={
            "type": "object",
            "properties": {
                "x":      {"type": "integer"},
                "y":      {"type": "integer"},
                "target_entity_id": {"type": "string", "description": "或者直接给出目标实体 id（如某个地标 location）"},
                "reason": {"type": "string"},
            },
            "required": [],
        },
    ),
    ToolSpec(
        name="propose_action",
        description="提议任意非言语动作：进攻、撤退、抢夺、施法、签字……写清楚动作和对象。导演决定成败。",
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "动作描述，如 'attack X with sword'、'plant evidence'、'cast fireball'"},
                "target_entity_id": {"type": "string"},
                "intensity": {"type": "string", "description": "low / medium / high"},
                "reason":  {"type": "string"},
            },
            "required": ["action"],
        },
    ),
    ToolSpec(
        name="observe",
        description="表达『我注意到/记下了某件事』。导演会把这条记入你的记忆。",
        parameters={
            "type": "object",
            "properties": {
                "text":   {"type": "string"},
                "about":  {"type": "string", "description": "相关的实体 id（可选）"},
            },
            "required": ["text"],
        },
    ),
    ToolSpec(
        name="end_turn",
        description="本回合不再行动。",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
]


SUBAGENT_SYSTEM_PROMPT = """你扮演一个具体的角色，**只能以这个角色的视角行动**。

你看到的世界状态只包含：你自己、你认识的人、你眼前能看见的东西、以及你亲历或听说的事件。
凡是你"不知道"的事（在 knowledge_blindspots 里、或不在视野/记忆里），你必须装作不知道。
不要替别的角色思考；不要给出全知叙事；不要使用你这个角色不会拥有的信息。

通过工具表达你这一回合想说什么、想做什么：
  - speak:           说话
  - move_to:         去某处
  - propose_action:  动手/施法/任何非言语动作
  - observe:         记下你注意到的细节
  - end_turn:        不再行动

你可以多次调用工具。说完做完后调用 end_turn。
不要写大段独白；用工具调用说话。
"""


# How many tool-call hops a single sub-agent gets per turn.
SUBAGENT_MAX_HOPS = 5


def run_subagent_turn(
    db: Session,
    world: World,
    character_id: str,
    *,
    extra_directive: Optional[str] = None,
    provider: Optional[LLMProvider] = None,
) -> dict:
    """One LLM turn from one character's POV. Returns intents (no world mutation)."""
    llm = provider or get_provider()
    view = build_character_view(db, world, character_id)
    me = view["viewer"]

    user_prompt = view_as_prompt(view)
    if extra_directive:
        user_prompt += f"\n\n## 本回合导演给你的提示\n{extra_directive}"

    messages: list[Message] = [Message(role="user", content=user_prompt)]
    intents: list[dict] = []
    finished = False

    for hop in range(SUBAGENT_MAX_HOPS):
        resp = llm.chat(
            system=SUBAGENT_SYSTEM_PROMPT,
            messages=messages,
            tools=SUBAGENT_TOOLS,
            max_tokens=1024,
            temperature=0.8,
        )
        messages.append(Message(
            role="assistant",
            content=resp.text or "",
            tool_calls=list(resp.tool_calls or []),
        ))
        if not resp.tool_calls:
            break
        for tc in resp.tool_calls:
            if tc.name == "end_turn":
                finished = True
                ack = {"ok": True, "ended": True}
            else:
                intents.append({
                    "character_id": character_id,
                    "character_name": me["name"],
                    "type": tc.name,
                    "args": tc.arguments or {},
                })
                ack = {"ok": True, "recorded": tc.name}
            messages.append(Message(
                role="tool",
                content=json.dumps(ack, ensure_ascii=False),
                tool_call_id=tc.id,
                tool_name=tc.name,
            ))
        if finished:
            break

    return {
        "character_id": character_id,
        "character_name": me["name"],
        "intents": intents,
        "hops": hop + 1,
        "finished": finished,
    }


def pick_focal_characters(db: Session, world: World, limit: int = 4) -> list[str]:
    """Auto-pick characters likely to act this tick.

    Heuristic: alive characters, prefer those whose last memory is recent
    (involved in latest events) or who have a pending move target.
    """
    bid = active_branch_id(world)
    chars = (db.query(Entity)
               .filter_by(branch_id=bid, alive=1, type="character")
               .all())

    def recency(e: Entity) -> int:
        mems = e.memories or []
        if not mems:
            return -1
        last = mems[-1]
        return int(last.get("tick") or 0)

    chars.sort(key=lambda e: (recency(e), e.target_x is not None), reverse=True)
    return [e.id for e in chars[:limit]]


def run_multi_agent_step(
    db: Session,
    world: World,
    character_ids: Optional[list[str]] = None,
    *,
    user_directive: Optional[str] = None,
    provider: Optional[LLMProvider] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    on_progress: Optional[Callable[[dict], None]] = None,
) -> dict:
    """Run one multi-agent tick:

      sub-agents emit intents → director resolves them into world events.

    If `character_ids` is None, auto-pick using pick_focal_characters.
    """
    llm = provider or get_provider()
    if character_ids is None:
        character_ids = pick_focal_characters(db, world)
    if not character_ids:
        # fall back to single-agent step
        return simulator.run_step(db, world, user_directive=user_directive, provider=llm)

    if on_progress:
        on_progress({"phase": "subagents_start", "count": len(character_ids)})

    intent_bundles: list[dict] = []
    for idx, cid in enumerate(character_ids):
        if cancel_check and cancel_check():
            raise simulator.CancelledError()
        if on_progress:
            on_progress({"phase": "subagent_turn", "index": idx, "total": len(character_ids), "character_id": cid})
        try:
            bundle = run_subagent_turn(db, world, cid, provider=llm)
            intent_bundles.append(bundle)
        except ValueError as e:
            log.warning("skip subagent %s: %s", cid, e)
            continue

    if on_progress:
        on_progress({"phase": "director_start", "intent_count": sum(len(b["intents"]) for b in intent_bundles)})

    director_directive = _format_director_directive(intent_bundles, user_directive)
    director_result = simulator.run_step(
        db, world,
        user_directive=director_directive,
        provider=llm,
        cancel_check=cancel_check,
        on_progress=on_progress,
    )

    return {
        "ok": True,
        "tick": director_result.get("tick"),
        "tick_start": director_result.get("tick_start"),
        "subagents": intent_bundles,
        "director": director_result,
    }


def _format_director_directive(intent_bundles: list[dict], user_directive: Optional[str]) -> str:
    """Render the bundle of character intents as a director-facing prompt."""
    parts = [
        "## 本回合各角色的意图（character sub-agent 产出）",
        "下面是每个登场角色这一回合想说/想做的事。请你作为导演，按以下原则把它们落成实际事件：",
        "1. 角色说的话不一定是真的。如果他们 is_lie=true，那只是他们想让别人相信的内容。",
        "2. 多个角色冲突时，按地图位置、能力、动机权衡，决定谁的意图实现、谁失败。",
        "3. 用 add_event 落下真正发生的事；participants 必须包含相关角色。",
        "4. 用 update_entity / set_position / move_entity 反映状态变化。",
        "5. 必要时 narrate 一段散文段落给读者。",
        "6. 完成后 end_turn。",
    ]
    for b in intent_bundles:
        parts.append(f"\n### {b['character_name']} ({b['character_id']})")
        if not b["intents"]:
            parts.append("（沉默/无行动）")
            continue
        for it in b["intents"]:
            parts.append(f"- [{it['type']}] {json.dumps(it['args'], ensure_ascii=False)}")
    if user_directive:
        parts.append(f"\n## 用户额外指令\n{user_directive}")
    return "\n".join(parts)
