# 词汇表 / Glossary

> 项目里反复出现、但**字面意思和实际语义对不齐**的概念。新 agent 进项目先读这一页，能省一小时摸索。
> 看不见的隐式约定 > 显式文档；这页只列那些会让人误判的词。

---

## 顶层数据模型

### World（世界）
**不是**"虚构世界"。是**一个故事项目 + 它当前的全部状态**：分支集合、活跃分支 id、当前 tick、规则、大纲、绑定的 style profile、地图配置、手稿原文……
- 表：`worlds`
- 一个用户可有 N 个 World，互相独立
- 删除 World 会级联删它所有的 Branch / Entity / Event / Snapshot

### Branch（分支）
**不是 git 分支**。是同一个 World 的一条**平行时间线**。每条分支独立持有一份 entity / event / causal_link / narrative_log。
- 表：`branches`
- 主分支 `parent_branch_id=NULL`（一般叫 `main`）
- 调用工具 `branch_world` → 复制当前分支到当前 tick 之前的所有数据，从 `diverged_at_tick` 开始独立演进
- **关键**：所有读取数据的 API 都按 `world.active_branch_id` 过滤；切换分支只是改这个 id

### Entity（实体）
角色 / 地点 / 派系 / 物品 / 概念。`type` 字段区分：`character` / `location` / `faction` / `object` / `concept`。
- 表：`entities`
- 绑定 `branch_id`（所以同一角色在不同分支是不同行）
- `attributes` JSON：静态属性（年龄、aliases、外貌等）
- `state` JSON：动态状态（伤势、位置等，会随推演变）
- `memories` JSON：仅 `character` 用，存"该角色记得的事件"列表，上限 200 条
- `persona` JSON：仅 `character` 用，存动机 / 说话风格 / 知识盲区

### Event（事件）
故事里发生的一件事。
- 表：`events`
- 绑定 `branch_id` 和 `tick`
- `participant_ids`：参与该事件的实体 id 列表
- `location_id`：事件发生地点的实体 id
- `deleted=1` 是软删除

### CausalLink（因果链）
两个 Event 之间的因果关系（cause → effect）。
- 表：`causal_links`
- 由推演工具 `link_causality` 创建，或 V2 因果抽取写入

### NarrativeLog（叙述日志）
LLM 生成的散文。**多 agent 流程会产生多版本同 tick 的记录**。`role` 字段区分：
- `director_draft`：导演 agent 的粗稿
- `author_final`：作者 agent 改写后的定稿（**前端展示用这版**）
- `narrator`：旧数据 / 单 agent 流程的版本
- 同 tick 内 `author_final` > 其它

---

## 时间 / 进度概念

### tick（推演时间）
**不是物理时间戳**。是**故事时序的整数序号**，从 0 起。
- 同一 tick 可以有多个 event
- `world.current_tick` = 活跃分支的最大 event tick + 1，表示"下一步推演会写这个 tick"
- 工具 `advance_time` 会把 `current_tick` 往前推

### max_tick（推演上限）
0 表示无上限。设了之后，`current_tick >= max_tick` 时 step 端点会拒绝。用来给故事划长度边界。

### Snapshot（快照）
**不是定时备份，也不是 git stash**。是**每次推演前自动建的全量回滚点**。
- 表：`snapshots`
- `payload` JSON：dump 该分支当前所有 entity / event / causal_link / narrative_log
- 用户可以手动建命名快照，也可以回滚到任意快照
- 回滚 = 删掉该分支当前数据，从 payload 还原 + 把 `current_tick` 回到 snapshot 时的值

---

## 手稿（manuscript）双路径 ★

项目最容易踩的混淆点。**V1 和 V2 是两套并存的流程**，做的事不一样。

### Manuscript（手稿）
用户上传的现有小说原文。存在 `world.manuscript_chunks` JSON 里：`[{"title": "第一章", "text": "..."}]`。

### V1 = "建世界时一次性抽骨架"
- 文件：`backend/app/engine/manuscript/manuscript_ingest.py`
- 触发：前端 `WorldsLibraryView` "📖 从手稿建" → `worlds_api.py` `/worlds/from_manuscript`
- **同步执行**（endpoint 直接跑 LLM 等返回）
- LLM 输出：cast / locations / factions / outline / setting
- **直接写库**：建 World + 主 Branch + Entity（cast/locations/factions），写 World.outline / World.description
- 长篇会分批（30 章/批 或 60k 字/批）多次调 LLM
- 风险：>180k 字（>3 批）可能 endpoint 超时

### V2 = "建世界后逐章抽事件草稿"
- 文件：`backend/app/engine/manuscript/manuscript_events.py`
- 触发：`WorldSettingsView` → `ManuscriptExtractSection` "抽取事件" → `manuscript_api.py` `/extract_events_async`
- **异步 job**（前端 1.5s 轮询 `/jobs/{id}`）
- LLM 输出：事件列表 + 因果链
- **不直接落库**！写入 `world.manuscript_draft_events` JSON，等用户审阅
- 支持指定 `chapter_indices`（只抽某些章），其它章节既有 draft 保留
- Job 中途崩溃可恢复（每批跑完立刻 commit JSON）
- 抽完事件后还会跑一遍因果 pass，写每个 event 的 `causes`（上游 tick 列表）

### Draft Event（草稿事件）
V2 抽出但**未落库**的事件。结构和 Event 表类似，但只在 `world.manuscript_draft_events` JSON 里活着。
- 字段：`tick` / `chapter_index` / `title` / `description` / `participant_ids` / `location_id` / `causes`
- 用户在 `ManuscriptExtractSection` 的审阅 dialog 里勾选哪些接受、改 participants / location
- 点 "落库" → `/commit_events` → 真写入 Event 表 + CausalLink 表

### V1 与 V2 的关系
- 同一个世界**先 V1 后 V2** 是标准流程（V1 建实体，V2 抽事件）
- V2 也可以独立用：先用模板建世界、手动加角色，再粘 manuscript 走 V2
- 但前端目前没有"为已有世界添加 manuscript"的入口，所以实操上 V2 总是跟在 V1 后面

---

## AI 推演相关

### Step / Auto / Reconcile
- `run_step`：调一次 LLM，跑一轮工具循环（最多 8 hops），写出若干 event/entity 变化 + 一段叙述
- `run_auto`：连续跑 N 次 step，期间可取消
- `run_reconcile`：用户编辑事件后重新做因果调和

### Tool Call（AI 工具调用）
LLM 不直接写 SQL，而是输出 ToolCall（name + arguments），由 `engine/core/executor.py` 分发执行。12 个工具：
`create_entity` / `update_entity` / `add_event` / `update_event` / `delete_event` / `link_causality` / `advance_time` / `branch_world` / `narrate` / `set_position` / `move_entity` / `end_turn`

### State Snapshot（状态快照）
**不要和 Snapshot 表搞混**。这是**每次推演前现算的、给 LLM 看的世界状态 JSON**，不写库。
- 函数：`engine/core/state.py::build_state_snapshot()`
- 默认截断到最近 30 事件 + 80 实体（控 token）
- `state_as_prompt()` 把它转成 markdown 喂 LLM
- 实体含 `alive` 字段（0/1），snapshot 返回**全员**（含已死），让前端能区分；prompt 渲染时（实体块、persona quickref、地图 entities_on_map）显式过滤 `alive=0`，LLM 看到的还是只活的

### Multi-Agent（多 agent 流程）
SimView 一个入口，三种模式可切：

**A. 编排流水线（默认，2026-05-21 推至前台）**
1. **Director**：跑工具调用 + `director_draft`
2. **Author**：按 style profile 改写成 `author_final`
3. **Critics**（N 个）：可配置多个审稿 agent，每个有 focus（语感/人设/节奏…）和严格度（lenient/normal/strict）
   - 模式：`parallel`（一轮全跑）/ `serial`（第一个 fail 即停）
   - 任一 critic `fail` → Author 按反馈重写 → 进入下一轮
   - 到 `max_critic_retries` 仍未 pass → `forced_accept` 兜底
   - 预算：`max_llm_calls` + `max_wall_seconds`，触顶提前结束

每次 LLM 调用写一条 **AgentTrace**（input/output summary + 完整 prompt/response），SimView 实时拉取展示，可手动停止。

**B. 单 agent（SimView 切换器关闭）**
director → author 两阶段，没有 critic 重写。走 `engine/core/simulator.py` `step` / `auto`。

**C. 多 agent (POV) — `step_multi_agent`**
每个 focal character 先用自己 POV 给出 intent，再由 director pass 合并成世界事件。和编排流水线的 critic 路径不是一回事。引擎在 `engine/agents/multi_agent.py`。

**配置入口：** 世界设置 → "Agent 流水线"（`AgentPipelineSection`），支持 "保存到本世界 / 设为全局默认 / 重置为继承全局"。配置 JSON 存 `world.agent_pipeline`，全局默认存 `app_settings`。

**API：** `agent_pipeline_api.py`（GET/PUT 配置 + `/step_orchestrated` 启 job + `/jobs/{id}/agent_traces` 增量拉 trace）；引擎在 `engine/agents/orchestrator.py::run_orchestrated_step`。

> 旧 `AgentRunView`（独立的 trace viewer 视图）路由 `/agent-run` 仍保留作直链调试用，侧边栏入口已移除（commit 9571b67）。

### Persona（人格）
仅 `character` 实体的 `persona` JSON：`{drives, voice, knowledge_blindspots}`。给 LLM 当角色卡用。
有"persona 萃取"功能，从该角色已发生事件里反推 persona。

### StyleProfile（风格档案）
绑定到 World 的语感模板，改写章节时套用。分内置（`kind=builtin`）和自建（`kind=custom`）。
- 表：`style_profiles`
- 字段：`spec_text`（自然语言风格描述）+ `sample_paragraphs`（范文段落）

---

## 一致性扫描

### ConsistencyIssue（一致性问题）
LLM 扫描发现的潜在矛盾（角色行为前后不一、世界规则违反等）。
- 表：`consistency_issues`
- `status`：`open` / `ignored` / `resolved`
- `category`：人物 / 设定 / 时间线 / 因果 等
- 推演时 top-5 open issue 会被塞进 director system prompt（"自纠环"），让 LLM 主动避免

### ScanRun（扫描运行记录）
一次扫描的元数据：何时跑、扫了哪个分支、产了多少 issue。

### PlotThread（剧情线）
通过工具 `open_plot_thread` / `close_plot_thread` 维护的"未收钩子"列表。LLM 看到 open 的 thread 会倾向收尾。

---

## 章节 / 渲染

### ChapterMarker（章节标记）
把 tick 范围标为一章。`start_tick` / `end_tick`。
- 用户可在 `ChaptersView` 手动切，也支持自动（按 tick / 按事件数 / 单章）
- 渲染整本时按 ChapterMarker 顺序拼

### Novelize（小说化）
单章渲染：把该章节 tick 范围内的 event + narrative_log 喂给 LLM，套 style profile，输出最终章节文本。

### Outline / OutlineProgress
- `World.outline`：用户写的剧情大纲（自由文本）
- `World.outline_progress` JSON：`{beats: [...], current_index, completed: [...]}`，由工具 `advance_outline_beat` 推进。让 LLM 知道"我们到剧情哪个节拍了"

---

## 容易混淆的对子

| 容易搞混 | 区别 |
| --- | --- |
| Snapshot 表 vs build_state_snapshot() | 前者是回滚点（写库），后者是给 LLM 看的状态 JSON（不写库） |
| V1 vs V2 | V1 同步抽骨架写库；V2 异步抽事件草稿到 JSON |
| Event vs Draft Event | 前者真在 events 表里；后者在 `world.manuscript_draft_events` JSON 里，落库后才进 events 表 |
| `tick` vs `created_at` | tick 是故事时间序号；created_at 是真实时间戳 |
| `branch_id` vs `active_branch_id` | 前者是 entity/event 上的外键；后者是 World 表上"当前显示哪条"的字段 |
| `narrator` vs `author_final` 角色 | narrator 是旧数据/单 agent；author_final 是多 agent 流程定稿 |
| 两阶段 vs 编排流水线 | 两阶段（director→author，可选 editor）走 `engine/core/simulator.py`；编排流水线（director→author→critics 重试）走 `engine/agents/orchestrator.py`。SimView 切换器决定走哪条；旧 `AgentRunView` 路由 `/agent-run` 仅作直链调试，侧边栏入口已移除 |
| Outline vs OutlineProgress | Outline 是用户写的文本；OutlineProgress 是结构化进度追踪 |
| `manuscript_chunks` vs `manuscript_draft_events` | 前者是 V1 切的章节；后者是 V2 抽的事件草稿 |
