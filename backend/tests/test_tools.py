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


# ---- prompt / 工具 schema 笔墨规范测试 ----

def test_system_prompt_carries_writing_rules():
    """SYSTEM_PROMPT 必须明确要求 description 含动作/神态/心理与最低字数。"""
    from app.engine.tools import SYSTEM_PROMPT
    # 关键词全部出现
    for kw in ("动作", "神态", "心理", "环境锚点", "80 字"):
        assert kw in SYSTEM_PROMPT, f"SYSTEM_PROMPT 缺少关键词: {kw}"
    # narrate 不再被定位为"可选的点缀"，而是关键节点鼓励
    assert "可选的点缀" not in SYSTEM_PROMPT
    assert "叙事面板" in SYSTEM_PROMPT


def test_add_event_tool_description_demands_prose():
    """add_event 的 description 字段说明应明确要求小说级文字 + 字数下限 + 反例。"""
    from app.engine.tools import TOOL_SPECS
    spec = next(t for t in TOOL_SPECS if t.name == "add_event")
    desc_field = spec.parameters["properties"]["description"]["description"]
    # 必须要求长度
    assert "80 字" in desc_field
    # 必须给出反例和正例做对比
    assert "反例" in desc_field and "正例" in desc_field
    # 必须点出三个层面
    assert "动作" in desc_field
    assert "神态" in desc_field or "心理" in desc_field


def test_narrate_tool_description_promotes_usage():
    """narrate 工具说明应鼓励主动使用并给出节奏建议。"""
    from app.engine.tools import TOOL_SPECS
    spec = next(t for t in TOOL_SPECS if t.name == "narrate")
    assert "100" in spec.description  # 有字数提示
    assert "2-3" in spec.description or "关键节点" in spec.description
