"""tools 执行测试 —— 直接调用 execute_tool，验证落库正确。"""
from __future__ import annotations
import pytest

from app.engine.executor import execute_tool, ToolError
from app.models import Entity, Event, CausalLink, NarrativeLog


def test_create_entity_persists(db, world_factory):
    w, _ = world_factory()
    res = execute_tool(db, w, "create_entity", {
        "type": "character", "name": "林冲", "summary": "豹子头"
    })
    assert res["ok"] is True
    eid = res["id"]
    e = db.query(Entity).filter_by(id=eid).first()
    assert e is not None
    assert e.name == "林冲"
    assert e.type == "character"
    assert e.alive == 1


def test_create_entity_requires_name(db, world_factory):
    w, _ = world_factory()
    with pytest.raises(ToolError):
        execute_tool(db, w, "create_entity", {"type": "character"})


def test_create_entity_requires_type(db, world_factory):
    w, _ = world_factory()
    with pytest.raises(ToolError):
        execute_tool(db, w, "create_entity", {"name": "x"})


def test_update_entity_merges_attributes(db, world_factory):
    w, _ = world_factory()
    res = execute_tool(db, w, "create_entity",
                       {"type": "character", "name": "张三",
                        "attributes": {"hp": 100, "mood": "calm"}})
    eid = res["id"]
    execute_tool(db, w, "update_entity",
                 {"id": eid, "attributes": {"mood": "angry"}})
    db.expire_all()
    e = db.query(Entity).filter_by(id=eid).first()
    # 浅合并：hp 保留，mood 覆盖
    assert e.attributes["hp"] == 100
    assert e.attributes["mood"] == "angry"


def test_update_entity_unknown_id_raises(db, world_factory):
    w, _ = world_factory()
    with pytest.raises(ToolError):
        execute_tool(db, w, "update_entity", {"id": "ent_nonexistent"})


def test_add_event_uses_world_tick_when_missing(db, world_factory):
    w, _ = world_factory()
    w.current_tick = 5
    db.commit()
    res = execute_tool(db, w, "add_event",
                       {"title": "出发", "description": "上路了"})
    assert res["ok"] is True
    e = db.query(Event).filter_by(id=res["id"]).first()
    assert e.tick == 5


def test_add_event_explicit_tick(db, world_factory):
    w, _ = world_factory()
    w.current_tick = 5
    db.commit()
    res = execute_tool(db, w, "add_event",
                       {"title": "回忆", "description": "...", "tick": 1})
    e = db.query(Event).filter_by(id=res["id"]).first()
    assert e.tick == 1


def test_delete_event_soft_delete(db, world_factory):
    w, _ = world_factory()
    res = execute_tool(db, w, "add_event",
                       {"title": "可撤销", "description": ""})
    eid = res["id"]
    execute_tool(db, w, "delete_event", {"id": eid, "reason": "重写"})
    e = db.query(Event).filter_by(id=eid).first()
    assert e is not None  # 不真删
    assert e.deleted == 1


def test_link_causality(db, world_factory):
    w, _ = world_factory()
    a = execute_tool(db, w, "add_event", {"title": "A", "description": ""})["id"]
    b = execute_tool(db, w, "add_event", {"title": "B", "description": ""})["id"]
    res = execute_tool(db, w, "link_causality",
                       {"cause_event_id": a, "effect_event_id": b,
                        "description": "A 导致 B"})
    assert res["ok"] is True
    links = db.query(CausalLink).all()
    assert len(links) == 1
    assert links[0].cause_event_id == a
    assert links[0].effect_event_id == b


def test_advance_time_increases_tick(db, world_factory):
    w, _ = world_factory()
    assert w.current_tick == 0
    execute_tool(db, w, "advance_time", {"ticks": 3})
    assert w.current_tick == 3


def test_advance_time_default_one(db, world_factory):
    w, _ = world_factory()
    execute_tool(db, w, "advance_time", {})
    assert w.current_tick == 1


def test_advance_time_zero_raises(db, world_factory):
    w, _ = world_factory()
    with pytest.raises(ToolError):
        execute_tool(db, w, "advance_time", {"ticks": 0})


def test_narrate_writes_log(db, world_factory):
    w, _ = world_factory()
    execute_tool(db, w, "narrate", {"text": "夜色降临"})
    logs = db.query(NarrativeLog).all()
    assert len(logs) == 1
    assert logs[0].text == "夜色降临"


def test_unknown_tool_raises(db, world_factory):
    w, _ = world_factory()
    with pytest.raises(ToolError):
        execute_tool(db, w, "nonexistent_tool", {})


def test_end_turn_returns_ended(db, world_factory):
    w, _ = world_factory()
    res = execute_tool(db, w, "end_turn", {})
    assert res["ended"] is True
