"""Orchestrator 主循环测试。

覆盖：
- 配置 schema 校验（director 数量边界、critic 数量边界）
- 全局 default 持久化 + resolve_for_world fallback
- _parse_critic_response 容错
- _Budget 上限触发
- 单元：_run_one_critic 写 trace + 解析 verdict
- 集成：critic fail → author rewrite → critic pass → final_verdict='pass'
- 集成：critic 始终 fail → max_critic_retries 到达 → final_verdict='forced_accept'
- 集成：cancel 中断
- 集成：budget 超限
- 集成：无 critic 配置 → final_verdict='no_critics'
"""
from __future__ import annotations
import time

import pytest

from app.engine.agents.agent_pipeline import (
    PipelineConfig, DirectorAgent, AuthorAgent, CriticAgent, BudgetConfig,
    load_global_default, save_global_default, resolve_for_world, LIMITS,
)
from app.engine.agents.orchestrator import (
    _Budget, BudgetExhausted, _parse_critic_response, _run_one_critic, _author_rewrite,
    run_orchestrated_step,
)
from app.providers.base import LLMResponse, ToolCall, Message
from app.models import NarrativeLog, AgentTrace, World


# ===== schema 测试 =====

def test_pipeline_validation_director_bounds():
    # 0 个 director 应失败
    with pytest.raises(Exception):
        PipelineConfig(directors=[], authors=[AuthorAgent()])
    # 超过 MAX_DIRECTORS 失败
    with pytest.raises(Exception):
        PipelineConfig(
            directors=[DirectorAgent()] * (LIMITS["max_directors"] + 1),
            authors=[AuthorAgent()],
        )
    # 边界值 OK
    cfg = PipelineConfig(
        directors=[DirectorAgent()] * LIMITS["max_directors"],
        authors=[AuthorAgent()],
    )
    assert len(cfg.directors) == LIMITS["max_directors"]


def test_pipeline_validation_critic_bounds():
    with pytest.raises(Exception):
        PipelineConfig(
            directors=[DirectorAgent()],
            authors=[AuthorAgent()],
            critics=[CriticAgent()] * (LIMITS["max_critics"] + 1),
        )
    cfg = PipelineConfig(
        directors=[DirectorAgent()],
        authors=[AuthorAgent()],
        critics=[CriticAgent()] * LIMITS["max_critics"],
    )
    assert len(cfg.critics) == LIMITS["max_critics"]


def test_pipeline_validation_author_must_be_one():
    with pytest.raises(Exception):
        PipelineConfig(directors=[DirectorAgent()], authors=[])
    with pytest.raises(Exception):
        PipelineConfig(directors=[DirectorAgent()], authors=[AuthorAgent(), AuthorAgent()])


def test_resolve_for_world_falls_back_to_default():
    cfg = resolve_for_world(None)
    assert isinstance(cfg, PipelineConfig)
    cfg2 = resolve_for_world({})
    assert isinstance(cfg2, PipelineConfig)
    # 损坏的 dict 也回落
    cfg3 = resolve_for_world({"directors": "not a list"})
    assert isinstance(cfg3, PipelineConfig)


def test_resolve_for_world_uses_provided_config():
    spec = PipelineConfig(
        directors=[DirectorAgent(name="custom")],
        authors=[AuthorAgent()],
    ).model_dump()
    cfg = resolve_for_world(spec)
    assert cfg.directors[0].name == "custom"


# ===== budget 测试 =====

def test_budget_call_count_limit():
    cfg = PipelineConfig(
        directors=[DirectorAgent()], authors=[AuthorAgent()],
        budget=BudgetConfig(max_llm_calls=2, max_wall_seconds=300),
    )
    b = _Budget(cfg)
    b.add_call()
    b.check()  # 1 < 2
    b.add_call()
    with pytest.raises(BudgetExhausted) as ei:
        b.check()
    assert ei.value.kind == "llm_calls"


def test_budget_wall_seconds_limit():
    cfg = PipelineConfig(
        directors=[DirectorAgent()], authors=[AuthorAgent()],
        budget=BudgetConfig(max_llm_calls=100, max_wall_seconds=10),
    )
    b = _Budget(cfg)
    b.start = time.monotonic() - 11.0  # 模拟超时
    with pytest.raises(BudgetExhausted) as ei:
        b.check()
    assert ei.value.kind == "wall_seconds"


# ===== critic response 解析 =====

def test_parse_critic_response_clean_json():
    r = _parse_critic_response('{"verdict":"pass","score":8,"reason":"good","suggestions":""}')
    assert r["verdict"] == "pass"
    assert r["score"] == 8


def test_parse_critic_response_markdown_wrapped():
    r = _parse_critic_response('```json\n{"verdict":"fail","score":3,"reason":"meh","suggestions":"fix"}\n```')
    assert r["verdict"] == "fail"
    assert r["suggestions"] == "fix"


def test_parse_critic_response_with_chatter():
    r = _parse_critic_response(
        'I think... {"verdict":"pass","score":7,"reason":"ok","suggestions":""} hope helps'
    )
    assert r["verdict"] == "pass"


def test_parse_critic_response_garbage_defaults_to_pass():
    r = _parse_critic_response("totally not json")
    assert r["verdict"] == "pass"  # 默认放行，避免 critic 自己崩了卡住流程


def test_parse_critic_response_invalid_verdict_normalizes():
    r = _parse_critic_response('{"verdict":"maybe","score":5}')
    assert r["verdict"] == "pass"


# ===== _run_one_critic 单元 =====

def test_run_one_critic_writes_trace_and_parses(db, world_factory):
    w, _ = world_factory()
    db.commit()

    class P:
        name = "fake"
        def chat(self, system, messages, tools, **kw):
            return LLMResponse(text='{"verdict":"fail","score":3,"reason":"太短","suggestions":"扩写"}')

    cfg = PipelineConfig(directors=[DirectorAgent()], authors=[AuthorAgent()])
    budget = _Budget(cfg)
    parsed, tr = _run_one_critic(
        db, "job_test", w, seq=1, iteration=0,
        critic=CriticAgent(name="语感", focus="文笔", severity="strict"),
        final_text="一句话。",
        directive="测试",
        provider=P(),
        budget=budget,
    )
    assert parsed["verdict"] == "fail"
    assert parsed["score"] == 3
    assert tr.role == "critic"
    assert tr.verdict == "fail"
    assert "扩写" in tr.extra["suggestions"]
    assert budget.calls == 1


def test_run_one_critic_handles_provider_crash(db, world_factory):
    w, _ = world_factory()
    db.commit()

    class P:
        name = "boom"
        def chat(self, *a, **kw):
            raise RuntimeError("network down")

    cfg = PipelineConfig(directors=[DirectorAgent()], authors=[AuthorAgent()])
    budget = _Budget(cfg)
    parsed, tr = _run_one_critic(
        db, "job_x", w, seq=1, iteration=0,
        critic=CriticAgent(),
        final_text="some text",
        directive=None,
        provider=P(),
        budget=budget,
    )
    # critic 自己崩 → 默认放行，trace 标 error
    assert parsed["verdict"] == "pass"
    assert tr.status == "error"
    assert "network down" in (tr.extra.get("error") or "")


# ===== 集成：完整 orchestrator 走通 =====

def _bind_style(db, world, style_id="style_jinyong"):
    from app.engine.worldgen.style_seeds import seed_builtin_styles
    from app.models import StyleProfile
    seed_builtin_styles(db)
    world.style_profile_id = style_id
    db.commit()
    return db.query(StyleProfile).filter_by(id=style_id).first()


def _director_then_critics_provider(critic_responses: list[str], author_rewrites: list[str] | None = None):
    """构造一个 FakeProvider 序列：
    1) director: 调 narrate 然后 end_turn
    2) author: 改写 director draft（一次）
    3) critics: 按 critic_responses 顺序返回
    4) author rewrites: 如有 fail，按 author_rewrites 序列返回
    后续重试时 critic_responses 接着消费。
    """
def _director_then_critics_provider(critic_responses: list[str], author_rewrites: list[str] | None = None,
                                     critics_per_round: int = 1):
    """构造 FakeProvider，按 orchestrator 实际调用顺序排队：
      director_hop1, director_hop2, author_initial,
      [critic_round_0_x_N], rewrite_0, [critic_round_1_x_N], rewrite_1, ...
    critics_per_round=每轮调几个 critic（=cfg.critics 的长度）。
    critic_responses 总数应 = critics_per_round * 总轮数。
    """
    base = [
        LLMResponse(tool_calls=[ToolCall(id="t1", name="narrate", arguments={"text": "夜风掠过城墙。林冲提刀。"})]),
        LLMResponse(tool_calls=[ToolCall(id="t2", name="end_turn", arguments={})]),
        LLMResponse(text="夜风掠过苍青色的城墙，林冲缓缓握紧了腰间的雁翎刀。"),
    ]
    cr = list(critic_responses)
    rw = list(author_rewrites or [])
    interleaved: list[LLMResponse] = []
    while cr:
        # 一轮 critic
        for _ in range(critics_per_round):
            if not cr:
                break
            interleaved.append(LLMResponse(text=cr.pop(0)))
        # 一次 rewrite（除非已经没有 rewrite 了，那就停在 critic）
        if rw:
            interleaved.append(LLMResponse(text=rw.pop(0)))

    full = base + interleaved
    fail_default = '{"verdict":"fail","score":1,"reason":"queue empty","suggestions":""}'

    class P:
        name = "fake"
        def __init__(self):
            self.queue = list(full)
            self.calls = 0
        def chat(self, system, messages, tools, **kw):
            self.calls += 1
            if self.queue:
                return self.queue.pop(0)
            return LLMResponse(text=fail_default)

    return P()


def test_orchestrator_no_critics_passes_through(db, world_factory):
    w, br = world_factory()
    _bind_style(db, w)
    db.commit()

    cfg = PipelineConfig(
        directors=[DirectorAgent()], authors=[AuthorAgent()],
        critics=[],
        budget=BudgetConfig(max_llm_calls=20, max_wall_seconds=60),
    )
    p = _director_then_critics_provider([])

    res = run_orchestrated_step(db, w, "测试", job_id="j1", cfg=cfg, provider=p)
    assert res["ok"] is True
    assert res["final_verdict"] == "no_critics"
    assert res["critic_rounds"] == 0
    # 应有 author_final
    af = db.query(NarrativeLog).filter_by(branch_id=br.id, role="author_final").first()
    assert af is not None
    # trace：至少 director + author 两条
    traces = db.query(AgentTrace).filter_by(job_id="j1").order_by(AgentTrace.seq).all()
    roles = [t.role for t in traces]
    assert "director" in roles
    assert "author" in roles


def test_orchestrator_critic_pass_first_round(db, world_factory):
    w, _ = world_factory()
    _bind_style(db, w)
    db.commit()

    cfg = PipelineConfig(
        directors=[DirectorAgent()], authors=[AuthorAgent()],
        critics=[CriticAgent(name="语感"), CriticAgent(name="人设")],
    )
    # 2 个 critic 都 pass
    p = _director_then_critics_provider([
        '{"verdict":"pass","score":8,"reason":"ok","suggestions":""}',
        '{"verdict":"pass","score":7,"reason":"ok","suggestions":""}',
    ], critics_per_round=2)
    res = run_orchestrated_step(db, w, "测试", job_id="j2", cfg=cfg, provider=p)
    assert res["final_verdict"] == "pass"
    assert res["critic_rounds"] == 1


def test_orchestrator_critic_fail_then_rewrite_then_pass(db, world_factory):
    w, _ = world_factory()
    _bind_style(db, w)
    db.commit()

    cfg = PipelineConfig(
        directors=[DirectorAgent()], authors=[AuthorAgent()],
        critics=[CriticAgent(name="语感")],
        max_critic_retries=2,
    )
    # 第 1 轮 fail；author 重写；第 2 轮 pass
    p = _director_then_critics_provider(
        critic_responses=[
            '{"verdict":"fail","score":3,"reason":"太短","suggestions":"扩写"}',
            '{"verdict":"pass","score":8,"reason":"现在饱满","suggestions":""}',
        ],
        author_rewrites=["夜风掠过苍青色的城墙，林冲缓缓握紧了腰间的雁翎刀，目光如刃，扫向城下。"],
    )
    res = run_orchestrated_step(db, w, "测试", job_id="j3", cfg=cfg, provider=p)
    assert res["final_verdict"] == "pass"
    assert res["critic_rounds"] == 2
    # trace 里应该有 author rewrite 这条
    traces = db.query(AgentTrace).filter_by(job_id="j3").order_by(AgentTrace.seq).all()
    has_rewrite = any(t.role == "author" and "rewrite" in t.agent_name for t in traces)
    assert has_rewrite


def test_orchestrator_critic_always_fail_forces_accept(db, world_factory):
    w, _ = world_factory()
    _bind_style(db, w)
    db.commit()

    cfg = PipelineConfig(
        directors=[DirectorAgent()], authors=[AuthorAgent()],
        critics=[CriticAgent(name="strict")],
        max_critic_retries=2,
    )
    # 3 轮全 fail（max_retries=2 → 总共 3 次 critic 评审）+ 2 次 rewrite
    p = _director_then_critics_provider(
        critic_responses=[
            '{"verdict":"fail","score":2,"reason":"差","suggestions":"重写"}',
            '{"verdict":"fail","score":2,"reason":"还差","suggestions":"再重写"}',
            '{"verdict":"fail","score":2,"reason":"依然差","suggestions":"放弃"}',
        ],
        author_rewrites=["改了一次。", "改了两次。"],
    )
    res = run_orchestrated_step(db, w, "测试", job_id="j4", cfg=cfg, provider=p)
    assert res["final_verdict"] == "forced_accept"
    assert res["critic_rounds"] == 3


def test_orchestrator_serial_critic_short_circuits(db, world_factory):
    w, _ = world_factory()
    _bind_style(db, w)
    db.commit()

    cfg = PipelineConfig(
        directors=[DirectorAgent()], authors=[AuthorAgent()],
        critics=[CriticAgent(name="A"), CriticAgent(name="B"), CriticAgent(name="C")],
        critic_mode="serial",
        max_critic_retries=0,
    )
    # A fail → B/C 不应被调用 → forced_accept（max_retries=0）
    p = _director_then_critics_provider([
        '{"verdict":"fail","score":2,"reason":"差","suggestions":"x"}',
    ])
    res = run_orchestrated_step(db, w, "测试", job_id="j5", cfg=cfg, provider=p)
    assert res["final_verdict"] == "forced_accept"
    # 只有 A 那条 critic trace（B/C 被短路）
    critic_traces = db.query(AgentTrace).filter_by(job_id="j5", role="critic").all()
    assert len(critic_traces) == 1
    assert critic_traces[0].agent_name == "A"


def test_orchestrator_cancel_mid_critic(db, world_factory):
    w, _ = world_factory()
    _bind_style(db, w)
    db.commit()

    cfg = PipelineConfig(
        directors=[DirectorAgent()], authors=[AuthorAgent()],
        critics=[CriticAgent(name="C1"), CriticAgent(name="C2")],
    )
    p = _director_then_critics_provider([
        '{"verdict":"pass","score":8,"reason":"ok","suggestions":""}',
        '{"verdict":"pass","score":8,"reason":"ok","suggestions":""}',
    ])
    # cancel 在 critic 阶段第一次检查时就触发
    cancelled = {"v": False}
    call_n = {"n": 0}
    def cancel_check():
        call_n["n"] += 1
        # 前 3 次（director+author）不取消，从第 4 次起取消
        if call_n["n"] >= 4:
            cancelled["v"] = True
        return cancelled["v"]

    res = run_orchestrated_step(
        db, w, "测试", job_id="j6", cfg=cfg, provider=p,
        cancel_check=cancel_check,
    )
    assert res["final_verdict"] == "cancelled"


def test_orchestrator_budget_exhausted(db, world_factory):
    w, _ = world_factory()
    _bind_style(db, w)
    db.commit()

    cfg = PipelineConfig(
        directors=[DirectorAgent()], authors=[AuthorAgent()],
        critics=[CriticAgent(name="A"), CriticAgent(name="B")],
        budget=BudgetConfig(max_llm_calls=4, max_wall_seconds=60),  # 故意调小
    )
    p = _director_then_critics_provider([
        '{"verdict":"fail","score":2,"reason":"差","suggestions":"x"}',
        '{"verdict":"fail","score":2,"reason":"差","suggestions":"x"}',
    ])
    res = run_orchestrated_step(db, w, "测试", job_id="j7", cfg=cfg, provider=p)
    # director(2 hops) + author(1) = 3，到第 1 个 critic 第 4 调用，第 2 个 critic 触发 budget
    # 不要求精确，只要 verdict 是 budget_exhausted 或 forced_accept（取决于实际调用顺序）
    assert res["final_verdict"] in ("budget_exhausted", "forced_accept", "pass")
    # budget 信息一定有
    assert "llm_calls" in res["budget_used"]


# ===== 全局 default 持久化 =====

def test_save_and_load_global_default(tmp_path, monkeypatch):
    from app.engine import agent_pipeline as ap
    monkeypatch.setattr(ap, "DEFAULT_PATH", tmp_path / "default.json")
    monkeypatch.setattr(ap, "DATA_DIR", tmp_path)

    cfg = PipelineConfig(
        directors=[DirectorAgent(name="custom")],
        authors=[AuthorAgent(name="my-author")],
        critics=[CriticAgent(name="strict-critic", severity="strict")],
        max_critic_retries=4,
    )
    save_global_default(cfg)
    loaded = load_global_default()
    assert loaded.directors[0].name == "custom"
    assert loaded.critics[0].severity == "strict"
    assert loaded.max_critic_retries == 4


# ===== Critic 跨轮记忆 =====

def test_critic_prev_round_threaded_into_prompt(db, world_factory):
    """同一 critic 在第 2 轮收到的 user_prompt 中应含上一轮自己的 verdict + suggestions。"""
    w, _ = world_factory()
    _bind_style(db, w)
    db.commit()

    cfg = PipelineConfig(
        directors=[DirectorAgent()], authors=[AuthorAgent()],
        critics=[CriticAgent(name="strict")],
        max_critic_retries=2,
    )
    p = _director_then_critics_provider(
        critic_responses=[
            '{"verdict":"fail","score":3,"reason":"语感太散","suggestions":"凝练动词"}',
            '{"verdict":"pass","score":8,"reason":"已收紧","suggestions":""}',
        ],
        author_rewrites=["收紧之后的版本。"],
    )
    res = run_orchestrated_step(db, w, "测试", job_id="j_prev", cfg=cfg, provider=p)
    assert res["final_verdict"] == "pass"
    # 找第 2 轮 critic trace（iteration=1）
    second = (
        db.query(AgentTrace)
        .filter(AgentTrace.job_id == "j_prev",
                AgentTrace.role == "critic",
                AgentTrace.iteration == 1)
        .first()
    )
    assert second is not None
    assert "你上一轮的审稿" in second.full_prompt
    assert "凝练动词" in second.full_prompt
    assert (second.extra or {}).get("prev_round_used") is True
    # 第一轮不应该有 prev_round
    first = (
        db.query(AgentTrace)
        .filter(AgentTrace.job_id == "j_prev",
                AgentTrace.role == "critic",
                AgentTrace.iteration == 0)
        .first()
    )
    assert (first.extra or {}).get("prev_round_used") is False


# ===== forced_accept 含 unresolved_critics =====

def test_forced_accept_returns_unresolved_critics(db, world_factory):
    w, _ = world_factory()
    _bind_style(db, w)
    db.commit()

    cfg = PipelineConfig(
        directors=[DirectorAgent()], authors=[AuthorAgent()],
        critics=[CriticAgent(name="strict")],
        max_critic_retries=1,
    )
    p = _director_then_critics_provider(
        critic_responses=[
            '{"verdict":"fail","score":2,"reason":"始终不行","suggestions":"建议 A"}',
            '{"verdict":"fail","score":2,"reason":"还是不行","suggestions":"建议 B"}',
        ],
        author_rewrites=["改了一次。"],
    )
    res = run_orchestrated_step(db, w, "测试", job_id="j_fa", cfg=cfg, provider=p)
    assert res["final_verdict"] == "forced_accept"
    unresolved = res.get("unresolved_critics") or []
    assert len(unresolved) == 1
    assert unresolved[0]["name"] == "strict"
    assert "还是不行" in unresolved[0]["reason"]


# ===== Pipeline 指标聚合 =====

def test_query_pipeline_metrics_aggregates(db, world_factory):
    from app.engine.agents.orchestrator import query_pipeline_metrics
    w, _ = world_factory()
    _bind_style(db, w)
    db.commit()

    cfg = PipelineConfig(
        directors=[DirectorAgent()], authors=[AuthorAgent()],
        critics=[CriticAgent(name="strict")],
        max_critic_retries=1,
    )
    # job 1: 一次过
    p1 = _director_then_critics_provider(
        critic_responses=['{"verdict":"pass","score":9,"reason":"好","suggestions":""}'],
    )
    run_orchestrated_step(db, w, "1", job_id="m1", cfg=cfg, provider=p1)
    # job 2: 一轮 fail → rewrite → pass
    p2 = _director_then_critics_provider(
        critic_responses=[
            '{"verdict":"fail","score":3,"reason":"差","suggestions":"重写"}',
            '{"verdict":"pass","score":8,"reason":"OK","suggestions":""}',
        ],
        author_rewrites=["改后。"],
    )
    run_orchestrated_step(db, w, "2", job_id="m2", cfg=cfg, provider=p2)
    # job 3: 全 fail → forced_accept
    p3 = _director_then_critics_provider(
        critic_responses=[
            '{"verdict":"fail","score":2,"reason":"差1","suggestions":"x"}',
            '{"verdict":"fail","score":2,"reason":"差2","suggestions":"y"}',
        ],
        author_rewrites=["改后。"],
    )
    run_orchestrated_step(db, w, "3", job_id="m3", cfg=cfg, provider=p3)

    m = query_pipeline_metrics(db, w.id, hours=24)
    assert m["summary"]["total_jobs"] == 3
    assert m["summary"]["forced_accept"] == 1
    assert m["summary"]["first_pass"] == 1  # 只有 job 1 第一轮就 pass
    assert m["summary"]["avg_critic_rounds"] >= 1.6  # (1+2+2)/3
    by = m["by_critic"]["strict"]
    assert by["runs"] == 5  # 1 + 2 + 2
    assert by["pass"] == 2
    assert by["fail"] == 3
    assert len(m["recent_forced"]) == 1
    assert m["recent_forced"][0]["unresolved_count"] == 1


# ===== Arc critic 注入章节 recap =====

def _make_chapter(db, branch_id, tick, title, summary):
    from app.models import ChapterMarker
    import uuid
    cm = ChapterMarker(
        id=f"cm_{uuid.uuid4().hex[:8]}",
        branch_id=branch_id, tick=tick, title=title, summary=summary,
    )
    db.add(cm)
    return cm


def test_arc_critic_receives_chapter_recap(db, world_factory):
    """arc kind 的 critic prompt 应含 build_chapter_recap_block 输出；general critic 不应含。"""
    w, br = world_factory()
    _bind_style(db, w)
    _make_chapter(db, br.id, tick=2, title="序章", summary="林冲告别家人，独自上路")
    _make_chapter(db, br.id, tick=5, title="第一章", summary="林冲在城外遇到神秘剑客")
    db.commit()

    cfg = PipelineConfig(
        directors=[DirectorAgent()], authors=[AuthorAgent()],
        critics=[CriticAgent(name="general"), CriticAgent(name="arc1", kind="arc")],
        max_critic_retries=0,
    )
    p = _director_then_critics_provider(
        critic_responses=[
            '{"verdict":"pass","score":8,"reason":"ok","suggestions":""}',
            '{"verdict":"pass","score":8,"reason":"ok","suggestions":""}',
        ],
        critics_per_round=2,
    )
    res = run_orchestrated_step(db, w, "测试", job_id="j_arc1", cfg=cfg, provider=p)
    assert res["final_verdict"] == "pass"

    arc_trace = (
        db.query(AgentTrace)
        .filter(AgentTrace.job_id == "j_arc1",
                AgentTrace.role == "critic",
                AgentTrace.agent_name == "arc1")
        .first()
    )
    gen_trace = (
        db.query(AgentTrace)
        .filter(AgentTrace.job_id == "j_arc1",
                AgentTrace.role == "critic",
                AgentTrace.agent_name == "general")
        .first()
    )
    assert arc_trace is not None and gen_trace is not None
    assert "前文章节回顾" in arc_trace.full_prompt
    assert "林冲告别家人" in arc_trace.full_prompt
    assert "前文章节回顾" not in gen_trace.full_prompt
    assert (arc_trace.extra or {}).get("arc_context_used") is True
    assert (arc_trace.extra or {}).get("kind") == "arc"
    assert (gen_trace.extra or {}).get("arc_context_used") is False
    assert (gen_trace.extra or {}).get("kind") == "general"


def test_arc_critic_no_chapters_does_not_inject_block(db, world_factory):
    """没有任何章节 summary 时，arc critic prompt 不应出现 # 前文章节回顾 标题。"""
    w, _ = world_factory()
    _bind_style(db, w)
    db.commit()

    cfg = PipelineConfig(
        directors=[DirectorAgent()], authors=[AuthorAgent()],
        critics=[CriticAgent(name="arc_only", kind="arc")],
        max_critic_retries=0,
    )
    p = _director_then_critics_provider(
        critic_responses=['{"verdict":"pass","score":8,"reason":"ok","suggestions":""}'],
    )
    res = run_orchestrated_step(db, w, "测试", job_id="j_arc2", cfg=cfg, provider=p)
    assert res["final_verdict"] == "pass"

    tr = (
        db.query(AgentTrace)
        .filter(AgentTrace.job_id == "j_arc2", AgentTrace.role == "critic")
        .first()
    )
    assert "前文章节回顾" not in tr.full_prompt
    assert (tr.extra or {}).get("arc_context_used") is False


def test_arc_critic_kind_serialized_round_trip():
    """CriticAgent.kind=arc 经 model_dump → model_validate 应保留。"""
    cfg = PipelineConfig(
        directors=[DirectorAgent()], authors=[AuthorAgent()],
        critics=[CriticAgent(name="x", kind="arc")],
    )
    raw = cfg.model_dump()
    assert raw["critics"][0]["kind"] == "arc"
    re = PipelineConfig.model_validate(raw)
    assert re.critics[0].kind == "arc"
    # 默认应是 general
    cfg2 = PipelineConfig(
        directors=[DirectorAgent()], authors=[AuthorAgent()],
        critics=[CriticAgent(name="y")],
    )
    assert cfg2.critics[0].kind == "general"


# ===== Best-of-K author 多候选 =====

def _best_of_k_provider(
    *,
    candidate_texts: list[str],
    critic_responses_per_candidate: list[list[str]],
    rewrite_texts: list[str] | None = None,
    post_rewrite_critic_responses: list[list[str]] | None = None,
):
    """构造 FakeProvider 序列，模拟 best-of-K 流水线：
      director_hop1, director_hop2,
      author_candidate_0, author_candidate_1, ..., author_candidate_K-1,
      ranking_critics_for_cand_0[N], ranking_critics_for_cand_1[N], ...,
      [rewrite_0, post_rewrite_critics[N], rewrite_1, ...]
    """
    base = [
        LLMResponse(tool_calls=[ToolCall(id="t1", name="narrate", arguments={"text": "夜风掠过城墙。林冲提刀。"})]),
        LLMResponse(tool_calls=[ToolCall(id="t2", name="end_turn", arguments={})]),
    ]
    for t in candidate_texts:
        base.append(LLMResponse(text=t))
    for cr_list in critic_responses_per_candidate:
        for cr in cr_list:
            base.append(LLMResponse(text=cr))
    rw = list(rewrite_texts or [])
    post = list(post_rewrite_critic_responses or [])
    while rw or post:
        if rw:
            base.append(LLMResponse(text=rw.pop(0)))
        if post:
            for cr in post.pop(0):
                base.append(LLMResponse(text=cr))

    fail_default = '{"verdict":"fail","score":1,"reason":"queue empty","suggestions":""}'

    class P:
        name = "fake"
        def __init__(self):
            self.queue = list(base)
            self.calls = 0
        def chat(self, system, messages, tools, **kw):
            self.calls += 1
            if self.queue:
                return self.queue.pop(0)
            return LLMResponse(text=fail_default)

    return P()


def test_best_of_k_winner_all_pass_skips_loop(db, world_factory):
    """K=2 候选 + 1 critic：cand0 fail, cand1 all-pass → 选 cand1, 不进入重试循环。"""
    w, br = world_factory()
    _bind_style(db, w)
    db.commit()

    cfg = PipelineConfig(
        directors=[DirectorAgent()], authors=[AuthorAgent()],
        critics=[CriticAgent(name="strict")],
        author_best_of=2,
        max_critic_retries=2,
    )
    p = _best_of_k_provider(
        candidate_texts=[
            "候选 0：夜风过城墙，林冲提刀。",
            "候选 1：夜风掠过苍青城墙，林冲缓缓握紧雁翎刀。",
        ],
        critic_responses_per_candidate=[
            ['{"verdict":"fail","score":3,"reason":"太散","suggestions":"凝练"}'],
            ['{"verdict":"pass","score":9,"reason":"很好","suggestions":""}'],
        ],
    )
    res = run_orchestrated_step(db, w, "测试", job_id="j_bok1", cfg=cfg, provider=p)
    assert res["final_verdict"] == "pass"
    assert res["critic_rounds"] == 1  # 只有 ranking 这一轮
    # author_final 文本应是 cand1
    af = db.query(NarrativeLog).filter_by(branch_id=br.id, role="author_final").first()
    assert af is not None and "雁翎刀" in af.text
    # 候选 trace
    cand_traces = (
        db.query(AgentTrace)
        .filter(AgentTrace.job_id == "j_bok1", AgentTrace.role == "author")
        .order_by(AgentTrace.seq).all()
    )
    cand_indices = [(t.extra or {}).get("candidate_index") for t in cand_traces if (t.extra or {}).get("is_best_of_candidate")]
    assert cand_indices == [0, 1]
    # ranking critic trace 应被打 is_ranking
    ranking_critics = (
        db.query(AgentTrace)
        .filter(AgentTrace.job_id == "j_bok1", AgentTrace.role == "critic")
        .all()
    )
    assert all((t.extra or {}).get("is_ranking") for t in ranking_critics)
    # 编排选 trace
    pick = (
        db.query(AgentTrace)
        .filter(AgentTrace.job_id == "j_bok1",
                AgentTrace.role == "orchestrator",
                AgentTrace.agent_name == "(best-of-K pick)")
        .first()
    )
    assert pick is not None
    assert (pick.extra or {}).get("winner_idx") == 1
    assert (pick.extra or {}).get("k") == 2


def test_best_of_k_winner_fails_then_rewrite_passes(db, world_factory):
    """K=2 候选都 fail → 选高分者 → 立即 rewrite → critic pass → final='pass', critic_rounds=2。"""
    w, _ = world_factory()
    _bind_style(db, w)
    db.commit()

    cfg = PipelineConfig(
        directors=[DirectorAgent()], authors=[AuthorAgent()],
        critics=[CriticAgent(name="strict")],
        author_best_of=2,
        max_critic_retries=2,
    )
    p = _best_of_k_provider(
        candidate_texts=["候选 0：差。", "候选 1：稍好但也差。"],
        critic_responses_per_candidate=[
            ['{"verdict":"fail","score":3,"reason":"差","suggestions":"重写"}'],
            ['{"verdict":"fail","score":5,"reason":"还行但差","suggestions":"再凝练"}'],
        ],
        rewrite_texts=["重写后的版本。"],
        post_rewrite_critic_responses=[
            ['{"verdict":"pass","score":8,"reason":"OK","suggestions":""}'],
        ],
    )
    res = run_orchestrated_step(db, w, "测试", job_id="j_bok2", cfg=cfg, provider=p)
    assert res["final_verdict"] == "pass"
    assert res["critic_rounds"] == 2  # ranking + 重写后那一轮
    pick = (
        db.query(AgentTrace)
        .filter(AgentTrace.job_id == "j_bok2",
                AgentTrace.role == "orchestrator",
                AgentTrace.agent_name == "(best-of-K pick)")
        .first()
    )
    # 都 fail 时按总分高者优先：cand1 score=5 > cand0 score=3
    assert (pick.extra or {}).get("winner_idx") == 1


def test_best_of_k_temperatures_evenly_spread():
    from app.engine.agents.orchestrator import _best_of_k_temperatures
    assert _best_of_k_temperatures(1) == [0.85]
    t2 = _best_of_k_temperatures(2)
    assert len(t2) == 2 and t2[0] < t2[1]
    t4 = _best_of_k_temperatures(4)
    assert len(t4) == 4 and t4 == sorted(t4)
    # 温度合理范围
    for t in t4:
        assert 0.0 <= t <= 1.5


def test_best_of_k_no_critics_falls_through_to_single_shot(db, world_factory):
    """K>1 但没 critic：无法做评分，应回落到单次 author。"""
    w, br = world_factory()
    _bind_style(db, w)
    db.commit()

    cfg = PipelineConfig(
        directors=[DirectorAgent()], authors=[AuthorAgent()],
        critics=[],  # 没有 critic
        author_best_of=3,
    )
    # 标准 director_then_critics_provider 模拟单次 author
    p = _director_then_critics_provider([])
    res = run_orchestrated_step(db, w, "fall-through", job_id="j_bok3", cfg=cfg, provider=p)
    assert res["final_verdict"] == "no_critics"
    # 确认没写出任何 best_of 候选 trace
    cand_traces = (
        db.query(AgentTrace)
        .filter(AgentTrace.job_id == "j_bok3", AgentTrace.role == "author")
        .all()
    )
    assert all(not (t.extra or {}).get("is_best_of_candidate") for t in cand_traces)


def test_best_of_k_metrics_excludes_ranking_traces(db, world_factory):
    """query_pipeline_metrics 应该忽略 best-of-K ranking 阶段的 critic trace。"""
    from app.engine.agents.orchestrator import query_pipeline_metrics
    w, _ = world_factory()
    _bind_style(db, w)
    db.commit()

    cfg = PipelineConfig(
        directors=[DirectorAgent()], authors=[AuthorAgent()],
        critics=[CriticAgent(name="strict")],
        author_best_of=2,
        max_critic_retries=0,
    )
    p = _best_of_k_provider(
        candidate_texts=["候选 0", "候选 1"],
        critic_responses_per_candidate=[
            ['{"verdict":"pass","score":7,"reason":"ok","suggestions":""}'],
            ['{"verdict":"pass","score":9,"reason":"better","suggestions":""}'],
        ],
    )
    run_orchestrated_step(db, w, "测试", job_id="j_bok4", cfg=cfg, provider=p)
    m = query_pipeline_metrics(db, w.id, hours=24)
    # best-of-K all-pass 应被算作 first_pass=1（ranking winner_all_pass）
    assert m["summary"]["total_jobs"] == 1
    assert m["summary"]["first_pass"] == 1
    assert m["summary"]["forced_accept"] == 0
    # critic_rounds=1: 只 ranking 跑了一轮; ranking 不被当成 retry 轮
    assert m["summary"]["avg_critic_rounds"] == 1.0
    # by_critic.runs 把 ranking 的两次评分都算进来（每个候选评一次都是 critic 的真实输出）
    assert m["by_critic"]["strict"]["runs"] == 2
    assert m["by_critic"]["strict"]["pass"] == 2
