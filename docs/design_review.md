# 设计评审

> 范围：架构、数据模型、模块边界、技术选型、可维护性。  
> 视角：「再来一个工程师接手要花多久能 Productive」。

---

## 一、整体架构

```
┌─────────────────┐         ┌─────────────────┐
│ frontend/       │         │ frontend-next/  │
│ Alpine.js 老版   │         │ Vue 3 + Vite    │
│ 12k 行          │         │ 6.8k 行          │
└────────┬────────┘         └────────┬────────┘
         │                           │
         └────────────┬──────────────┘
                      │ REST JSON
                      ▼
         ┌──────────────────────────────┐
         │ FastAPI · routes.py 4089 行   │
         │ 95 个 @router 端点            │
         └──────────────┬───────────────┘
                        │
        ┌───────────────┼────────────────┐
        ▼               ▼                ▼
   ┌─────────┐   ┌─────────────┐   ┌──────────┐
   │ engine/ │   │ providers/   │   │ models/  │
   │ 30 模块 │   │ 4 LLM 抽象   │   │ 18 表     │
   └─────────┘   └─────────────┘   └──────────┘
                        │                │
                        ▼                ▼
                  ┌─────────┐      ┌──────────┐
                  │ LLM API │      │ SQLite   │
                  └─────────┘      └──────────┘
```

**判断**：分层清晰，方向是对的。问题集中在「`routes.py` 单文件爆炸」+「双前端」。

---

## 二、数据模型评审

### 18 张表，分四组：

#### A. 核心叙事（无可挑剔）
- `World` / `Branch` / `Entity` / `Event` / `CausalLink`
- 决策正确：把"什么发生了"和"为什么发生"分两张表，因果是一等公民
- `Branch` 自引用 + `Entity / Event.branch_id` 让多分支天然成立
- `EntitySnapshot` 按 tick 存历史属性，回看角色弧线时不用回溯事件

#### B. 状态快照
- `Snapshot` / `NarrativeLog` / `ChapterMarker` / `ChapterSummary`
- `Snapshot.payload` 用 JSON 存整个世界状态 — 简单粗暴但有效
- `NarrativeLog` 与 `Event.description` 角色重叠，**值得追问**：散文叙事到底放哪？

#### C. 元数据 / 配置
- `WorldTemplate` / `WorldLore` / `StyleProfile` / `EmbeddingChunk`
- `WorldLore` vs `Entity.summary` 边界模糊，世界设定到底以哪个为准？
- `EmbeddingChunk` 给 RAG 准备但目前用得少，**潜在死代码**

#### D. 一致性 / 计划
- `PlotThread` / `ConsistencyIssue` / `ScanRun` / `IssuePatch`
- 模型设计完整，但 UI 层暴露不够，**典型「表建好了功能没接通」**

### 可疑点
1. **`Event.consequences` JSON vs `CausalLink` 表**：两套描述因果，前者 inline、后者 normalized。AI 工具调用会两边都写，**容易不同步**
2. **`Entity.attributes` JSON 什么都塞**：aliases、persona 片段、自定义属性、临时状态。**T2-B 又往里加了 aliases**。这字段会越来越乱，**应该考虑把 aliases / persona 拆成独立列**（aliases 已在 R 系列拆出）
3. ~~**`World.manuscript_chunks` / `manuscript_draft_events` 都用 JSON 列**~~：~~已迁移~~ 现已独立成 `manuscript_chunks` 表（R 系列）。但 **新发现**：`text` 列声明 TEXT 没做编码校验，某次失败的 epub 导入把二进制流（含 NUL 字节）直接塞了进去，单库膨胀 100MB。**需要在 ingest 路径加 utf-8 解码兜底 + 入库前校验无 NUL**（未做）
4. **`current_tick` / `max_tick` 维护分散**：commit_events、advance_time、各种工具调用都在改，**容易出现 max_tick < 实际最大 event.tick 的不一致**
5. **删 world 时级联清理不全**：`worlds` 行删了但 `manuscript_chunks` / `snapshots` / `chapter_markers` / `plot_threads` / `agent_traces` 等的孤儿行不会被自动清，长期累积。**需要 ON DELETE CASCADE 或显式级联**（2026-05 体检发现，已手动清，未做根治）

### 索引
- `events_branch_tick`、`plot_threads_branch_status` 都有
- 但 `Entity` 表只有 `branch_id` 索引，按 type / name 查没有 — 大世界（500+ 实体）会慢

---

## 三、`engine/` 模块清单

```
author.py              Author agent（生成叙事）
blueprint.py           世界蓝图设计
blueprint_render.py    蓝图 → 实体
character_view.py      单角色视角
consistency.py         一致性扫描
dialogue_rehearsal.py  对话排练
draft_cleanup.py       草稿清理
editor.py              Editor agent（修订）
executor.py            工具调用执行器（427 行）
jobs.py                后台任务管理
lore_gaps.py           世界设定补全
manuscript.py          手稿主文件
manuscript_events.py   V2 事件抽取（442 行）
manuscript_ingest.py   V1 骨架抽取（416 行）
map_sim.py             地图模拟
multi_agent.py         多 agent 协调
novelize.py            事件 → 散文
patch.py               IssuePatch 应用
persona_extract.py     persona 萃取
pov.py                 POV 改写
recap.py               进度回顾
scene_continuity.py    场景连续性扫描
simulator.py           主推演循环（594 行）
snapshots.py           快照管理
state.py               world state 序列化（487 行）
style_seeds.py         文风模板种子
thread_aging.py        PlotThread 老化
tools.py               12 个工具定义
transitions.py         状态转换
worldgen.py            程序化世界生成（625 行）
```

**30 个模块**，平均 200-400 行，中等粒度。

### 设计上做对的
- `state.py` 把 prompt 字段过滤集中处理，避免 token 浪费
- `executor.py` 工具调用逻辑独立，测试得动
- `simulator.py` 主循环抽象到位
- `providers/` 4 个 LLM 抽象到 `base.py`，新加 provider 不痛

### 设计上的味道
1. **模块命名风格不统一**：`character_view` vs `multi_agent` vs `dialogue_rehearsal` vs `lore_gaps` — 有的是「做什么」，有的是「概念」，没有统一动词法
2. **agent 概念散落**：`author.py` / `editor.py` / `multi_agent.py` / `character_view.py` 都是 agent 角色，**应该有 `agents/` 子目录归拢**
3. **手稿相关 4 个文件**：`manuscript.py` / `manuscript_events.py` / `manuscript_ingest.py` / `scene_continuity.py`，**应该有 `manuscript/` 子目录**
4. **`tools.py` + `executor.py` + `simulator.py` 三角关系**：tools 定义 schema，executor 执行 SQL，simulator 跑循环。三者耦合紧但各自职责清晰，**这块设计是项目最优秀的部分**

### 建议的目录重构（低风险，纯搬运）
```
engine/
  agents/          author, editor, character_view, multi_agent, dialogue_rehearsal
  manuscript/      ingest (V1), events (V2), scene_continuity, manuscript (主文件)
  consistency/     consistency, patch, scene_continuity（重叠选其一）
  worldgen/        blueprint, blueprint_render, worldgen, lore_gaps, style_seeds
  core/            state, executor, simulator, tools, snapshots, jobs
  views/           novelize, pov, recap, character_view, transitions
  map/             map_sim
```

---

## 四、API 层评审：`routes.py` 4089 行 / 95 端点

**必须拆**。建议按业务域：

```python
# 现状：routes.py 一个文件 95 个端点
# 建议：

api/
  __init__.py          # 主 router 装配
  worlds.py            # /worlds CRUD（~15 端点）
  branches.py          # /branches（~8）
  entities.py          # /entities CRUD + persona（~12）
  events.py            # /events + causal_links（~10）
  manuscript.py        # /manuscript/* （~10，T2/T3 都在这）
  consistency.py       # /scan_consistency, /issues, /patches（~10）
  novelize.py          # /novelize, /pov, /export（~8）
  map.py               # 已经独立成 map_routes.py 了
  templates.py         # /templates（~5）
  jobs.py              # /jobs/*（~5）
  styles.py            # /style_profiles（~5）
  llm_config.py        # /llm/*（~5）
```

**实施成本**：纯搬运，半天能搞完。**不拆的成本**：每次找端点要在 4000 行里 grep。

---

## 五、前端评审

### 双前端是头号问题
- `frontend/`（Alpine 12.6k 行）：能跑、稳定、但单文件 `app.js` ~3500 行
- `frontend-next/`（Vue 6.8k 行）：现代、组件化、但功能尚未追平

**决策建议**：
- 明确 `frontend-next` 是主线
- 老 `frontend/` 进入冻结：只修严重 bug，不加功能
- 设定时间点：T2/T3/T1 全跑通后 1 个月内删除老版

### `frontend-next/` 内部
| 文件 | 行数 | 评价 |
|---|---|---|
| `WorldSettingsView.vue` | 927 | **过胖**。手稿 / 范围抽取 / 审阅 / 风格绑定全在一起 |
| `services/api.ts` | 713 | 还可接受，但接近"上帝文件" |
| `CastView.vue` | 604 | 合理 |
| `ChaptersView.vue` | 574 | 合理 |
| 其它 view | 400-500 | 合理 |

**`WorldSettingsView` 拆分建议**：
```
views/world/settings/
  WorldSettingsView.vue       # 入口 + 标签页
  GeneralPanel.vue            # 名称 / 描述 / 大纲
  BranchesPanel.vue           # 分支管理
  SnapshotsPanel.vue          # 快照
  StylePanel.vue              # 文风
  ManuscriptPanel.vue         # 手稿全部相关
  ManuscriptReviewModal.vue   # 审阅 modal 单独抽
```

### 状态管理
- 用 Pinia（`stores/toast.ts`）但只有 toast 一个 store
- 大部分状态在 view 内部 ref，跨 view 通信靠重新 fetch
- **判断**：现阶段 OK，但角色 / 事件可能要提到 store 让多个 view 共用

---

## 六、Provider / LLM 抽象

```
providers/
  base.py              抽象接口
  claude.py            Anthropic SDK
  openai_provider.py   OpenAI SDK
  deepseek.py          OpenAI 兼容
  ollama.py            本地，prompt 模拟 tool calling
  config.py            配置读写
```

### 做对的
- `Message` / `LLMProvider` 抽象到位，新加 Gemini / Mistral 不难
- 配置 hot reload，UI 层切换不需重启
- DeepSeek 复用 OpenAI 协议，代码不重复

### 担心的
1. **Ollama 用 prompt 模拟工具调用**：复杂场景肯定不稳。**应该限定 Ollama 路径只跑非工具任务（叙事 / 改写）**，工具调用强制原生 tool use 路径
2. **`max_tokens` 各处硬编码**：6000、4000、2000 散落各模块。**应该集中配置**
3. **超时 240s / 180s 也散落**：长 prompt 怎么处理没有统一策略

---

## 七、测试覆盖

```
backend/tests/  6020 行  115+ 条
```

### 强项
- FakeProvider 替身设计优秀，跑测试不打真 LLM
- conftest.py 的 fixture 设计合理
- 2.5 秒跑完，开发反馈循环快

### 弱项
1. **没有手稿模块的测试**：`manuscript_ingest` / `manuscript_events` 都没有专属 test 文件
2. **没有一致性扫描的端到端测试**：能测 JSON 解析，没测扫描器是否真能发现矛盾
3. **没有前端测试**：Vue 组件 0 测试。Settings View 927 行没有任何回归保护
4. **多分支场景测试薄**：`test_executor_branch_map.py` 一个文件，复杂分叉合并无覆盖

---

## 八、可观测性

**几乎没有**。

- 没有结构化日志（用 `logging`，但格式不统一）
- 没有指标（每次 advance 多少 token？哪个工具最常被调？哪个工具最常失败？）
- 没有 trace（一次 advance 调用了几次 LLM？分别多久？）
- LLM 错误只能在 stderr 看
- Job 进度只有字符串 message，没有结构化阶段

**建议**：
1. 至少加一个简单的 `metrics.py`：每个 LLM 调用记 (provider, model, tokens_in, tokens_out, latency, error)，写到 SQLite 一张表
2. Job 的 progress 加结构化字段：`{stage, current, total, eta}`，前端能画进度条
3. 关键调用加 OpenTelemetry hook（不强制接 collector，但接口先留好）

---

## 九、性能 / 成本

### 已知瓶颈
1. **手稿 V1 长小说**：3 批以上耗时 3-5 分钟，sync endpoint 会超时
2. **state.py 序列化大世界**：500+ 实体时 prompt 准备本身就慢
3. **`Snapshot.payload` JSON**：恢复一个大快照要解 50-100 KB JSON
4. ~~**`World.manuscript_chunks` JSON**~~：已独立成表（R 系列）。新隐患：`text` 列没编码校验，二进制污染会让单行膨胀几 MB（见可疑点 #3）

### 成本
- 一次完整手稿导入（V1 + V2 + 因果链）粗估 300k - 800k tokens 输入，**单次 3-8 美元**
- **当前 0 提示**：用户点下去之前不知道要花多少
- 应该有「预估 token / 预估成本」的 dry-run 接口

---

## 十、安全

- 单机本地工具，**没考虑多用户隔离**（合理，符合定位）
- LLM API key 存 `data/llm_config.json`，**纯文本**。如果 data 目录被 git commit 会泄露
- `.env` 在 `.gitignore` ✅
- `data/` 是否在 `.gitignore` 没确认 — **建议立刻确认**
- 用户上传手稿没有大小限制 — 一次塞 500 MB 文本会怎样？

---

## 十一、文档

- README 充实（这次刚重写）
- **没有 API 文档**：FastAPI 自带 `/docs` 在用就行，但参数说明散
- **没有 ADR**：18 张表为什么这么设计、为什么用 SQLite 不用 Postgres、为什么手稿分 V1/V2 — 都没文字记录
- **没有贡献指南**：单人项目暂时不需要

---

## 十二、技术债清单（按 ROI 排）

| 优先级 | 债 | 收益 | 成本 |
|---|---|---|---|
| **P0** | `routes.py` 拆分 | 后续每个改动都受益 | 半天 |
| **P0** | 老 `frontend/` 冻结公告 | 减半的维护精力 | 1 小时 |
| **P1** | `WorldSettingsView` 拆分 | T1 改动会涉及它 | 2-3 小时 |
| **P1** | `engine/` 子目录归拢 | 模块边界清晰 | 半天 |
| **P1** | LLM 调用集中配置（max_tokens / timeout） | 调参方便 | 1 小时 |
| **P2** | 手稿 / 一致性测试覆盖 | 大重构有底 | 1 天 |
| **P2** | `metrics.py` token / latency 记录 | 知道钱花哪了 | 2 小时 |
| **P3** | `Entity.attributes` JSON 拆列 | schema 健壮 | 半天 + 迁移 |
| **P3** | `manuscript_chunks` 移到独立表 | 性能 | 半天 + 迁移 |

---

## 十三、结论

设计的**骨架是好的**：
- 数据模型核心正确
- 工具调用框架（tools / executor / simulator）是项目最优秀的部分
- Provider 抽象到位
- 测试基础设施扎实

**问题集中在两层**：
1. **入口层（`routes.py` + 双前端 + 巨型 Vue 组件）已经超过单人项目舒适区**
2. **可观测性层几乎不存在**，写完就不知道运行情况

下一阶段如果要再扩展，必须先做拆分 + 加 metrics，否则改一个改一片，反馈也无从收集。

**好消息是**：所有问题都是机械式的工程债，不涉及任何架构性返工。半天到一天的拆分能解决其中 80%。
