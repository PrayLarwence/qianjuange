"""multi_agent.run_multi_agent_step：sub-agent 产 intent → director 落事件。

整条链路用 FakeProvider 驱动。
"""
from __future__ import annotations
import pytest

from app.providers.base import LLMResponse, ToolCall
from app.engine.core.executor import execute_tool
from app.engine import multi_agent
from app.models import Event


def _tc(tcid: str, tool: str, **arguments) -> ToolCall:
    return ToolCall(id=tcid, name=tool, arguments=arguments)


# ---- pick_focal_characters ----

def test_pick_focal_picks_only_alive_characters(db, world_factory):
    w, _ = world_factory()
    a = execute_tool(db, w, "create_entity", {"type": "character", "name": "活"})["id"]
    b = execute_tool(db, w, "create_entity", {"type": "character", "name": "死"})["id"]
    # location 不应被选
    execute_tool(db, w, "create_entity", {"type": "location", "name": "山头"})
    # 把 b 标记死
    execute_tool(db, w, "update_entity", {"id": b, "state": {}})
    db.expire_all()
    from app.models import Entity
    db.query(Entity).filter_by(id=b).first().alive = 0
    db.commit()

    picked = multi_agent.pick_focal_characters(db, w, limit=4)
    assert a in picked
    assert b not in picked


def test_pick_focal_respects_limit(db, world_factory):
    w, _ = world_factory()
    for i in range(5):
        execute_tool(db, w, "create_entity", {"type": "character", "name": f"c{i}"})
    picked = multi_agent.pick_focal_characters(db, w, limit=3)
    assert len(picked) == 3


def test_pick_focal_empty(db, world_factory):
    w, _ = world_factory()
    assert multi_agent.pick_focal_characters(db, w) == []


# ---- run_subagent_turn ----

def test_subagent_speak_intent_collected(db, world_factory):
    w, _ = world_factory()
    cid = execute_tool(db, w, "create_entity", {"type": "character", "name": "甲"})["id"]

    class FakeP:
        name = "fake"
        def __init__(self):
            self.scripted = [
                LLMResponse(tool_calls=[_tc("1", "speak", text="我要走")]),
                LLMResponse(tool_calls=[_tc("2", "end_turn")]),
            ]
        def chat(self, system, messages, tools, **kw):
            return self.scripted.pop(0) if self.scripted else LLMResponse()

    bundle = multi_agent.run_subagent_turn(db, w, cid, provider=FakeP())
    assert bundle["character_id"] == cid
    assert bundle["finished"] is True
    types = [it["type"] for it in bundle["intents"]]
    assert "speak" in types
    # speak 不应直接落库（subagent 只是产 intent）
    assert db.query(Event).count() == 0


def test_subagent_unknown_character_raises(db, world_factory):
    w, _ = world_factory()
    fake = type("F", (), {"name": "f", "chat": lambda self, *a, **k: LLMResponse()})()
    with pytest.raises(ValueError):
        multi_agent.run_subagent_turn(db, w, "ent_nope", provider=fake)


def test_subagent_text_only_no_intent(db, world_factory):
    """LLM 只回文本不调工具时，应直接收尾（intents 空）。"""
    w, _ = world_factory()
    cid = execute_tool(db, w, "create_entity", {"type": "character", "name": "沉默者"})["id"]

    class FakeP:
        name = "fake"
        def chat(self, system, messages, tools, **kw):
            return LLMResponse(text="...")

    bundle = multi_agent.run_subagent_turn(db, w, cid, provider=FakeP())
    assert bundle["intents"] == []


# ---- run_multi_agent_step (full path) ----

def test_run_multi_agent_step_falls_back_when_no_chars(db, world_factory):
    """没有可选 focal 时应退化为 simulator.run_step。"""
    w, _ = world_factory()

    class FakeP:
        name = "fake"
        def __init__(self):
            self.scripted = [
                LLMResponse(tool_calls=[_tc("d1", "end_turn")]),
            ]
        def chat(self, system, messages, tools, **kw):
            return self.scripted.pop(0) if self.scripted else LLMResponse()

    res = multi_agent.run_multi_agent_step(db, w, character_ids=None, provider=FakeP())
    # 退化路径：simulator.run_step 直接返回 step dict（无 subagents 键）
    assert "subagents" not in res or res.get("subagents") == []


def test_run_multi_agent_step_full_chain(db, world_factory):
    """两个角色各产 intent，director 解析后落 1 个 add_event。"""
    w, _ = world_factory()
    a = execute_tool(db, w, "create_entity", {"type": "character", "name": "甲"})["id"]
    b = execute_tool(db, w, "create_entity", {"type": "character", "name": "乙"})["id"]

    class FakeP:
        name = "fake"
        def __init__(self):
            self.scripted = [
                # subagent 1: speak + end_turn
                LLMResponse(tool_calls=[_tc("a1", "speak", text="挑战！")]),
                LLMResponse(tool_calls=[_tc("a2", "end_turn")]),
                # subagent 2: propose + end_turn
                LLMResponse(tool_calls=[_tc("b1", "propose_action", action="迎战")]),
                LLMResponse(tool_calls=[_tc("b2", "end_turn")]),
                # director: add_event + end_turn
                LLMResponse(tool_calls=[
                    _tc("d1", "add_event", title="对决", description="开打"),
                    _tc("d2", "end_turn"),
                ]),
            ]
        def chat(self, system, messages, tools, **kw):
            return self.scripted.pop(0) if self.scripted else LLMResponse(
                tool_calls=[_tc("auto_end", "end_turn")]
            )

    p = FakeP()
    res = multi_agent.run_multi_agent_step(db, w, character_ids=[a, b], provider=p)
    assert res["ok"] is True
    assert len(res["subagents"]) == 2
    intent_types = [it["type"] for sub in res["subagents"] for it in sub["intents"]]
    assert "speak" in intent_types
    assert "propose_action" in intent_types
    # director 落了事件
    assert db.query(Event).filter_by(title="对决").count() == 1


# ---- sub-agent 文学性 prompt / 工具 schema ----

def test_subagent_system_prompt_has_writing_rules():
    """SUBAGENT_SYSTEM_PROMPT 应包含'笔墨'章节，要求细节而非日志。"""
    from app.engine.agents.multi_agent import SUBAGENT_SYSTEM_PROMPT
    assert "笔墨" in SUBAGENT_SYSTEM_PROMPT
    # 关键词
    for kw in ("voice", "细节", "元叙述"):
        assert kw in SUBAGENT_SYSTEM_PROMPT, f"missing keyword: {kw}"


def test_subagent_speak_tool_demands_voice():
    """speak 工具说明应要求台词体现 voice，不是中性叙述。"""
    from app.engine.agents.multi_agent import SUBAGENT_TOOLS
    spec = next(t for t in SUBAGENT_TOOLS if t.name == "speak")
    assert "voice" in spec.description.lower()


def test_subagent_propose_action_demands_imagery():
    """propose_action 应要求画面感动作描述，提供反例对比。"""
    from app.engine.agents.multi_agent import SUBAGENT_TOOLS
    spec = next(t for t in SUBAGENT_TOOLS if t.name == "propose_action")
    assert "画面感" in spec.description
    assert "差例" in spec.description and "好例" in spec.description
