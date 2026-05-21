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

from ...models import World, Entity
from ...providers import LLMProvider, Message, ToolSpec, get_provider
from .character_view import build_character_view, view_as_prompt
from ..core.executor import active_branch_id
from ..core import simulator

log = logging.getLogger(__name__)


# Restricted tool surface for character sub-agents. Each call expresses
# an INTENT — what the character wants/says/notices — never a world fact.
SUBAGENT_TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="speak",
        description=(
            "说一句话或一段话（旁人能听见）。"
            "**用你这个角色独有的 voice 写**——用词、节奏、口头禅、停顿都要符合 voice 描述。"
            "不要写成中性叙述，要让人一眼能从台词里认出是你这个角色在说话。"
            "说谎时也如实写下你想说的内容；导演会决定旁人是否相信。"
        ),
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
        description=(
            "提议任意非言语动作：进攻、撤退、抢夺、施法、签字……导演决定成败。"
            "**action 字段要写得有画面感**——不只是动作类型，还要带上你做这个动作时的神态/姿态/力度。"
            "差例：'attack X with sword'。"
            "好例：'横刀斜劈，肩头压低半寸，刀风没出鞘前先把对方逼退了一步'——动作里就含 voice。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "带画面感的动作描述，体现你的 voice"},
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


SUBAGENT_SYSTEM_PROMPT = """你扮演一个具体的角色。你**就是**这个角色——不是在描述他、不是在推演他，是从他的脑子里讲话和行动。

# 强约束（按优先级，违反就是失败）

1. **drives 是你的方向盘**。你看到的 user prompt 里会列出这个角色的 drives（动机）。你这一回合的每一次 speak / move_to / propose_action，必须能回答："这是我的哪个 drive 在驱动？" 如果一个动作和所有 drives 都无关，**不要做**。宁可 end_turn 也不要做不符合人设的事。

2. **voice 是你的嘴巴**。你的 speak 必须用这个 voice 描述的语气、节奏、用词习惯说话。voice 写"沉默寡言、字字斟酌"，你就不要长篇大论；写"市井泼皮、爱开玩笑"，你就不要正经文绉绉。

3. **knowledge_blindspots 是你的盲区**。列在那里的事，你**不知道**。哪怕用户 prompt 的"事件清单"里写了，你也要装作没看见——这些是上帝视角的信息，不是你这个角色的信息。

4. **视野约束**。不在你 visible_entities / 你的记忆里的人和事，你不知道。不要替别的角色思考、不要给全知叙事、不要使用你这个角色不会拥有的信息。

# 行动方式

通过工具表达这一回合：
  - speak:           说话（用你的 voice）
  - move_to:         去某处（这是为了哪个 drive？）
  - propose_action:  动手/施法/任何非言语动作（这是为了哪个 drive？）
  - observe:         记下你注意到的细节
  - end_turn:        不再行动

可以多次调用工具。说完做完后调用 end_turn。

# 笔墨（你写出来的文字会成为故事的肉）

- speak 的 text、propose_action 的 action、observe 的 text 都不是日志条目，是给读者看的小说级文字。
- 每条至少有一个细节（手抖一下、目光的方向、语气的停顿、屋外的风），不要光写"我说"或"我做"。
- voice 在台词措辞和动作姿态里展现，不在解说里。voice 写"沉默克制"就少话多停顿，写"市井嬉笑"就口语带玩笑，让读者读两个字就能认出是你。
- 不要写元叙述（"这表明…"、"其实他在想…"），让动作和细节自己说话。

# 风格

不要写"作为 X 角色，我会..."这类元叙述。直接以第一人称行动。
不要写大段思考独白；让动作和言语本身体现你的人设。
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
