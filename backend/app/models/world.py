from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Float, Text, ForeignKey, DateTime, JSON, Index,
)
from sqlalchemy.orm import relationship
from .db import Base


class World(Base):
    __tablename__ = "worlds"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    outline = Column(Text, default="")
    current_tick = Column(Integer, default=0)
    active_branch_id = Column(String, ForeignKey("branches.id", use_alter=True, name="fk_world_active_branch"))
    rules = Column(JSON, default=dict)
    template_id = Column(String, nullable=True)
    outline_progress = Column(JSON, default=dict)
    max_tick = Column(Integer, default=0)
    map_w = Column(Integer, default=0)
    map_h = Column(Integer, default=0)
    map_seed = Column(Integer, default=0)
    map_meta = Column(JSON, default=dict)
    style_profile_id = Column(String, ForeignKey("style_profiles.id", use_alter=True, name="fk_world_style_profile"), nullable=True)
    embedding_provider = Column(String, default="")  # '' | 'local_bge' | 'zhipu' | 'siliconflow'
    author_model_override = Column(String, default="")
    editor_model_override = Column(String, default="")
    reader_model_override = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    branches = relationship("Branch", back_populates="world", foreign_keys="Branch.world_id")


class Branch(Base):
    __tablename__ = "branches"
    id = Column(String, primary_key=True)
    world_id = Column(String, ForeignKey("worlds.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    parent_branch_id = Column(String, ForeignKey("branches.id"), nullable=True)
    diverged_at_tick = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    world = relationship("World", back_populates="branches", foreign_keys=[world_id])
    parent = relationship("Branch", remote_side=[id])


class Entity(Base):
    __tablename__ = "entities"
    id = Column(String, primary_key=True)
    branch_id = Column(String, ForeignKey("branches.id"), nullable=False, index=True)
    type = Column(String, nullable=False)
    name = Column(String, nullable=False)
    summary = Column(Text, default="")
    attributes = Column(JSON, default=dict)
    state = Column(JSON, default=dict)
    location_id = Column(String, ForeignKey("entities.id"), nullable=True)
    created_at_tick = Column(Integer, default=0)
    alive = Column(Integer, default=1)
    map_x = Column(Integer, nullable=True)
    map_y = Column(Integer, nullable=True)
    target_x = Column(Integer, nullable=True)
    target_y = Column(Integer, nullable=True)
    move_speed = Column(Float, default=1.0)
    sim_state = Column(JSON, default=dict)
    persona = Column(JSON, default=dict)
    memories = Column(JSON, default=list)


class Event(Base):
    __tablename__ = "events"
    id = Column(String, primary_key=True)
    branch_id = Column(String, ForeignKey("branches.id"), nullable=False, index=True)
    tick = Column(Integer, nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    location_id = Column(String, ForeignKey("entities.id"), nullable=True)
    participants = Column(JSON, default=list)
    consequences = Column(JSON, default=list)
    metadata_ = Column("metadata", JSON, default=dict)
    deleted = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


Index("ix_events_branch_tick", Event.branch_id, Event.tick)


class CausalLink(Base):
    __tablename__ = "causal_links"
    id = Column(String, primary_key=True)
    branch_id = Column(String, ForeignKey("branches.id"), nullable=False, index=True)
    cause_event_id = Column(String, ForeignKey("events.id"), nullable=False)
    effect_event_id = Column(String, ForeignKey("events.id"), nullable=False)
    description = Column(Text, default="")
    weight = Column(Float, default=1.0)


class Snapshot(Base):
    __tablename__ = "snapshots"
    id = Column(String, primary_key=True)
    branch_id = Column(String, ForeignKey("branches.id"), nullable=False)
    tick = Column(Integer, nullable=False)
    label = Column(String, default="")
    payload = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)


class NarrativeLog(Base):
    __tablename__ = "narrative_logs"
    id = Column(String, primary_key=True)
    branch_id = Column(String, ForeignKey("branches.id"), nullable=False, index=True)
    tick = Column(Integer, nullable=False)
    role = Column(String, default="narrator")
    # 新增：多 agent 管线下的稿件分类
    # 'director_draft' (Director 输出的粗稿，将被 Author 改写)
    # 'author_final'   (Author 改写后的定稿，用户实际看的)
    # 'editor_critique'(Editor 的评注，渲染时通常隐藏)
    # 'reader_feedback'(Reader Critic 的读后感，下回合喂给 Director)
    # 旧值 'narrator' / 'system' 等保留兼容
    text = Column(Text, default="")
    revision_index = Column(Integer, default=0)  # 同一 (tick, role) 的多版本号
    parent_log_id = Column(String, ForeignKey("narrative_logs.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


Index("ix_narrative_logs_branch_tick", NarrativeLog.branch_id, NarrativeLog.tick)
Index("ix_narrative_logs_role", NarrativeLog.role)


class ChapterMarker(Base):
    __tablename__ = "chapter_markers"
    id = Column(String, primary_key=True)
    branch_id = Column(String, ForeignKey("branches.id"), nullable=False, index=True)
    tick = Column(Integer, nullable=False)
    title = Column(String, default="")
    note = Column(Text, default="")
    summary = Column(Text, default="")  # B1: 章节凝练（一两句话），喂给 Director prompt
    created_at = Column(DateTime, default=datetime.utcnow)


class PlotThread(Base):
    __tablename__ = "plot_threads"
    id = Column(String, primary_key=True)
    branch_id = Column(String, ForeignKey("branches.id"), nullable=False, index=True)
    title = Column(String, default="")
    summary = Column(Text, default="")
    opened_tick = Column(Integer, nullable=False)
    closed_tick = Column(Integer, nullable=True)
    status = Column(String, default="open")  # 'open' | 'closed'
    resolution = Column(Text, default="")  # 收尾时填的兑现说明
    related_entity_ids = Column(JSON, default=list)  # 涉及的实体 id 列表（可选）
    created_at = Column(DateTime, default=datetime.utcnow)


Index("ix_plot_threads_branch_status", PlotThread.branch_id, PlotThread.status)


Index("ix_chapter_markers_branch_tick", ChapterMarker.branch_id, ChapterMarker.tick)


class WorldTemplate(Base):
    __tablename__ = "world_templates"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    category = Column(String, default="", index=True)
    description = Column(Text, default="")
    long_description = Column(Text, default="")
    cover_emoji = Column(String, default="📖")
    rules = Column(JSON, default=dict)
    seed_directive = Column(Text, default="")
    suggested_steps = Column(JSON, default=list)
    seed_entities = Column(JSON, default=list)
    canonical_outline = Column(JSON, default=list)
    series = Column(String, default="", index=True)
    series_order = Column(Integer, default=0)
    max_steps_hint = Column(Integer, default=30)
    tags = Column(JSON, default=list)
    author = Column(String, default="user")
    is_official = Column(Integer, default=0)
    use_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class ConsistencyIssue(Base):
    __tablename__ = "consistency_issues"
    id = Column(String, primary_key=True)
    world_id = Column(String, ForeignKey("worlds.id"), nullable=False, index=True)
    branch_id = Column(String, ForeignKey("branches.id"), nullable=True, index=True)
    category = Column(String, default="other", index=True)
    severity = Column(String, default="medium")
    title = Column(String, default="")
    description = Column(Text, default="")
    suggestion = Column(Text, default="")
    entity_ids = Column(JSON, default=list)
    tick_start = Column(Integer, default=0)
    tick_end = Column(Integer, default=0)
    status = Column(String, default="open", index=True)
    scan_id = Column(String, default="", index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)


class ScanRun(Base):
    __tablename__ = "scan_runs"
    id = Column(String, primary_key=True)
    world_id = Column(String, ForeignKey("worlds.id"), nullable=False, index=True)
    branch_id = Column(String, nullable=True)
    scope = Column(String, default="recent")
    tick_from = Column(Integer, default=0)
    tick_to = Column(Integer, default=0)
    issue_count = Column(Integer, default=0)
    status = Column(String, default="completed")
    error = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


# ==== 阶段 0 新表（先建好 schema，后续阶段才开始写入） ====


class StyleProfile(Base):
    """小说风格预设。kind='builtin' 全局共享；'custom' 绑 world_id。

    spec_text 是给 Author 的风格指令；sample_paragraphs 是范文片段（比 spec_text
    重要，是真正的"风格指纹"原料）；frozen=1 表示已锁定不允许修改（首次满意后
    用户冻结）。
    """
    __tablename__ = "style_profiles"
    id = Column(String, primary_key=True)
    world_id = Column(String, ForeignKey("worlds.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    kind = Column(String, default="builtin")  # 'builtin' | 'custom'
    category = Column(String, default="")  # 'narrative' | 'genre' | 'special'
    description = Column(Text, default="")  # 一行描述，UI 卡片用
    spec_text = Column(Text, default="")  # 给 Author 的完整风格 spec
    sample_paragraphs = Column(JSON, default=list)  # [{title, text}] 范文片段
    frozen = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


Index("ix_style_profiles_kind", StyleProfile.kind)


class EntitySnapshot(Base):
    """实体在某时间点的快照。ChapterMarker 触发时给重要 entity 拍照，
    用于 Author 写后期章节时引用 '初登场 / 上一章 / 当前' 三版人物。

    阶段 0 先建表不写入；B3 阶段才正式启用。
    """
    __tablename__ = "entity_snapshots"
    id = Column(String, primary_key=True)
    entity_id = Column(String, ForeignKey("entities.id"), nullable=False, index=True)
    branch_id = Column(String, ForeignKey("branches.id"), nullable=False, index=True)
    chapter_marker_id = Column(String, ForeignKey("chapter_markers.id"), nullable=True)
    tick = Column(Integer, nullable=False)
    persona_snapshot = Column(JSON, default=dict)
    attributes_snapshot = Column(JSON, default=dict)
    state_snapshot = Column(JSON, default=dict)
    summary_snapshot = Column(Text, default="")  # 当时角色简介
    created_at = Column(DateTime, default=datetime.utcnow)


Index("ix_entity_snapshots_entity_tick", EntitySnapshot.entity_id, EntitySnapshot.tick)


class EmbeddingChunk(Base):
    """段落向量索引。每段 author_final 异步 embed 后入库；后期 Author 写新段
    用 cosine 召回 top-k 相关历史段。

    embedding 字段存原始 float32 字节流；维度由 embedding_model 决定。阶段 0
    建表不写入；B2 阶段实装。
    """
    __tablename__ = "embedding_chunks"
    id = Column(String, primary_key=True)
    world_id = Column(String, ForeignKey("worlds.id"), nullable=False, index=True)
    branch_id = Column(String, ForeignKey("branches.id"), nullable=False, index=True)
    log_id = Column(String, ForeignKey("narrative_logs.id"), nullable=True, index=True)
    chapter_marker_id = Column(String, ForeignKey("chapter_markers.id"), nullable=True)
    tick = Column(Integer, default=0)
    text = Column(Text, default="")
    embedding = Column(Text, default="")  # JSON-encoded list[float]，简化跨环境兼容
    embedding_model = Column(String, default="")
    dim = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


Index("ix_embedding_chunks_world_chapter", EmbeddingChunk.world_id, EmbeddingChunk.chapter_marker_id)


class ChapterSummary(Base):
    """章节级摘要。每个 ChapterMarker 触发时异步生成 200 字摘要，进 Director/
    Author prompt 的 '章节摘要列表' 段。阶段 0 建表，B1 阶段填充。
    """
    __tablename__ = "chapter_summaries"
    id = Column(String, primary_key=True)
    chapter_marker_id = Column(String, ForeignKey("chapter_markers.id"), nullable=False, index=True)
    branch_id = Column(String, ForeignKey("branches.id"), nullable=False, index=True)
    summary = Column(Text, default="")
    key_event_ids = Column(JSON, default=list)
    word_count = Column(Integer, default=0)
    model_used = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
