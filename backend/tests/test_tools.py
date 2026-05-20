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


# ---- advance_outline_beat ----

def test_advance_outline_beat_tool_registered():
    """工具应注册并描述清楚触发条件 + no-op 行为。"""
    from app.engine.tools import TOOL_SPECS
    spec = next(t for t in TOOL_SPECS if t.name == "advance_outline_beat")
    assert "current_index" in spec.description
    assert "no-op" in spec.description.lower() or "noop" in spec.description.lower()


def test_advance_outline_beat_noop_without_template(db, world_factory):
    """无模板时应 ok 返回但 advanced=False，不抛错。"""
    w, _ = world_factory()
    res = execute_tool(db, w, "advance_outline_beat", {})
    assert res["ok"] is True
    assert res["advanced"] is False
    assert res["reason"] == "no_template"


def test_advance_outline_beat_advances_progress(db, world_factory):
    """正常推进：current_index 加 1，旧 index 进 completed，写一条系统日志。"""
    from app.models import WorldTemplate, NarrativeLog
    import uuid
    t = WorldTemplate(
        id=f"t_{uuid.uuid4().hex[:8]}", name="x", description="",
        canonical_outline=[{"beat": "开学"}, {"beat": "分院"}, {"beat": "期末"}],
    )
    db.add(t); db.commit()
    w, _ = world_factory()
    w.template_id = t.id
    w.outline_progress = {"current_index": 1, "completed": [0]}
    db.commit()

    res = execute_tool(db, w, "advance_outline_beat", {"note": "魁地奇试训完成"})
    assert res["advanced"] is True
    assert res["completed_index"] == 1
    assert res["new_current_index"] == 2

    db.refresh(w)
    assert w.outline_progress["current_index"] == 2
    assert 1 in w.outline_progress["completed"]

    # 系统日志应被写入
    log = (db.query(NarrativeLog)
             .filter_by(role="system")
             .order_by(NarrativeLog.created_at.desc())
             .first())
    assert log is not None
    assert "节拍 #1" in log.text
    assert "分院" in log.text
    assert "魁地奇试训完成" in log.text


def test_advance_outline_beat_noop_when_all_done(db, world_factory):
    """current_index 已超出 outline 长度时 noop。"""
    from app.models import WorldTemplate
    import uuid
    t = WorldTemplate(id=f"t_{uuid.uuid4().hex[:8]}", name="x", description="",
                      canonical_outline=[{"beat": "唯一"}])
    db.add(t); db.commit()
    w, _ = world_factory()
    w.template_id = t.id
    w.outline_progress = {"current_index": 5, "completed": [0]}
    db.commit()

    res = execute_tool(db, w, "advance_outline_beat", {})
    assert res["advanced"] is False
    assert res["reason"] == "all_done"


def test_advance_outline_beat_marks_all_done_on_last_beat(db, world_factory):
    """推进最后一拍后 all_done=True。"""
    from app.models import WorldTemplate
    import uuid
    t = WorldTemplate(id=f"t_{uuid.uuid4().hex[:8]}", name="x", description="",
                      canonical_outline=[{"beat": "A"}, {"beat": "B"}])
    db.add(t); db.commit()
    w, _ = world_factory()
    w.template_id = t.id
    w.outline_progress = {"current_index": 1, "completed": [0]}
    db.commit()

    res = execute_tool(db, w, "advance_outline_beat", {})
    assert res["advanced"] is True
    assert res["all_done"] is True

    db.refresh(w)
    assert w.outline_progress["current_index"] == 2


def test_advance_outline_beat_noop_when_template_has_empty_outline(db, world_factory):
    """模板存在但 canonical_outline 为空时不应崩。"""
    from app.models import WorldTemplate
    import uuid
    t = WorldTemplate(id=f"t_{uuid.uuid4().hex[:8]}", name="x", description="",
                      canonical_outline=[])
    db.add(t); db.commit()
    w, _ = world_factory()
    w.template_id = t.id
    db.commit()

    res = execute_tool(db, w, "advance_outline_beat", {})
    assert res["advanced"] is False
    assert res["reason"] == "no_outline"


def test_advance_outline_beat_does_not_double_complete(db, world_factory):
    """如果旧 current_index 已经在 completed 里（边界），不应重复添加。"""
    from app.models import WorldTemplate
    import uuid
    t = WorldTemplate(id=f"t_{uuid.uuid4().hex[:8]}", name="x", description="",
                      canonical_outline=[{"beat": "A"}, {"beat": "B"}])
    db.add(t); db.commit()
    w, _ = world_factory()
    w.template_id = t.id
    # 异常状态：current_index=0 但 0 已在 completed（人为构造）
    w.outline_progress = {"current_index": 0, "completed": [0]}
    db.commit()

    execute_tool(db, w, "advance_outline_beat", {})
    db.refresh(w)
    assert w.outline_progress["completed"].count(0) == 1  # 仍只一个 0
    assert w.outline_progress["current_index"] == 1


# ---- plot_threads ----

def test_plot_thread_tools_registered():
    from app.engine.tools import TOOL_SPECS
    names = {t.name for t in TOOL_SPECS}
    assert "open_plot_thread" in names
    assert "close_plot_thread" in names
    op = next(t for t in TOOL_SPECS if t.name == "open_plot_thread")
    cl = next(t for t in TOOL_SPECS if t.name == "close_plot_thread")
    # required 字段约束
    assert "title" in op.parameters["required"]
    assert "summary" in op.parameters["required"]
    assert "thread_id" in cl.parameters["required"]


def test_open_plot_thread_creates_row_and_logs(db, world_factory):
    from app.models import PlotThread, NarrativeLog
    w, _ = world_factory()
    w.current_tick = 7
    db.commit()

    res = execute_tool(db, w, "open_plot_thread", {
        "title": "林冲未报高俅之仇",
        "summary": "林冲在白虎堂被陷害发誓必杀，但尚未行动",
        "related_entity_ids": ["c_linchong", "c_gaoqiu"],
    })
    assert res["ok"] is True and res["status"] == "open"
    th = db.query(PlotThread).filter_by(id=res["id"]).first()
    assert th is not None
    assert th.status == "open"
    assert th.opened_tick == 7
    assert th.related_entity_ids == ["c_linchong", "c_gaoqiu"]

    log = db.query(NarrativeLog).filter_by(role="system").first()
    assert log is not None
    assert "钩子开启" in log.text and "林冲" in log.text


def test_open_plot_thread_requires_title_and_summary(db, world_factory):
    from app.engine.executor import ToolError
    import pytest
    w, _ = world_factory()
    with pytest.raises(ToolError):
        execute_tool(db, w, "open_plot_thread", {"title": "x"})  # 没 summary
    with pytest.raises(ToolError):
        execute_tool(db, w, "open_plot_thread", {"summary": "x"})  # 没 title


def test_close_plot_thread_marks_closed_and_records_resolution(db, world_factory):
    from app.models import PlotThread, NarrativeLog
    w, _ = world_factory()
    w.current_tick = 3
    db.commit()
    o = execute_tool(db, w, "open_plot_thread", {"title": "t", "summary": "s"})
    tid = o["id"]

    w.current_tick = 18
    db.commit()
    res = execute_tool(db, w, "close_plot_thread",
                       {"thread_id": tid, "resolution": "在沧州野猪林一役收"})
    assert res["closed"] is True

    th = db.query(PlotThread).filter_by(id=tid).first()
    assert th.status == "closed"
    assert th.closed_tick == 18
    assert "野猪林" in th.resolution

    sys_logs = db.query(NarrativeLog).filter_by(role="system").all()
    closing = [l for l in sys_logs if "钩子收束" in l.text]
    assert len(closing) == 1
    assert "野猪林" in closing[0].text


def test_close_plot_thread_noop_when_not_found(db, world_factory):
    w, _ = world_factory()
    res = execute_tool(db, w, "close_plot_thread", {"thread_id": "nope_xxx"})
    assert res["ok"] is True
    assert res["closed"] is False
    assert res["reason"] == "not_found"


def test_close_plot_thread_noop_when_already_closed(db, world_factory):
    w, _ = world_factory()
    o = execute_tool(db, w, "open_plot_thread", {"title": "t", "summary": "s"})
    execute_tool(db, w, "close_plot_thread", {"thread_id": o["id"]})
    # 再 close 一次
    res = execute_tool(db, w, "close_plot_thread", {"thread_id": o["id"]})
    assert res["closed"] is False
    assert res["reason"] == "already_closed"


def test_state_snapshot_exposes_open_threads(db, world_factory):
    from app.engine.state import build_state_snapshot, state_as_prompt
    w, _ = world_factory()
    w.current_tick = 10
    db.commit()
    execute_tool(db, w, "open_plot_thread", {
        "title": "未还的旧绢", "summary": "黛玉收下了一方旧绢但没还",
    })
    db.refresh(w)
    snap = build_state_snapshot(db, w)
    assert "open_plot_threads" in snap
    assert len(snap["open_plot_threads"]) == 1
    assert snap["open_plot_threads"][0]["title"] == "未还的旧绢"

    out = state_as_prompt(snap)
    assert "未收的剧情钩子" in out
    assert "未还的旧绢" in out


def test_state_snapshot_omits_threads_section_when_none(db, world_factory):
    from app.engine.state import build_state_snapshot, state_as_prompt
    w, _ = world_factory()
    snap = build_state_snapshot(db, w)
    assert "open_plot_threads" not in snap
    out = state_as_prompt(snap)
    assert "未收的剧情钩子" not in out


def test_closed_threads_dont_appear_in_snapshot(db, world_factory):
    from app.engine.state import build_state_snapshot
    w, _ = world_factory()
    o = execute_tool(db, w, "open_plot_thread", {"title": "a", "summary": "b"})
    execute_tool(db, w, "close_plot_thread", {"thread_id": o["id"]})
    snap = build_state_snapshot(db, w)
    assert "open_plot_threads" not in snap  # 全 closed → 段落不出现


def test_open_thread_age_marks_stale(db, world_factory):
    """钩子拖了 5+ tick 时 prompt 应注明'拖了 X tick 了'，让 LLM 注意。"""
    from app.engine.state import build_state_snapshot, state_as_prompt
    w, _ = world_factory()
    w.current_tick = 2
    db.commit()
    execute_tool(db, w, "open_plot_thread", {"title": "t", "summary": "s"})

    w.current_tick = 20
    db.commit()
    snap = build_state_snapshot(db, w)
    out = state_as_prompt(snap)
    assert "拖了" in out  # stale marker


def test_system_prompt_documents_thread_workflow():
    """SYSTEM_PROMPT 应说明钩子的开 / 收工作流 + 修正第 1 条段落清单。"""
    from app.engine.tools import SYSTEM_PROMPT
    assert "open_plot_thread" in SYSTEM_PROMPT
    assert "close_plot_thread" in SYSTEM_PROMPT
    assert "未收的剧情钩子" in SYSTEM_PROMPT  # 第 1 条段落清单已更新
    assert "未解决的因果钩子" not in SYSTEM_PROMPT  # 旧的撒谎措辞已删


# ---- pacing budget ----

def _bind_template(db, w, beats, current_index=0):
    from app.models import WorldTemplate
    import uuid
    t = WorldTemplate(id=f"t_{uuid.uuid4().hex[:8]}", name="x", description="",
                      canonical_outline=[{"beat": b} for b in beats])
    db.add(t); db.commit()
    w.template_id = t.id
    w.outline_progress = {"current_index": current_index, "completed": list(range(current_index))}
    db.commit()


def test_pacing_omitted_when_no_outline_and_no_threads(db, world_factory):
    from app.engine.state import build_state_snapshot, state_as_prompt
    w, _ = world_factory()
    snap = build_state_snapshot(db, w)
    assert "pacing_budget" not in snap
    assert "节奏与预算" not in state_as_prompt(snap)


def test_pacing_untimed_when_threads_but_no_outline(db, world_factory):
    """无大纲但有钩子时仍提示注意，不让钩子无限累积。"""
    from app.engine.state import build_state_snapshot
    w, _ = world_factory()
    execute_tool(db, w, "open_plot_thread", {"title": "t", "summary": "s"})
    snap = build_state_snapshot(db, w)
    assert snap["pacing_budget"]["level"] == "untimed"


def test_pacing_critical_when_threads_exceed_remaining_beats(db, world_factory):
    """剩 1 拍但有 3 条钩子 → critical，prompt 必须出现'禁止开新钩子'。"""
    from app.engine.state import build_state_snapshot, state_as_prompt
    w, _ = world_factory()
    _bind_template(db, w, ["A", "B", "C"], current_index=2)  # 剩 1 拍
    for i in range(3):
        execute_tool(db, w, "open_plot_thread", {"title": f"t{i}", "summary": "s"})
    snap = build_state_snapshot(db, w)
    p = snap["pacing_budget"]
    assert p["level"] == "critical"
    assert p["remaining_beats"] == 1
    assert p["open_threads"] == 3
    out = state_as_prompt(snap)
    assert "节奏与预算" in out
    assert "禁止" in out


def test_pacing_endgame_when_all_done_with_open_threads(db, world_factory):
    from app.engine.state import build_state_snapshot
    w, _ = world_factory()
    _bind_template(db, w, ["A", "B"], current_index=2)  # all_done
    execute_tool(db, w, "open_plot_thread", {"title": "t", "summary": "s"})
    snap = build_state_snapshot(db, w)
    assert snap["pacing_budget"]["level"] == "endgame"


def test_pacing_done_when_all_done_no_threads(db, world_factory):
    from app.engine.state import build_state_snapshot
    w, _ = world_factory()
    _bind_template(db, w, ["A", "B"], current_index=2)
    snap = build_state_snapshot(db, w)
    assert snap["pacing_budget"]["level"] == "done"


def test_pacing_tight_when_late_with_many_threads(db, world_factory):
    """已推 60%+ 且有 3+ 钩子，但还没到剩拍 < 钩子的程度 → tight。"""
    from app.engine.state import build_state_snapshot
    w, _ = world_factory()
    # 10 拍推到第 6 → 60%，剩 4 拍，开 3 条钩子（remaining > threads → 不会 critical）
    _bind_template(db, w, [f"b{i}" for i in range(10)], current_index=6)
    for i in range(3):
        execute_tool(db, w, "open_plot_thread", {"title": f"t{i}", "summary": "s"})
    snap = build_state_snapshot(db, w)
    assert snap["pacing_budget"]["level"] == "tight"
    assert snap["pacing_budget"]["progress_pct"] == 60


def test_pacing_early_empty_nudges_to_open_threads(db, world_factory):
    """早期 0 钩子时给出'埋钩子'提示。"""
    from app.engine.state import build_state_snapshot, state_as_prompt
    w, _ = world_factory()
    _bind_template(db, w, [f"b{i}" for i in range(10)], current_index=1)  # 10%
    snap = build_state_snapshot(db, w)
    assert snap["pacing_budget"]["level"] == "early_empty"
    assert "open_plot_thread" in state_as_prompt(snap)


def test_pacing_comfortable_default(db, world_factory):
    from app.engine.state import build_state_snapshot
    w, _ = world_factory()
    _bind_template(db, w, [f"b{i}" for i in range(10)], current_index=3)  # 30%
    execute_tool(db, w, "open_plot_thread", {"title": "t", "summary": "s"})
    snap = build_state_snapshot(db, w)
    assert snap["pacing_budget"]["level"] == "comfortable"


def test_pacing_section_renders_meta_line(db, world_factory):
    """'状态：' 行应该带上进度/剩拍/钩子数三个字段。"""
    from app.engine.state import build_state_snapshot, state_as_prompt
    w, _ = world_factory()
    _bind_template(db, w, ["a", "b", "c", "d"], current_index=2)
    execute_tool(db, w, "open_plot_thread", {"title": "t", "summary": "s"})
    out = state_as_prompt(build_state_snapshot(db, w))
    assert "状态：" in out
    assert "进度 50%" in out
    assert "剩 2 拍" in out
    assert "未收钩子 1 条" in out
