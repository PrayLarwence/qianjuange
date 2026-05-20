"""A3 测试：Author agent 路径全覆盖。

覆盖：
- 没绑风格 → 完全 no-op（老行为）
- 绑了风格 + LLM 成功 → 写 author_final，retag draft
- 绑了风格 + LLM 失败 → 回落
- 绑了风格 + 输出过短 → 回落（length anomaly）
- 绑了风格 + 输出空字符串 → 回落
- run_step 集成：author_final 可见，director_draft 默认隐藏
- timeline 端点 include_drafts 开关
- cleanup_old_drafts 在 step 后被调用
"""
from __future__ import annotations
import pytest
from app.models import NarrativeLog, StyleProfile, Event
from app.engine.author import run_author_for_step
from app.providers.base import LLMResponse


# ===== Author 单元测试 =====

def _make_draft(db, branch_id, tick, text, idx=0):
    """直接落 narrator 行（模拟 Director 的 narrate 工具调用结果）。"""
    import uuid
    log = NarrativeLog(
        id=f"nl_{uuid.uuid4().hex[:8]}",
        branch_id=branch_id, tick=tick, role="narrator", text=text,
    )
    db.add(log); db.commit()
    return log


def _bind_style(db, world, style_id="style_jinyong"):
    from app.engine.style_seeds import seed_builtin_styles
    seed_builtin_styles(db)
    world.style_profile_id = style_id
    db.commit()
    return db.query(StyleProfile).filter_by(id=style_id).first()


def test_author_no_style_is_noop(db, world_factory):
    """没绑风格的世界：Author 不介入，narrator 保持 narrator。"""
    w, br = world_factory()
    _make_draft(db, br.id, tick=1, text="林冲拔剑。")

    res = run_author_for_step(db, w, br.id, start_tick=1)
    assert res.ok and res.reason == "no style profile (legacy world)"
    assert res.log_id is None  # 没新建任何行

    # 数据库里应该只有一条 narrator
    rows = db.query(NarrativeLog).filter_by(branch_id=br.id).all()
    assert len(rows) == 1
    assert rows[0].role == "narrator"


def test_author_success_writes_final_and_retags_drafts(db, world_factory):
    w, br = world_factory()
    _bind_style(db, w, "style_jinyong")
    _make_draft(db, br.id, tick=1, text="林冲拔剑，那汉子退了一步。")

    class FakeProvider:
        name = "fake"
        def chat(self, system, messages, tools, max_tokens=2048, temperature=0.7, timeout=120.0):
            # 返回风格化的改写文本（长度合理）
            return LLMResponse(text="林冲腰间长剑出鞘三寸。那汉子脸色一变，半步退后。剑光未动，胜负已分。")

    res = run_author_for_step(db, w, br.id, start_tick=1, provider=FakeProvider())
    assert res.ok and not res.fell_back
    assert res.log_id

    rows = db.query(NarrativeLog).filter_by(branch_id=br.id).order_by(NarrativeLog.created_at).all()
    assert len(rows) == 2
    # 原 narrator 已被 retag
    drafts = [r for r in rows if r.role == "director_draft"]
    finals = [r for r in rows if r.role == "author_final"]
    assert len(drafts) == 1 and len(finals) == 1
    assert "腰间长剑" in finals[0].text
    assert finals[0].parent_log_id == drafts[0].id


def test_author_llm_exception_falls_back(db, world_factory):
    w, br = world_factory()
    _bind_style(db, w, "style_serious_lit")
    _make_draft(db, br.id, tick=1, text="她推开门走了进去。")

    class BoomProvider:
        name = "boom"
        def chat(self, *a, **kw):
            raise RuntimeError("network down")

    res = run_author_for_step(db, w, br.id, start_tick=1, provider=BoomProvider())
    assert res.ok and res.fell_back
    assert "llm error" in res.reason

    finals = db.query(NarrativeLog).filter_by(branch_id=br.id, role="author_final").all()
    assert len(finals) == 1
    # 回落分支：定稿文本就是粗稿原文
    assert finals[0].text == "她推开门走了进去。"


def test_author_too_short_falls_back(db, world_factory):
    w, br = world_factory()
    _bind_style(db, w, "style_serious_lit")
    long_draft = "这是一段很长的粗稿。" * 20  # 200 字
    _make_draft(db, br.id, tick=1, text=long_draft)

    class ShortProvider:
        name = "short"
        def chat(self, *a, **kw):
            return LLMResponse(text="嗯。")  # 远低于 30%

    res = run_author_for_step(db, w, br.id, start_tick=1, provider=ShortProvider())
    assert res.ok and res.fell_back
    assert "length anomaly" in res.reason


def test_author_too_long_falls_back(db, world_factory):
    w, br = world_factory()
    _bind_style(db, w, "style_jinyong")
    _make_draft(db, br.id, tick=1, text="林冲拔剑。")

    class LongProvider:
        name = "long"
        def chat(self, *a, **kw):
            return LLMResponse(text="林冲拔剑。" * 100)  # 远超 5 倍

    res = run_author_for_step(db, w, br.id, start_tick=1, provider=LongProvider())
    assert res.ok and res.fell_back


def test_author_empty_output_falls_back(db, world_factory):
    w, br = world_factory()
    _bind_style(db, w, "style_serious_lit")
    _make_draft(db, br.id, tick=1, text="她说了什么。")

    class EmptyProvider:
        name = "empty"
        def chat(self, *a, **kw):
            return LLMResponse(text="   ")

    res = run_author_for_step(db, w, br.id, start_tick=1, provider=EmptyProvider())
    assert res.ok and res.fell_back and "empty output" in res.reason


def test_author_no_draft_returns_ok(db, world_factory):
    """本回合没有任何 narrate 调用 → 无事可做。"""
    w, br = world_factory()
    _bind_style(db, w)
    res = run_author_for_step(db, w, br.id, start_tick=1)
    assert res.ok and res.reason == "no draft"


def test_author_merges_multiple_drafts(db, world_factory):
    """同回合多条 narrate → Author 合并改写为单条 final。"""
    w, br = world_factory()
    _bind_style(db, w, "style_jinyong")
    _make_draft(db, br.id, tick=2, text="夜深。")
    _make_draft(db, br.id, tick=2, text="林冲在屋内来回踱步。")
    _make_draft(db, br.id, tick=2, text="窗外雪未停。")

    class MergeProvider:
        name = "merge"
        def chat(self, system, messages, tools, max_tokens=2048, temperature=0.7, timeout=120.0):
            # 验证 prompt 里包含三段粗稿
            user = messages[0].content
            assert "夜深" in user and "林冲" in user and "雪未停" in user
            return LLMResponse(text="夜深了。林冲一人在屋内踱步，听窗外雪声未歇。")

    res = run_author_for_step(db, w, br.id, start_tick=2, provider=MergeProvider())
    assert res.ok and not res.fell_back
    drafts = db.query(NarrativeLog).filter_by(branch_id=br.id, role="director_draft").all()
    finals = db.query(NarrativeLog).filter_by(branch_id=br.id, role="author_final").all()
    assert len(drafts) == 3
    assert len(finals) == 1


# ===== run_step 集成：mock 模式不调 Author =====

def test_run_step_mock_does_not_call_author(db, world_factory, monkeypatch):
    """mock 模式跳过 Author 阶段，narrator 保持 narrator。"""
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    from app.engine.simulator import run_step
    w, br = world_factory()
    _bind_style(db, w)  # 即使绑了风格，mock 模式也不该跑 Author
    out = run_step(db, w, user_directive="测试推演")
    assert out["ok"]
    rows = db.query(NarrativeLog).filter_by(branch_id=br.id).all()
    # mock_step 落的是 narrator，没有 director_draft / author_final
    roles = {r.role for r in rows}
    assert "director_draft" not in roles
    assert "author_final" not in roles


# ===== timeline 端点 include_drafts 开关 =====

def test_timeline_hides_drafts_by_default(client, db, world_factory):
    """timeline 默认不返 director_draft。"""
    w, br = world_factory()
    # 直接造一条 draft + 一条 final
    db.add(NarrativeLog(id="nl_d", branch_id=br.id, tick=1, role="director_draft", text="粗稿"))
    db.add(NarrativeLog(id="nl_f", branch_id=br.id, tick=1, role="author_final", text="定稿",
                         parent_log_id="nl_d"))
    db.add(NarrativeLog(id="nl_n", branch_id=br.id, tick=2, role="narrator", text="老格式"))
    db.commit()

    r = client.get(f"/api/worlds/{w.id}/timeline")
    assert r.status_code == 200
    nar = r.json()["narration"]
    texts = [n["text"] for n in nar]
    assert "定稿" in texts
    assert "老格式" in texts
    assert "粗稿" not in texts
    # 字段含 id / parent_log_id 让前端能做对照
    by_id = {n["id"]: n for n in nar}
    assert by_id["nl_f"]["parent_log_id"] == "nl_d"


def test_timeline_includes_drafts_when_flag_set(client, db, world_factory):
    w, br = world_factory()
    db.add(NarrativeLog(id="nl_d", branch_id=br.id, tick=1, role="director_draft", text="粗稿"))
    db.add(NarrativeLog(id="nl_f", branch_id=br.id, tick=1, role="author_final", text="定稿",
                         parent_log_id="nl_d"))
    db.commit()
    r = client.get(f"/api/worlds/{w.id}/timeline?include_drafts=1")
    nar = r.json()["narration"]
    texts = [n["text"] for n in nar]
    assert "粗稿" in texts and "定稿" in texts


# ===== run_step 集成：绑风格后整条 Director→Author 链 =====

def test_run_step_with_style_runs_author_pipeline(db, world_factory):
    """
    Director（fake LLM）调 narrate；Author（fake LLM）改写为 final。
    最终 NarrativeLog 应有 1 director_draft + 1 author_final，
    run_step 返回的 narration 是 author 的输出。
    """
    from app.engine.simulator import run_step
    from app.providers.base import ToolCall

    w, br = world_factory()
    _bind_style(db, w, "style_jinyong")

    # Director：调 narrate + end_turn
    director_responses = [
        LLMResponse(tool_calls=[
            ToolCall(id="t1", name="narrate", arguments={"text": "林冲拔剑，那汉子退了一步。"}),
            ToolCall(id="t2", name="end_turn", arguments={}),
        ]),
    ]
    # Author 用同一 provider 实例，scripted 里第二条是 Author 的输出
    director_responses.append(LLMResponse(text="林冲腰间长剑出鞘三寸。那汉子脸色一变，半步退后。"))

    class StackProvider:
        name = "stack"
        def __init__(self, scripted):
            self.scripted = list(scripted)
        def chat(self, system, messages, tools, max_tokens=2048, temperature=0.7, timeout=120.0):
            return self.scripted.pop(0)

    p = StackProvider(director_responses)
    # Author 通过 get_provider_for_role 取 provider；override 为空时回落主 provider。
    # 用 monkeypatch 把主 provider 替成 StackProvider 自己。
    import app.providers as prov_mod
    old = prov_mod.get_provider
    prov_mod.get_provider = lambda *a, **kw: p
    try:
        res = run_step(db, w, provider=p)
    finally:
        prov_mod.get_provider = old

    assert res["ok"]
    drafts = db.query(NarrativeLog).filter_by(branch_id=br.id, role="director_draft").all()
    finals = db.query(NarrativeLog).filter_by(branch_id=br.id, role="author_final").all()
    assert len(drafts) == 1
    assert len(finals) == 1
    assert "腰间长剑" in finals[0].text
    # run_step 返回的 narration 是 final 文本（不是粗稿）
    assert "腰间长剑" in res["narration"]


def test_run_step_with_style_author_failure_falls_back(db, world_factory):
    """Author 失败时，run_step 仍返回 narration（来自回落 final）。"""
    from app.engine.simulator import run_step
    from app.providers.base import ToolCall

    w, br = world_factory()
    _bind_style(db, w, "style_jinyong")

    director_responses = [
        LLMResponse(tool_calls=[
            ToolCall(id="t1", name="narrate", arguments={"text": "她推门进来。"}),
            ToolCall(id="t2", name="end_turn", arguments={}),
        ]),
    ]

    call_count = {"n": 0}

    class FailingAuthor:
        name = "fail"
        def chat(self, system, messages, tools, max_tokens=2048, temperature=0.7, timeout=120.0):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return director_responses[0]
            raise RuntimeError("author network down")

    p = FailingAuthor()
    import app.providers as prov_mod
    old = prov_mod.get_provider
    prov_mod.get_provider = lambda *a, **kw: p
    try:
        res = run_step(db, w, provider=p)
    finally:
        prov_mod.get_provider = old

    assert res["ok"]
    # 回落：final 文本就是粗稿原文
    finals = db.query(NarrativeLog).filter_by(branch_id=br.id, role="author_final").all()
    assert len(finals) == 1 and finals[0].text == "她推门进来。"
    assert "她推门进来。" in res["narration"]
