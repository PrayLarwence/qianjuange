# Narrative Sandbox · 自动化叙事与世界线推演引擎

一个面向小说创作的世界模拟沙盒。把世界状态（实体、事件、因果、时间线、分支）建模成结构化数据，让 AI 通过工具调用一步步推演整个剧情，再把推演产物改写成可读的小说章节。

## 它做什么

### 推演核心
- **实体系统**：角色 / 地点 / 物品 / 组织 / 势力 / 概念，自由属性 + persona（drives、voice、blindspots）
- **事件系统**：每个事件有 tick、参与者、地点、后果
- **因果链**：事件间显式建立因果，可视化成 DAG
- **多世界线**：随时分叉，做 what-if 推演，可对比、合并
- **AI 推演**：AI 读当前状态、调用工具改变世界、生成叙事
- **多 Provider**：Claude / OpenAI / DeepSeek / Ollama 可切换，Web UI 可视化配置

### 视图与叙事
- **因果图**：cytoscape + dagre，节点是事件，连线是因果
- **时间线**：每条分支按 tick 排开
- **🕒 时空带**：vis-timeline 多分支并列甘特图，因果连线 + 章节标记叠加
- **📖 阅读**：把所有事件渲染成连贯散文，专注模式可全屏阅读
- **章节标记**：手动或自动切章，作为小说导出的章节锚点

### AI 能力
- **角色 LLM 视角**：每个角色一个 sub-agent，按 persona 出意图，导演综合落事件
- **persona 萃取**：从角色参与过的事件反推他的 drives / voice / blindspots
- **一致性扫描**：检测 OOC、时空矛盾、被遗忘的伏笔
- **角色弧光 / 情绪曲线**：跨 tick 追踪角色变化
- **关系图谱**：从事件推断角色间关系
- **POV 改写**：把全知第三人称改写成指定角色的第一人称
- **并发探索**：同一节点跑多个 what-if 分支，AI 评估推荐

### 世界生成
- **模板系统**：预设世界 + 种子实体 + 剧情大纲，跨书续写人物保留
- **程序化地图**：Voronoi 大陆 + 噪声地形 + 气候带 + 生物群系
- **地图模拟**：实体在地图上有坐标，可设移动目标，按 tick 推进

### 导出
- **小说 Markdown**：按章节切分，LLM 改写成可读小说
- **POV 成稿**：第三人称全知 / 角色第一人称
- **JSON 导出 / 导入**：完整世界状态可备份、迁移

## 快速开始

需要 Python 3.10+。

Windows:
```
run.bat
```

macOS / Linux:
```
chmod +x run.sh
./run.sh
```

首次会生成 `.env`。配置 API Key 两种方式：

- **推荐：可视化配置**。启动后打开 http://localhost:8000，点右上角 **⚙** 图标，填 Key、选模型、点"测试连接"。配置存于 `data/llm_config.json`，覆盖 `.env`。
- 或在 `.env` 里填好后再启动。

## 60 秒上手

1. 欢迎页选一个 **📚 模板**（推荐先选《水浒传》或《三国》某一章节，已经预填好骨架）
2. 底部"推演控制台"留空，点 **推 5 步**，AI 会自动调工具填实体、加事件、连因果
3. 切到 **📖 阅读** 视图看故事；切到 **🕒 时空带** 看分支结构
4. 点工具栏 **📖 导出小说**，AI 把这条分支改写成 markdown，复制或下载

## 架构

```
backend/
  app/
    models/      SQLAlchemy 模型 + SQLite
    providers/   Claude / OpenAI / DeepSeek / Ollama 抽象
    engine/      推演引擎、工具集、小说化、一致性、地图、persona 萃取
    api/         FastAPI 路由
    main.py
frontend/
  index.html     Tailwind + Alpine.js
  app.js         Cytoscape 因果图、vis-timeline 时空带、阅读视图
data/
  world.db       SQLite
```

## AI 可调用的工具

| 工具 | 作用 |
|------|------|
| `create_entity` | 创建角色/地点/物品/组织 |
| `update_entity` | 修改实体属性或状态 |
| `add_event` | 添加事件到时间线 |
| `update_event` / `delete_event` | 改写、软删除事件 |
| `link_causality` | 在两个事件间建立因果链 |
| `advance_time` | 推进世界时钟 |
| `branch_world` | 分叉新世界线 |
| `narrate` | 写入散文叙事 |
| `set_position` / `move_entity` | 地图坐标安放 / 设移动目标 |
| `end_turn` | 结束本轮 |

## 路线图

当前版本 v0.1+，下一阶段考虑：
- 单文件大模块拆分（`routes.py` 3000+ 行、`app.js` 3500+ 行）
- 测试覆盖（目前是端到端手测）
- 离线包（去 CDN 依赖）
- 角色对话风格更细粒度（按场景 / 情绪状态切换 voice）

## 注意

- AI 调用消耗 Token，长世界状态会让单次请求变贵。state 已自动截断到最近 30 事件 + 80 实体。
- 数据库在 `data/world.db`，删了就清空。LLM 配置在 `data/llm_config.json`。
- DeepSeek 走 OpenAI 兼容协议，原生支持 tool calling。
- Ollama 路径用 prompt 模拟工具调用，效果不如其它原生 tool use 路径稳定。
