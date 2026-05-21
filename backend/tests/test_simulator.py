"""端到端：用 FakeProvider 驱动 simulator.run_step。

证明完整链路：LLM 响应 → tool dispatch → 落库 → 返回 step 结果。
完全不打真 LLM。
"""
from __future__ import annotations

from app.engine.core.simulator import run_step
from app.providers.base import LLMResponse, ToolCall
from app.models import Entity, Event, NarrativeLog


def _tc(tcid: str, tool: str, **arguments) -> ToolCall:
    return ToolCall(id=tcid, name=tool, arguments=arguments)


def test_run_step_creates_entity_then_ends(db, world_factory, fake_llm):
    w, _ = world_factory()
    fake_llm.scripted = [
        LLMResponse(tool_calls=[
            _tc("1", "create_entity", type="character", name="武松", summary="打虎"),
        ]),
        LLMResponse(tool_calls=[_tc("2", "end_turn")]),
    ]
    res = run_step(db, w, provider=fake_llm)
    assert res["ok"] is True
    assert any(c["name"] == "create_entity" for c in res["tool_calls"])
    # 真的落库了
    assert db.query(Entity).filter_by(name="武松").count() == 1


def test_run_step_full_chain(db, world_factory, fake_llm):
    """单步内连发 advance_time + add_event + narrate + end_turn。"""
    w, _ = world_factory()
    fake_llm.scripted = [
        LLMResponse(tool_calls=[
            _tc("1", "advance_time", ticks=2),
            _tc("2", "add_event", title="夜袭", description="月色下出击"),
            _tc("3", "narrate", text="风冷如刀。"),
        ]),
        LLMResponse(tool_calls=[_tc("4", "end_turn")]),
    ]
    res = run_step(db, w, provider=fake_llm)
    assert res["ok"] is True

    # 状态变化
    db.refresh(w)
    assert w.current_tick == 2
    assert db.query(Event).filter_by(title="夜袭").count() == 1
    assert db.query(NarrativeLog).filter_by(text="风冷如刀。").count() == 1

    # tool_calls 序列含全部
    names = [c["name"] for c in res["tool_calls"]]
    assert "advance_time" in names
    assert "add_event" in names
    assert "narrate" in names


def test_run_step_text_only_becomes_narration(db, world_factory, fake_llm):
    """LLM 不调工具只回文本时，应自动 narrate 并落 NarrativeLog。"""
    w, _ = world_factory()
    fake_llm.scripted = [LLMResponse(text="风雨欲来。")]
    res = run_step(db, w, provider=fake_llm)
    assert res["ok"] is True
    assert db.query(NarrativeLog).filter_by(text="风雨欲来。").count() == 1


def test_run_step_records_llm_call(db, world_factory, fake_llm):
    """断言 simulator 真的调了 LLM 而不是走了 mock 分支。"""
    w, _ = world_factory()
    fake_llm.scripted = [LLMResponse(tool_calls=[_tc("1", "end_turn")])]
    run_step(db, w, provider=fake_llm)
    assert len(fake_llm.calls) >= 1
    # tools 应该是从 TOOL_SPECS 注入的
    tool_names = fake_llm.calls[0]["tools"]
    assert "create_entity" in tool_names
    assert "add_event" in tool_names
    assert "end_turn" in tool_names


def test_run_step_max_hops_breaks_loop(db, world_factory, fake_llm):
    """模型反复调工具不 end_turn 时，simulator 应在 MAX_HOPS_PER_STEP 内强制收尾。"""
    w, _ = world_factory()
    # 永远只调 advance_time，不发 end_turn
    fake_llm.scripted = [
        LLMResponse(tool_calls=[_tc(f"t{i}", "advance_time", ticks=1)])
        for i in range(20)
    ]
    res = run_step(db, w, provider=fake_llm)
    assert res["ok"] is True
    # 至少没死循环；hops 受限
    assert res["hops"] <= 8


def test_run_step_unknown_tool_records_error(db, world_factory, fake_llm):
    """未知工具应记录 error，不让 simulator 崩。"""
    w, _ = world_factory()
    fake_llm.scripted = [
        LLMResponse(tool_calls=[_tc("1", "totally_fake_tool", x=1)]),
        LLMResponse(tool_calls=[_tc("2", "end_turn")]),
    ]
    res = run_step(db, w, provider=fake_llm)
    assert res["ok"] is True
    bad = next(c for c in res["tool_calls"] if c["name"] == "totally_fake_tool")
    assert bad.get("error")
