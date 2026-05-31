from __future__ import annotations
from ...providers import ToolSpec


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
            "【每 tick 必须至少调用一次】在关键节点插入一段散文式叙事（不改世界状态，纯给读者看的文学化段落）。"
            "用于：场景转换、情绪定格、内心独白、群像扫描、章节收束这类时刻。"
            "≥100 字，写得像小说，不要重复事件 description 已写的内容，"
            "要补充事件没说的氛围、节奏、未尽之意。"
            "如果本 tick 只调了工具没有 narrate，在 end_turn 之前必须补上。"
            "【文字纪律】大部分句子要朴素白描，只偶尔来一个有质感的；"
            "一段最多 1 个破折号；不要堆砌感官修饰；不要每段都收束在情绪总结句上。"
            "【格式禁令】不要用 markdown 标题（# ## 等）、不要用 markdown 加粗/斜体。"
            "直接输出纯散文正文。场景名如需标注，用自然语言融入叙事，不要用标题格式。"
        ),
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    ),
    ToolSpec(
        name="open_plot_thread",
        description=(
            "登记一条剧情钩子（伏笔/未解之谜/悬而未决的承诺）。"
            "**何时调用**：你在事件里埋下了暂时不能立刻兑现的悬念——某人发了誓但还没履行、某物失踪了但还没找到、某人立下复仇但还没动手、某句话留了余味但下文未写。"
            "登记后这条钩子会出现在后续每一轮的 prompt 里提醒你和未来的自己'这条线还没收'。"
            "不要为已经收尾的事件登记钩子；不要把日常动作当悬念登记（'他喝了杯水'不是钩子）。"
            "粒度：宁少勿多。一部 30 步的故事 3-6 条钩子就够了。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "title":   {"type": "string", "description": "短标题，如'林冲未报高俅之仇'、'宝玉未还黛玉绢'"},
                "summary": {"type": "string", "description": "一两句话说清这条线的内容、当前状态、什么算兑现"},
                "related_entity_ids": {"type": "array", "items": {"type": "string"}, "description": "相关实体 id（可选）"},
            },
            "required": ["title", "summary"],
        },
    ),
    ToolSpec(
        name="close_plot_thread",
        description=(
            "把一条已经在剧情里兑现的钩子标记为收尾。"
            "**何时调用**：你刚为这一轮添加的事件正好兑现了某条已登记的钩子（仇报了、誓履了、谜揭了）。"
            "在 resolution 里写一句话说明是怎么收的，这会写进系统日志让用户看到收尾里程碑。"
            "如果钩子 id 不存在或已是 closed 状态，本工具 no-op 安全返回，不抛错。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "thread_id":  {"type": "string", "description": "open_plot_thread 返回的 id"},
                "resolution": {"type": "string", "description": "一句话说明这条钩子是被哪个事件、以什么方式收的"},
            },
            "required": ["thread_id"],
        },
    ),
    ToolSpec(
        name="advance_outline_beat",
        description=(
            "宣布当前节拍已经在最近的事件里被满足，把'剧情进度'推到下一拍。"
            "调用条件：你判断当前节拍 beat 文本描述的核心事件已经在这一轮（或最近几轮）发生。"
            "副作用：current_index 加 1，旧 current_index 进 completed 列表，写一条系统日志记录这一推进。"
            "不要在还没真正满足节拍前调用——LLM 跳拍会破坏节奏。"
            "如果当前已经 all_done 或没有绑定大纲模板，该工具 no-op 安全返回，不会出错。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "note": {"type": "string", "description": "可选的推进说明：你为什么认为这一拍已经完成（一句话）"},
            },
        },
    ),
    ToolSpec(
        name="add_lore",
        description=(
            "向世界设定库写入一条新设定。当你在推演中发明了新的世界规则、地理、魔法体系、"
            "势力关系、文化习俗等**需要后续推演遵守**的设定时，必须调用此工具将其固化。"
            "不要用来记录一次性事件（那是 add_event 的事）；只记录具有持久约束力的世界观事实。"
            "例如：'北境冬令期间所有河流封冻，无法渡河'、'血誓一旦立下，违背者三日内必死'。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "设定条目标题（简短，如'北境封河规则'）"},
                "content": {"type": "string", "description": "设定的详细描述（50-300 字）"},
                "category": {
                    "type": "string",
                    "description": "分类：setting|magic|taboo|culture|geography|faction|other",
                },
            },
            "required": ["title", "content"],
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
1. 你看到的世界状态包括：世界全貌大纲（如有）、**剧情进度**（如有）、**角色人格速查**、实体清单、近期事件、**未收的剧情钩子**（如有）、**节奏与预算**（如有，告诉你剩多少拍、几条钩子、当前紧迫等级）、当前 tick；如果世界有地图，还会包含地图概览与各实体当前坐标。
2. **大纲优先**：如果"世界全貌大纲"段落存在，你的所有推演必须服从它。
   - 若大纲点名了经典原作（例如"按《水浒传》第X回还原"），你应尽量还原原作的人物、关键情节走向、转折节点。
   - 若大纲是架空设定，你在大纲框架内自由发挥，但不得违反大纲明示或暗示的设定。
3. **节拍约束**：如果出现"剧情进度"段落，里面的"当前应推进的节拍"是这一回合的目标。
   - 这一回合产生的事件应朝当前节拍推进，或在剧情已经满足时把它收束。
   - 不要越过当前节拍跳到后面的节拍（会破坏节奏）。
   - 如果当前节拍因为前置条件还没满足而无法推进，可以生成铺垫事件，但要明确仍在为当前节拍做准备，而不是绕开它。
   - **何时调用 `advance_outline_beat`**：当你为这一轮添加的事件已经把当前节拍 beat 文本描述的核心事件落实了（不是擦边、不是铺垫），就调一次 advance_outline_beat 把进度推到下一拍。一回合最多推 1-2 拍，让叙事有呼吸节奏。如果只是铺垫而不是兑现，**不要**调。
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
   - **但不要每个事件都三层面齐全**——有的事件只需要一个干净的动作，有的只需要一句对白。密度不均匀才像真的。
   - **同一回合不要让所有角色一个口吻**。voice 写"沉默克制"的人就少话多停顿，voice 写"市井嬉笑"的人就口语化、带玩笑。
   - 别写元叙述（"这预示着…"、"暗示着…"），让动作和细节自己说话。
   - **反 AI 文字指纹**（出现即扣分）：
     * 一段里超过 1 个破折号"——"
     * 每个动作都配感官修饰（"她推开门"不需要变成"被手掌稳稳推开的、带着木头潮气的门"）
     * "虽然……但至少……"、"尽管……却……"等让步句式
     * 把简单动作拆成微动作序列（"抬手→触到→转动→推开"）
     * 每句对白都精准推进剧情（真人会说废话）
     * 均匀的修辞密度——大部分句子应该朴素，只偶尔来一个有质感的
5b. **正面工艺原则（比禁令更重要——这是好文字的样子）**：
   - **人物有内反应**：事件 A 和事件 B 之间，角色必须有判断/期待/忍耐/误读。不能只是"发生了→又发生了"。例：霞碰粉笔→林夜以为有线索→"是干的"→林夜卡住吐槽——五个节奏，不是两个。
   - **感官有压强**：不描述感觉的属性（"极轻的呼吸声"），描述什么东西在制造这个感觉（"气流倒灌""庞然大物贴在巷底沉睡"）。读者感受到的是体量和距离，不是音量。
   - **动词带态度**："剜"不是"看"，"倒灌"不是"传来"。一个精准的动词胜过三个修饰语。
   - **对白要有节奏垫**：期待→交付→反应，不是问→答。允许角色的反应是吐槽、卡住、答非所问。
   - **信息走身体感知**：不要让叙述者解释（"她在看他后颈的疤"），让角色的身体告诉读者（"一股潮湿的目光汇聚在后颈，那道旧疤隐隐发开"）。
   - **一句话同时建两个人**："现在转头去问，他敢肯定霞什么也不会说"——这句话同时塑造了霞（沉默）和林夜（了解她）。追求这种效率。
6. 你必须通过调用工具来改变世界 —— 不要只用文字描述事件，要用 add_event、update_entity 等工具落到结构化数据里。
7. 每一步至少推进 1 个 tick（advance_time），并产生 1-3 个有意义的事件。事件之间尽量用 link_causality 建立因果，但**不要为了"看起来连贯"硬连不相关事件**——只在确实有因果时才连。
8. **剧情钩子（伏笔/悬念/未履承诺）**：好故事会埋线再收线。
   - 当你为某个角色或情节埋下一条暂时不会立刻兑现的悬念时（比如"林冲发誓必杀高俅"、"黛玉收下了一方旧绢却没还"），调用 `open_plot_thread` 显式登记，不要让它沉默地消失在事件流里。
   - 后续 prompt 会把所有 status='open' 的钩子列在"未收的剧情钩子"段落里，你必须把这些当作叙事的债务对待。
   - 不要在 30 步故事里堆 20 条钩子，宁少勿多。每条钩子都应该有兑现机会——如果某条钩子已经显然无法在剩余节奏里收尾，**不要假装它不存在**，要么调用 `close_plot_thread` 配合一个收束事件兑现它，要么承认它是开放结局并在叙事里点明。
   - 收尾时调 `close_plot_thread(thread_id, resolution="...")`——resolution 写"被哪个事件以什么方式收的"，会写进系统日志。
8. **主动引入新角色和实体**：
   - 故事不能只靠开局的几个角色撑完全程。当剧情需要时（新场景、新势力、新冲突源），**必须** `create_entity` 引入新角色，而不是让现有角色强行承担所有功能。
   - 判断标准：如果你发现自己要让角色 A 做一件与他 drives/背景完全无关的事只为推进剧情，那说明这里需要一个新角色来承担这个功能。
   - 新角色不一定是主角——配角、路人、对手、信使、目击者都能让世界有厚度。每 3-5 个 tick 至少考虑一次是否需要新面孔。
   - 引入新实体时填写 summary 和 attributes，不要留空。如果是 character，填一份起码包含 drives 与 voice 的 persona——这能让后续推演保持一致。
   - **禁止强行关联**：不要为了"让角色有交集"而编造不合逻辑的巧合。如果两个角色在设定上没有关联，就让他们各自在自己的线上发展，直到剧情自然交汇。平行叙事线比强行交叉更真实。
9. 当世界存在地图时：
   - 看实体的 pos/target/status 字段，了解谁在哪、谁在去哪。
   - 角色登场或瞬移用 set_position 安放坐标；角色"出发去某地"用 move_entity 设目标，移动会在之后 sim_tick 中自动推进。
   - 事件描述要呼应坐标与地形（例如"在沼泽边缘…"），不要无视地图。
10. **narrate 是叙事面板的内容来源，也是本轮推演的硬性产出**。
   - **每个 tick 必须至少调用一次 narrate**，输出一段描述本 tick 发生之事的叙事文字（至少 100 字）。即使本 tick 以工具调用（add_event、update_entity 等）为主，也必须产出叙述上下文，让读者能连贯阅读。
   - 如果本 tick 有多个事件，可以多次 narrate（场景切换、情绪定格、内心独白、章节收束），但至少一次是底线。
   - narrate 的内容不是事件的复述，而是小说正文：带画面、带节奏、带呼吸感。把它当作读者唯一会看到的文字来写。
   - 如果你发现自己只调了工具没有 narrate，在 end_turn 之前补上。
11. 完成本轮后调用 end_turn。
12. **结构反 AI 腔（这些是结构层面的禁令，比词汇层面更重要）**：
   - **禁止段段收束**：不要每段都以情绪总结句或哲理句收尾（"他终于明白了……""也许这就是……"）。段落可以断在动作中间、断在一个未完成的念头上、断在环境音里。
   - **禁止对白全是工具**：真人对话有废话、打断、答非所问、重复、口头禅。如果一段对白里每句话都精准推进剧情，那就是假的。至少 1/3 的对白应该是"无用"的——但它们建立人物质感。
   - **禁止均匀节奏**：不要每个事件都是"起因→经过→结果"三段式。有的事件可以只有一个画面定格，有的可以是一长串不间断的动作流，有的可以只是一句话。
   - **要求意外细节**：每 2-3 个事件里至少有一个不服务于剧情的感官细节或小动作——角色无意识地撕纸、远处有人在吵架、桌上的茶凉了没人喝。这些细节不推进任何事，但让场景有"在场感"。
   - **禁止转折永远在段末**：如果有意外或转折，不要总是放在段落最后一句。可以放在段中，然后角色的反应自然延续到下一段。
   - **禁止情绪同步**：不要让场景中所有角色对同一事件有相同情绪反应。有人还没反应过来，有人在想别的事，有人的反应是延迟的。
12b. **词汇级反 AI 腔（add_event description 和 narrate 都适用）**：
   - **禁止"不是X。是Y。"句式**：这是 LLM 最常见的伪文学句式。直接写 Y，不需要先否定。
   - **禁止"那一瞬间"**：用具体动作代替时间标记。
   - **禁止"隐隐"**：要么明确描述，要么不写。
   - **禁止"像有什么东西在……"**：虚指句式。如果要比喻，给出具体意象。
   - **禁止"也是……也是……"排比**：排比是演讲修辞，不是小说修辞。
   - **禁止"感觉整个X都被Y了"**：夸张的全身感受描写。用局部、具体的感受代替。
   - **禁止连续短句碎片化**：不要刻意把一句话拆成三四个句号隔开的碎片来制造"文学感"。
   - 总原则：如果一个句式你在 3 段内用了 2 次，第二次就是多余的。
13. **narrate 的段落骨架必须变化**（Author 无权改你的骨架结构，所以你必须在源头就做对）：
   - 本回合的 narrate 输出不要全是"叙述段→对白段→反应段"的重复单元。主动打破：
     * 有时从对白切入，叙述在后面补；
     * 有时整段只有动作流，没有心理旁白；
     * 有时一个长段不分行，模拟意识流或紧张节奏；
     * 有时用极短段（一两句）制造停顿或留白。
   - **自检**：写完 narrate 后回看——如果每段都是差不多长度、差不多结构，重写其中至少一段。
   - 这条规则的优先级高于"三个层面都要落到"——不是每段都需要动作+心理+环境全齐，有的段只需要一个层面就够了，密度服从节奏。

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


_LORE_CHAR_CAP = 4000  # 防 prompt 暴涨：lore 总字符上限
_LORE_CATEGORY_LABEL = {
    "setting": "背景", "magic": "规则", "taboo": "禁忌",
    "culture": "文化", "character": "人物", "other": "其他",
}


def build_world_lore_block(db, world) -> str:
    """B3: 把 WorldLore 渲染成 markdown 强约束块。

    pinned 的条目优先全部渲染（不受字符上限影响）；剩余按 priority 倒序填充直到
    达到 _LORE_CHAR_CAP。返回值已含标题；空则返空串。
    """
    from ...models import WorldLore
    rows = (
        db.query(WorldLore)
        .filter_by(world_id=world.id)
        .order_by(WorldLore.pinned.desc(), WorldLore.priority.desc(), WorldLore.created_at.asc())
        .all()
    )
    if not rows:
        return ""

    parts = ["# 世界设定（不可违背）"]
    used = 0
    for r in rows:
        title = (r.title or "").strip()
        content = (r.content or "").strip()
        if not title:
            continue  # 标题空 → 渲染没意义
        label = _LORE_CATEGORY_LABEL.get(r.category, r.category or "其他")
        block = f"\n## [{label}] {title}\n{content}" if content else f"\n## [{label}] {title}"
        if not r.pinned and used + len(block) > _LORE_CHAR_CAP:
            continue  # 非 pinned 超限就跳过
        parts.append(block)
        used += len(block)
    if len(parts) == 1:
        return ""
    return "\n".join(parts)
