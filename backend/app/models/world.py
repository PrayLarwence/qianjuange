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
    text = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class ChapterMarker(Base):
    __tablename__ = "chapter_markers"
    id = Column(String, primary_key=True)
    branch_id = Column(String, ForeignKey("branches.id"), nullable=False, index=True)
    tick = Column(Integer, nullable=False)
    title = Column(String, default="")
    note = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


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
