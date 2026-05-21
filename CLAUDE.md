# CLAUDE.md

> 这份文件给进入项目的 Claude / agent 自动加载。**先读完再动代码。**
> 给人看的 README 在 `README.md`，词汇表在 `docs/GLOSSARY.md`，数据流图也在 README 里。

## 这是什么项目
Narrative Sandbox：面向小说创作的世界模拟沙盒。用户用 AI 工具调用做世界推演、抽事件、改写章节；也支持反向导入现有小说做"骨架抽取 → 事件审阅 → 继续推演"。

## 一句话技术栈
- 后端：Python 3.11 + FastAPI + SQLAlchemy + SQLite，单文件 `data/world.db`
- 前端：**只动 `frontend-next/`**（Vue 3 + TS + Vite + Pinia + Tailwind）。`frontend/` 是 Alpine.js 老前端，已冻结，不要碰
- LLM：OpenAI / Claude / DeepSeek / Ollama，配置写在 `data/llm_config.json`，UI 里改

---

## 启动 / 测试

```bash
# 后端
cd backend && uvicorn app.main:app --reload

# 前端
cd frontend-next && npm run dev

# 一键（Windows）
run.bat

# 测试（397 项 pytest，FakeProvider 替身，不打真 LLM）
run-tests.bat
# 或手动
cd backend && ../.venv/Scripts/python -m pytest

# 前端 typecheck + 构建
cd frontend-next && npm run build
```

环境约束：**Windows + bash shell（git bash）**。脚本路径用 `/` 不用 `\`，`/dev/null` 不是 `NUL`。Python 解释器是 `.venv/Scripts/python`（仓库根 `.venv/`）。

---

## 核心概念速览（详见 `docs/GLOSSARY.md`）

| 词 | 在代码里的真实意思 |
| --- | --- |
| **World** | 一个故事项目 + 它的全部状态（含多个分支） |
| **Branch** | 同一世界的平行时间线。每条分支独立持有 entity / event / causal_link / narrative_log |
| **tick** | 故事时间序号（整数，从 0 起）。事件归属某个 tick；同 tick 可有多个事件 |
| **current_tick** | 活跃分支的最新 tick；推演会从这里继续 |
| **active_branch_id** | 当前编辑的分支。世界视图里看到的所有数据都被这个 id 过滤 |
| **Snapshot** | 推演前自动建的回滚点，整 dump 到 JSON。和 git stash 类似 |
| **manuscript** | 用户上传的原稿。V1 从中抽骨架，V2 从中抽事件草稿 |
| **draft event** | V2 抽出的事件，存在 `world.manuscript_draft_events` JSON 里。**未落库**，需要用户审阅后 commit 才进 Event 表 |
| **V1** | `manuscript_ingest.py`，**同步**，在建世界时一次性抽骨架（cast/locations/outline）写库 |
| **V2** | `manuscript_events.py`，**异步 job**，建世界后逐章抽事件草稿到 JSON，等用户审阅 |

---

## 项目结构（重要）

```
backend/app/
  models/         数据模型（SQLAlchemy）。world.py 是核心
  providers/      LLM 适配器
  engine/         推演引擎（已按域归入 8 子目录，旧扁平路径保留为 stub 转发，不会断 import）
                  ├── agents/      orchestrator / agent_pipeline / author / editor / multi_agent / character_view / dialogue_rehearsal
                  ├── manuscript/  manuscript_ingest（V1）/ manuscript_events（V2）/ scene_continuity
                  ├── consistency/ consistency / patch
                  ├── core/        simulator / executor / tools / state / snapshots / jobs / metrics
                  ├── narrative/   novelize / pov / recap / persona_extract / draft_cleanup / thread_aging / transitions
                  ├── worldgen/    worldgen / blueprint / blueprint_render / lore_gaps / style_seeds
                  ├── embedding/   base / local_bge / siliconflow / zhipu
                  └── map/         map_sim
  api/            FastAPI 路由（已按业务域拆分，见下）

frontend-next/src/
  views/world/    各 tab 视图（Sim/Cast/Timeline/Chapters 等）
  views/          顶层视图（WorldsLibrary/Home/Settings）
  components/                          全局共享组件
  components/world-settings/           WorldSettingsView 拆出的 8 个 section
  services/api.ts 单文件 API 客户端
  stores/         Pinia stores

data/             world.db + llm_config.json（运行时数据，**不要 commit**）
docs/             设计文档 + 词汇表
```

### `backend/app/api/` 路由分布
2025 年初做了拆分（2026-05 完成）：原 ~2680 行 routes.py 拆成 19 个子模块，主文件压到 46 行只做 router 聚合。**加新端点时**：

1. 找最贴近业务域的 `*_api.py` 加进去
2. 都不贴近就新建 `xxx_api.py`，在 `routes.py` 加两行 `import` + `include_router`

子模块速查：

| 文件 | 管什么 |
| --- | --- |
| `worlds_api.py` | 世界 CRUD |
| `world_settings_api.py` | PATCH 世界（含 style_profile / lore） |
| `branches_api.py` | 分支切换 / 重命名 / 删除 |
| `entities_api.py` | 角色 / 地点 / 派系等实体 |
| `events_api.py` | 事件 CRUD |
| `step_api.py` | 推演 step / auto / reconcile（含 job） |
| `history_api.py` | 快照 / 回滚 |
| `timeline_api.py` | 时间轴查询 |
| `chapters_api.py` | 章节标记 |
| `manuscript_api.py` | 手稿导入、V2 事件抽取 |
| `manuscript_render_api.py` | 章节预览 / 渲染 |
| `novelize_api.py` | 单章成稿 |
| `export_novel_api.py` | 整本导出 markdown |
| `consistency_api.py` | 一致性扫描 / issue / patch / scene_continuity |
| `agent_pipeline_api.py` | Agent 流水线配置 + 编排推演 + trace |
| `templates_api.py` | 世界模板 |
| `explore_api.py` | 探索建议 |
| `llm_api.py` | LLM 配置 |
| `_common.py` | 共享 helper（`_new_id` / `_id_prefix_for`） |

另有几个旧命名独立路由，未参与拆分：`map_routes.py` / `dialogue_routes.py` / `lore_routes.py` / `stats_routes.py` / `storyboard_aux_routes.py`。新功能不要往这里加。

### `frontend-next/src/components/world-settings/`
WorldSettingsView 在 2025 年拆成了 8 个 section（每个 50–420 行）。**加新世界设置入口**：在这个目录下新建 `XxxSection.vue`，到 `views/world/WorldSettingsView.vue` 编排即可。父视图只做 load + 编排，所有交互逻辑在 section 里。

---

## 主要数据流（速记）

详细图见 `README.md` 顶部的 Mermaid。这里只列入口和写哪张表：

| 流程 | 前端入口 | API | 引擎 | 写表 |
| --- | --- | --- | --- | --- |
| 推演（默认） | `SimView` 切换器 ON | `agent_pipeline_api.py` `/step_orchestrated` | `engine/agents/orchestrator.py` | Event / Entity / CausalLink / NarrativeLog / AgentTrace |
| 推演（单 agent） | `SimView` 切换器 OFF | `step_api.py` | `engine/core/simulator.py` + `executor.py` + 12 个工具 | Event / Entity / CausalLink / NarrativeLog |
| 推演（POV） | `SimView` "多 agent" | `step_api.py` `/step_multi_agent` | `engine/agents/multi_agent.py` | 同上 |
| V1 建世界 | `WorldsLibraryView` "📖 从手稿建" | `worlds_api.py` `/from_manuscript` | `engine/manuscript/manuscript_ingest.py`（同步） | World / Branch / Entity（cast/locations） |
| V2 抽事件 | `ManuscriptExtractSection` | `manuscript_api.py` `/extract_events_async` | `engine/manuscript/manuscript_events.py`（job） | `world.manuscript_draft_events`（JSON，**未落库**） |
| V2 落库 | 同上，审阅 → commit | `manuscript_api.py` `/commit_events` | 直接写库 | Event + CausalLink |
| 一致性扫描 | `ReviewView` | `consistency_api.py` | `engine/consistency/consistency.py` + `consistency/patch.py` + `manuscript/scene_continuity.py` | ConsistencyIssue / ScanRun / IssuePatch |
| 章节渲染 | `ChaptersView` | `manuscript_render_api.py` / `novelize_api.py` | `engine/agents/author.py` / `agents/editor.py` / `narrative/novelize.py` | NarrativeLog（role=author_final）/ ChapterMarker |
| 整本导出 | `ChaptersView` "导出" | `export_novel_api.py` | 拼接 NarrativeLog + ChapterMarker | 输出文件，不写库 |

**记住**：推演 step 写出的 Event 和 V2 落库的 Event 共用同一张表。章节渲染和一致性扫描读的也是这张表。所以 V2 commit 后用户能继续推演、能直接渲染章节。

---

## 开发约定 / 不要做的事

### 不要碰
- `frontend/`（Alpine.js 老前端，2025 已冻结，见 `frontend/FROZEN.md`）
- 直接打真 LLM 跑测试 → 用 FakeProvider，看 `tests/conftest.py`
- 在 `data/` 下手改 `world.db` → 用 SQLAlchemy 迁移或 API 端点
- 在 `routes.py` 写新端点 → 见上文路由分布

### 标准做法
- **加新 LLM provider**：在 `backend/app/providers/` 加文件，注册到 `PROVIDER_CLASSES`
- **加新工具（AI 调用的）**：在 `engine/core/executor.py` 实现函数 + 在 `engine/core/tools.py`（或对应 spec 文件）登记 schema
- **加 schema 字段**：改 `models/world.py`，启动时 SQLAlchemy 会自动建表，但**老库不会自动加列**——需要手动 `ALTER TABLE` 或删 `data/world.db` 重建
- **改前端 API 调用**：所有 fetch 都走 `services/api.ts`，不要直接 `fetch()`

### Token / 性能
- LLM 状态会被截断到最近 30 事件 + 80 实体（`build_state_snapshot` 默认）
- 一次推演最多 8 hops（防 LLM 死循环）；编排流水线额外有 budget（max_llm_calls / max_wall_seconds）
- V1 ingest 是同步的，>180k 字（>3 批）可能踩 endpoint 超时；V2 是 job，没这个问题
- V2 因果抽取会让总耗时翻倍

### LLM provider 注意
- DeepSeek 走 OpenAI 兼容协议，原生 tool calling
- Ollama 用 prompt 模拟 tool calling，不如原生稳定。本地测试可以，生产不推荐
- 测试时永远用 `FakeProvider`，不打真 API

---

## 当前重构状态（2026-05）

最近完成（当前会话）：

**工程债全部清零**：
- engine 31 文件 → 7 子目录 + stub 兼容
- manuscript_chunks JSON → 独立表
- Entity.attributes 拆出 aliases 列
- metrics 可观测性（LlmCallMetric 表 + MetricsProvider + GET /metrics）
- 前端测试 27 条（vitest + @vue/test-utils）
- 导出 docx/epub

**功能深化**：
- V1 异步 job（`POST /worlds/from_manuscript_async`）
- 智能文本分割（3 级章节检测 + 字数回退）
- 编排流水线默认启用（SimView Director→Author→Critics，预置人设+文风 critic）
- V2 审阅原文对照（source_context 字段）
- 推演后自动一致性检查

**体验**：
- 仪表盘 DashboardView（统计卡片 + metrics + 实体分布 + 事件日志 + LLM 日志）
- 三步引导流程（导入→抽取→推演）
- 大文件防卡死（>512KB 不塞 DOM）
- 侧边栏 11 标签分 3 组
- SettingsDrawer LLM + metrics 面板

待真实小说回归测试：
- T2/T3 全系列（见 README）

下一批待办：端到端测试、前端测试扩展、阅读模式增强、i18n

---

## 风格 / 沟通

- 我（用户）写代码十年以上，熟悉 Python / TS / Vue。**不要解释基础概念**，直接给修改点
- 倾向**短而准**的回复，不要总结刚做了什么（diff 自己看得见）
- 改完先跑 `pytest` + `vue-tsc`，再向我汇报
- 中文交流；代码注释能不写就不写，写也用最少的字
- 重构 / 拆分这种大动作，先确认范围再动；不要"顺手"改无关代码
