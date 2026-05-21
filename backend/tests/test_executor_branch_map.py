"""branch_world / set_position / move_entity 测试。地图相关用 map_factory 隔离到 tmp_path。"""
from __future__ import annotations
import pytest

from app.engine.core.executor import execute_tool, ToolError
from app.models import Branch, Entity


# ---- branch_world ----

def test_branch_world_creates_new_branch(db, world_factory):
    w, parent = world_factory()
    res = execute_tool(db, w, "branch_world", {"name": "if-branch", "description": "what-if"})
    assert res["ok"] is True
    new_bid = res["branch_id"]

    branches = db.query(Branch).filter_by(world_id=w.id).all()
    assert len(branches) == 2
    new = next(b for b in branches if b.id == new_bid)
    assert new.parent_branch_id == parent.id
    assert new.name == "if-branch"
    assert new.diverged_at_tick == 0


def test_branch_world_requires_name(db, world_factory):
    w, _ = world_factory()
    with pytest.raises(ToolError):
        execute_tool(db, w, "branch_world", {"description": "no name"})


def test_branch_world_clones_entities(db, world_factory):
    w, parent = world_factory()
    # 父分支放一个角色
    execute_tool(db, w, "create_entity",
                 {"type": "character", "name": "原", "summary": "本尊"})
    # 分叉
    res = execute_tool(db, w, "branch_world", {"name": "fork"})
    new_bid = res["branch_id"]

    parent_entities = db.query(Entity).filter_by(branch_id=parent.id).all()
    new_entities = db.query(Entity).filter_by(branch_id=new_bid).all()
    assert len(parent_entities) == 1
    assert len(new_entities) == 1
    # 名字一致但 id 不同
    assert new_entities[0].name == "原"
    assert new_entities[0].id != parent_entities[0].id


def test_branch_world_records_diverge_tick(db, world_factory):
    w, _ = world_factory()
    w.current_tick = 7
    db.commit()
    res = execute_tool(db, w, "branch_world", {"name": "late"})
    new = db.query(Branch).filter_by(id=res["branch_id"]).first()
    assert new.diverged_at_tick == 7


# ---- set_position ----

def test_set_position_no_map_raises(db, world_factory):
    w, _ = world_factory()
    eid = execute_tool(db, w, "create_entity", {"type": "character", "name": "x"})["id"]
    with pytest.raises(ToolError, match="no map"):
        execute_tool(db, w, "set_position", {"id": eid, "x": 0, "y": 0})


def test_set_position_with_map(db, world_factory, map_factory):
    w, _ = world_factory()
    map_factory(w.id, 5, 5)
    eid = execute_tool(db, w, "create_entity", {"type": "character", "name": "x"})["id"]

    res = execute_tool(db, w, "set_position", {"id": eid, "x": 2, "y": 3})
    assert res["pos"] == [2, 3]

    db.expire_all()
    e = db.query(Entity).filter_by(id=eid).first()
    assert e.map_x == 2 and e.map_y == 3
    assert (e.sim_state or {}).get("status") == "idle"


def test_set_position_out_of_bounds(db, world_factory, map_factory):
    w, _ = world_factory()
    map_factory(w.id, 5, 5)
    eid = execute_tool(db, w, "create_entity", {"type": "character", "name": "x"})["id"]
    with pytest.raises(ToolError, match="out of"):
        execute_tool(db, w, "set_position", {"id": eid, "x": 99, "y": 0})


def test_set_position_missing_args(db, world_factory, map_factory):
    w, _ = world_factory()
    map_factory(w.id, 5, 5)
    eid = execute_tool(db, w, "create_entity", {"type": "character", "name": "x"})["id"]
    with pytest.raises(ToolError):
        execute_tool(db, w, "set_position", {"id": eid, "x": 1})  # 缺 y


def test_set_position_unknown_entity(db, world_factory, map_factory):
    w, _ = world_factory()
    map_factory(w.id, 5, 5)
    with pytest.raises(ToolError, match="entity not found"):
        execute_tool(db, w, "set_position", {"id": "ent_nope", "x": 0, "y": 0})


# ---- move_entity ----

def test_move_entity_sets_target(db, world_factory, map_factory):
    w, _ = world_factory()
    map_factory(w.id, 5, 5)
    eid = execute_tool(db, w, "create_entity", {"type": "character", "name": "x"})["id"]
    execute_tool(db, w, "set_position", {"id": eid, "x": 0, "y": 0})

    res = execute_tool(db, w, "move_entity", {"id": eid, "x": 4, "y": 4})
    assert res["to"] == [4, 4]

    db.expire_all()
    e = db.query(Entity).filter_by(id=eid).first()
    assert e.target_x == 4 and e.target_y == 4
    assert (e.sim_state or {}).get("status") == "moving"


def test_move_entity_clear_target_when_no_xy(db, world_factory, map_factory):
    w, _ = world_factory()
    map_factory(w.id, 5, 5)
    eid = execute_tool(db, w, "create_entity", {"type": "character", "name": "x"})["id"]
    execute_tool(db, w, "set_position", {"id": eid, "x": 0, "y": 0})
    execute_tool(db, w, "move_entity", {"id": eid, "x": 4, "y": 4})

    # 不带 x/y 应清目标
    res = execute_tool(db, w, "move_entity", {"id": eid})
    assert res.get("stopped") is True

    db.expire_all()
    e = db.query(Entity).filter_by(id=eid).first()
    assert e.target_x is None and e.target_y is None
    assert (e.sim_state or {}).get("status") == "idle"


def test_move_entity_without_position_raises(db, world_factory, map_factory):
    w, _ = world_factory()
    map_factory(w.id, 5, 5)
    eid = execute_tool(db, w, "create_entity", {"type": "character", "name": "x"})["id"]
    # 没 set_position 直接 move
    with pytest.raises(ToolError, match="no position"):
        execute_tool(db, w, "move_entity", {"id": eid, "x": 1, "y": 1})


def test_move_entity_speed_clamped(db, world_factory, map_factory):
    w, _ = world_factory()
    map_factory(w.id, 5, 5)
    eid = execute_tool(db, w, "create_entity", {"type": "character", "name": "x"})["id"]
    execute_tool(db, w, "set_position", {"id": eid, "x": 0, "y": 0})
    execute_tool(db, w, "move_entity", {"id": eid, "x": 3, "y": 3, "speed": 0.001})

    db.expire_all()
    e = db.query(Entity).filter_by(id=eid).first()
    assert e.move_speed == pytest.approx(0.1)  # clamped to floor
