"""引擎纯函数测试 —— 不依赖 DB / LLM。"""
from __future__ import annotations

from app.engine.state import _entity_for_prompt


def test_prompt_drops_empty_summary():
    full = {"id": "e1", "type": "character", "name": "周浩然",
            "summary": "", "attributes": {}}
    out = _entity_for_prompt(full)
    assert "summary" not in out
    assert "attributes" not in out
    assert out["name"] == "周浩然"
    assert out["type"] == "character"


def test_prompt_keeps_meaningful_fields():
    full = {"id": "e1", "type": "character", "name": "吴用",
            "summary": "智多星", "attributes": {"iq": 99}, "state": {"alive": 1}}
    out = _entity_for_prompt(full)
    assert out["summary"] == "智多星"
    assert out["attributes"] == {"iq": 99}
    assert out["state"] == {"alive": 1}


def test_prompt_position_packed_into_pos():
    full = {"id": "e1", "type": "character", "name": "x",
            "map_x": 10, "map_y": 20}
    out = _entity_for_prompt(full)
    assert out["pos"] == [10, 20]
    assert "map_x" not in out and "map_y" not in out


def test_prompt_target_with_speed():
    full = {"id": "e1", "type": "character", "name": "x",
            "target_x": 5, "target_y": 6, "move_speed": 2.5}
    out = _entity_for_prompt(full)
    assert out["target"] == [5, 6]
    assert out["speed"] == 2.5


def test_prompt_partial_position_dropped():
    """只有 x 没有 y 时不应输出 pos —— 防止脏数据漏出。"""
    full = {"id": "e1", "type": "character", "name": "x", "map_x": 10}
    out = _entity_for_prompt(full)
    assert "pos" not in out


def test_prompt_status_idle_dropped():
    full = {"id": "e1", "type": "character", "name": "x",
            "sim_state": {"status": "idle"}}
    out = _entity_for_prompt(full)
    assert "status" not in out


def test_prompt_status_blocked_kept():
    full = {"id": "e1", "type": "character", "name": "x",
            "sim_state": {"status": "moving", "blocked_reason": "山"}}
    out = _entity_for_prompt(full)
    assert out["status"] == "moving"
    assert out["blocked"] == "山"


def test_build_state_snapshot_minimal(db, world_factory):
    """落库一个空世界后，build_state_snapshot 应给出合法 shape。"""
    from app.engine.state import build_state_snapshot
    w, _ = world_factory(name="空世界")
    snap = build_state_snapshot(db, w)
    assert snap["world"]["id"] == w.id
    assert snap["world"]["current_tick"] == 0
    assert snap["entities"] == []
    assert snap["recent_events"] == []
    assert snap["causal_links"] == []


def test_build_state_snapshot_with_entity(db, world_factory):
    from app.engine.state import build_state_snapshot
    from app.models import Entity
    w, br = world_factory(name="有人世界")
    db.add(Entity(id="e1", branch_id=br.id, type="character",
                  name="主角", summary="少侠",
                  attributes={}, state={}, alive=1, created_at_tick=0))
    db.commit()
    snap = build_state_snapshot(db, w)
    assert len(snap["entities"]) == 1
    assert snap["entities"][0]["name"] == "主角"


def test_build_state_snapshot_skips_dead(db, world_factory):
    from app.engine.state import build_state_snapshot
    from app.models import Entity
    w, br = world_factory()
    db.add(Entity(id="dead", branch_id=br.id, type="character",
                  name="阵亡者", summary="", attributes={}, state={},
                  alive=0, created_at_tick=0))
    db.add(Entity(id="alive", branch_id=br.id, type="character",
                  name="幸存者", summary="", attributes={}, state={},
                  alive=1, created_at_tick=0))
    db.commit()
    snap = build_state_snapshot(db, w)
    names = {e["name"] for e in snap["entities"]}
    assert "幸存者" in names
    assert "阵亡者" not in names
