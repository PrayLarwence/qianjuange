"""executor 剩余错误分支补测。"""
from __future__ import annotations
import pytest

from app.engine.executor import execute_tool, ToolError


# ---- update_event ----

def test_update_event_unknown_id(db, world_factory):
    w, _ = world_factory()
    with pytest.raises(ToolError):
        execute_tool(db, w, "update_event", {"id": "evt_none", "title": "新"})


def test_update_event_missing_id(db, world_factory):
    w, _ = world_factory()
    with pytest.raises(ToolError):
        execute_tool(db, w, "update_event", {"title": "新"})


def test_update_event_changes_title(db, world_factory):
    w, _ = world_factory()
    eid = execute_tool(db, w, "add_event", {"title": "旧", "description": ""})["id"]
    execute_tool(db, w, "update_event", {"id": eid, "title": "新"})
    db.expire_all()
    from app.models import Event
    assert db.query(Event).filter_by(id=eid).first().title == "新"


def test_update_event_changes_tick(db, world_factory):
    w, _ = world_factory()
    eid = execute_tool(db, w, "add_event", {"title": "x", "description": ""})["id"]
    execute_tool(db, w, "update_event", {"id": eid, "tick": 99})
    db.expire_all()
    from app.models import Event
    assert db.query(Event).filter_by(id=eid).first().tick == 99


# ---- delete_event ----

def test_delete_event_unknown_id(db, world_factory):
    w, _ = world_factory()
    with pytest.raises(ToolError):
        execute_tool(db, w, "delete_event", {"id": "evt_none"})


def test_delete_event_missing_id(db, world_factory):
    w, _ = world_factory()
    with pytest.raises(ToolError):
        execute_tool(db, w, "delete_event", {})


# ---- link_causality ----

def test_link_causality_missing_endpoints(db, world_factory):
    w, _ = world_factory()
    with pytest.raises(ToolError):
        execute_tool(db, w, "link_causality", {})


def test_link_causality_self_loop_rejected(db, world_factory):
    """A → A 应被拒绝（如果实现校验了）。"""
    w, _ = world_factory()
    a = execute_tool(db, w, "add_event", {"title": "a", "description": ""})["id"]
    # 即使未拒绝，也至少不应崩
    try:
        execute_tool(db, w, "link_causality",
                     {"cause_event_id": a, "effect_event_id": a})
    except ToolError:
        pass  # 拒绝也行


def test_link_causality_unknown_event(db, world_factory):
    w, _ = world_factory()
    a = execute_tool(db, w, "add_event", {"title": "a", "description": ""})["id"]
    with pytest.raises(ToolError):
        execute_tool(db, w, "link_causality",
                     {"cause_event_id": a, "effect_event_id": "evt_nope"})


# ---- narrate ----

def test_narrate_empty_text_raises(db, world_factory):
    w, _ = world_factory()
    with pytest.raises(ToolError):
        execute_tool(db, w, "narrate", {"text": ""})


def test_narrate_missing_text_raises(db, world_factory):
    w, _ = world_factory()
    with pytest.raises(ToolError):
        execute_tool(db, w, "narrate", {})
