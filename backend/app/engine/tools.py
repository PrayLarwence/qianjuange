from __future__ import annotations
from ..providers import ToolSpec


TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="create_entity",
        description="创建一个新实体（角色/地点/物品/组织/势力等）。地点也是实体，type='location'。",
        parameters={
            "type": "object",
            "properties": {
                "type": {"type": "string", "description": "character | location | item | organization | faction | concept"},
                "name": {"type": "string"},
                "summary": {"type": "string", "description": "一句话描述"},
                "attributes": {"type": "object", "description": "自由结构属性，例如性格、能力、背景"},
                "location_id": {"type": "string", "description": "实体当前所在地点的 entity id（可选）"},
            },
            "required": ["type", "name"],
        },
    ),
    ToolSpec(
        name="update_entity",
        description="修改已存在实体的属性或状态。changes 会浅合并到 attributes/state。",
        parameters={
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "attributes": {"type": "object"},
                "state": {"type": "object", "description": "动态状态，如 mood, hp, alive, location_id"},
                "summary": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["id"],
        },
    ),
    ToolSpec(
        name="add_event",
        description="在当前时间或指定 tick 添加一个事件。事件是世界推进的最小单位。",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "事件的简短标签（10-20 字）。"},
                "description": {
                    "type": "string",
                    "description": (
                        "**这是给读者看的小说级文字，不是日志条目。** 至少 80 字，理想 120-200 字。"
                        "必须包含：(1) 谁做了什么具体动作；(2) 至少一项神态/语气/心理细节，体现当事人的 voice 与 drives；"
                        "(3) 现场的环境/物件/感官细节作为锚点。"
                        "反例：'林冲答应了高俅的安排。'（流水账，没人格）"
                        "正例：'林冲沉默良久，目光在那柄油纸伞的伞骨上停留了一拍才点头。"
                        "他指节在膝头微微一紧，又松开——这答应里没有情愿，只有家小尚在汴京的人才懂的克制。'"
                        "（动作+神态+心理+voice 同时落到位）。"
                    ),
                },
                "tick": {"type": "integer", "description": "省略则用世界当前 tick"},
                "participants": {"type": "array", "items": {"type": "string"}, "description": "参与实体 id 列表"},
                "location_id": {"type": "string"},
                "consequences": {"type": "array", "items": {"type": "string"}, "description": "事件直接后果的简述列表"},
            },
            "required": ["title", "description"],
        },
    ),
    ToolSpec(
        name="update_event",
        description="修改已存在事件的标题、描述、tick、参与者或地点。在调和场景下用来按新因果改写下游事件。",
        parameters={
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "tick": {"type": "integer"},
                "participants": {"type": "array", "items": {"type": "string"}},
                "location_id": {"type": "string"},
                "consequences": {"type": "array", "items": {"type": "string"}},
                "reason": {"type": "string", "description": "为何要改写（用于审计）"},
            },
            "required": ["id"],
        },
    ),
    ToolSpec(
        name="delete_event",
        description="软删除一个事件（标记 deleted=True，不真删数据）。其因果链同时失效。用于'这事不该发生'。",
        parameters={
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["id"],
        },
    ),
    ToolSpec(
        name="link_causality",
        description="在两个事件间建立因果链。cause 引发 effect。",
        parameters={
            "type": "object",
            "properties": {
                "cause_event_id": {"type": "string"},
                "effect_event_id": {"type": "string"},
                "description": {"type": "string"},
                "weight": {"type": "number", "description": "0-1 因果强度"},
            },
            "required": ["cause_event_id", "effect_event_id"],
        },
    ),
    ToolSpec(
        name="advance_time",
        description="推进世界时钟若干 tick（一个 tick 的现实跨度由世界设定决定）。",
        parameters={
            "type": "object",
            "properties": {"ticks": {"type": "integer", "minimum": 1}},
            "required": ["ticks"],
        },
    ),
    ToolSpec(
        name="branch_world",
        description="从当前状态分叉一条新的世界线，用于 what-if 推演。返回新 branch_id。",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["name"],
        },
    ),
    ToolSpec(
        name="narrate",
        description=(
            "在关键节点插入一段散文式叙事（不改世界状态，纯给读者看的文学化段落）。"
            "用于：场景转换、情绪定格、内心独白、群像扫描、章节收束这类时刻。"
            "建议每 2-3 个事件之后调用一次，让叙事面板有持续可读内容。"
            "≥100 字，写得像小说，不要重复事件 description 已写的内容，"
            "要补充事件没说的氛围、节奏、未尽之意。"
        ),
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    ),
    ToolSpec(
        name="end_turn",
        description="结束本轮推演。当你认为本 step 已经完成，调用此工具。",
        parameters={"type": "object", "properties": {}},
    ),
    ToolSpec(
        name="set_position",
        description="把实体瞬间放到地图上的指定坐标。用于初次登场、传送、章节切换等不需要逐步移动的场景。仅在世界已生成地图时可用。",
        parameters={
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "实体 id"},
                "x": {"type": "integer"},
                "y": {"type": "integer"},
            },
            "required": ["id", "x", "y"],
        },
    ),
    ToolSpec(
        name="move_entity",
        description="给实体设定一个移动目标。实体会在后续 sim_tick 中按 speed 自动走过去（受地形影响）。仅在地图存在且实体已有坐标时可用。要让实体停下，省略 x/y 或设为 null。",
        parameters={
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "x": {"type": "integer", "description": "目标 X，省略则停下"},
                "y": {"type": "integer", "description": "目标 Y，省略则停下"},
                "speed": {"type": "number", "description": "每 tick 像素数，默认沿用现有 move_speed"},
            },
            "required": ["id"],
        },
    ),
]


SYSTEM_PROMPT = """你是一个叙事沙盒的世界推演引擎。你的职责是基于当前世界状态，推演接下来发生的事情。

规则：
1. 你看到的世界状态包括：世界全貌大纲（如有）、**剧情进度**（如有）、**角色人格速查**、实体清单、近期事件、未解决的因果钩子、当前 tick；如果世界有地图，还会包含地图概览与各实体当前坐标。
2. **大纲优先**：如果"世界全貌大纲"段落存在，你的所有推演必须服从它。
   - 若大纲点名了经典原作（例如"按《水浒传》第X回还原"），你应尽量还原原作的人物、关键情节走向、转折节点。
   - 若大纲是架空设定，你在大纲框架内自由发挥，但不得违反大纲明示或暗示的设定。
3. **节拍约束**：如果出现"剧情进度"段落，里面的"当前应推进的节拍"是这一回合的目标。
   - 这一回合产生的事件应朝当前节拍推进，或在剧情已经满足时把它收束。
   - 不要越过当前节拍跳到后面的节拍（会破坏节奏）。
   - 如果当前节拍因为前置条件还没满足而无法推进，可以生成铺垫事件，但要明确仍在为当前节拍做准备，而不是绕开它。
4. **persona 是硬约束，不是装饰**：
   - "角色人格速查"列出的 drives / voice / blindspots 是每个角色这一回合行为的最高约束。
   - 当你为某个角色 add_event 时，必须能回答："这个事件里他这么做，是出于他的哪个 drive？" 答不出来就不要让他这么做。
   - 角色说话用他的 voice 风格写，不要让所有角色嘴里的话都是同一种声音。
   - 角色不应表现出对自己 blindspots 的了解，即便上帝视角下其它事件已发生。
   - 角色 JSON 里的 `memories` 字段是该角色**自己记得的过往事件**（已从近期事件清单里滚出的旧事），是他做决定的私人参照。让人物在这一回合的言行和这些记忆产生共鸣——比如旧仇未消的人见到对头时眼神变冷、被恩人救过的人在抉择时迟疑。不要把记忆当装饰，要让它驱动当下行为。
5. **事件文字规范（这是读者直接看的东西，决定故事质感）**：
   - 每个 add_event 的 description **不是事件日志**，而是一段小说级文字。**至少 80 字**，理想 120-200 字。
   - 必须落到三个层面：
     * **动作**：当事人具体做了什么（不是"他答应了"，而是"他停顿一拍才点头"）。
     * **神态/心理**：表情、目光、肢体细节、闪过的念头——voice 在这里展现，不只在台词里。
     * **环境锚点**：现场至少一个感官细节（一柄伞、一阵风、远处的钟声、桌上未喝完的茶），让画面立得起来。
   - **同一回合不要让所有角色一个口吻**。voice 写"沉默克制"的人就少话多停顿，voice 写"市井嬉笑"的人就口语化、带玩笑。
   - 别写元叙述（"这预示着…"、"暗示着…"），让动作和细节自己说话。
6. 你必须通过调用工具来改变世界 —— 不要只用文字描述事件，要用 add_event、update_entity 等工具落到结构化数据里。
7. 每一步至少推进 1 个 tick（advance_time），并产生 1-3 个有意义的事件。事件之间尽量用 link_causality 建立因果，但**不要为了"看起来连贯"硬连不相关事件**——只在确实有因果时才连。
8. 引入新实体时填写 summary 和 attributes，不要留空。如果是 character，填一份起码包含 drives 与 voice 的 persona——这能让后续推演保持一致。
9. 当世界存在地图时：
   - 看实体的 pos/target/status 字段，了解谁在哪、谁在去哪。
   - 角色登场或瞬移用 set_position 安放坐标；角色"出发去某地"用 move_entity 设目标，移动会在之后 sim_tick 中自动推进。
   - 事件描述要呼应坐标与地形（例如"在沼泽边缘…"），不要无视地图。
10. **narrate 是叙事面板的内容来源**。每一步推演里，关键节点（场景切换、情绪定格、内心独白、章节收束）应该调用 narrate 写一段散文，建议每 2-3 个事件之后插入一次。不要把它当可选点缀——读者主要在叙事面板里读你的故事。
11. 完成本轮后调用 end_turn。

不要输出大段思考独白；用工具调用说话。
"""


def render_world_rules(rules: dict | None) -> str:
    if not rules:
        return ""
    parts: list[str] = []
    core = rules.get("core_rules") or rules.get("constraints") or []
    if isinstance(core, list) and core:
        parts.append("## 这个世界的硬性设定（必须遵守，不得违反）")
        for r in core:
            if isinstance(r, str) and r.strip():
                parts.append(f"- {r.strip()}")
    forbidden = rules.get("forbidden") or []
    if isinstance(forbidden, list) and forbidden:
        parts.append("\n## 严格禁止")
        for r in forbidden:
            if isinstance(r, str) and r.strip():
                parts.append(f"- {r.strip()}")
    tone = rules.get("tone") or ""
    if isinstance(tone, str) and tone.strip():
        parts.append(f"\n## 叙事基调\n{tone.strip()}")
    language = rules.get("language") or ""
    if isinstance(language, str) and language.strip():
        parts.append(f"\n## 语言风格\n{language.strip()}")
    notes = rules.get("notes") or ""
    if isinstance(notes, str) and notes.strip():
        parts.append(f"\n## 其他备注\n{notes.strip()}")
    if not parts:
        return ""
    return "\n".join(parts)
