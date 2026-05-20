"""A6 自纠环测试：Editor 发现的 open issue 反馈到 Director 的 prompt。

用直接调用 _build_self_correction_block 和 _build_user_prompt 验证拼装逻辑。
不跑真实 LLM——这一层只测 prompt 构造。
"""
from __future__ import annotations
import pytest

from app.models import ConsistencyIssue


def _add_issue(db, branch_id: str, *, id: str, **kw):
    defaults = dict(
        category="personality", severity="medium",
        title="问题", description="描述", suggestion="建议",
        entity_ids=[], tick_start=1, tick_end=1, status="open",
        scan_id="scan_x",
    )
    defaults.update(kw)
    iss = ConsistencyIssue(
        id=id,
        world_id="w_irrelevant",  # block 只按 branch_id 过滤
        branch_id=branch_id,
        **defaults,
    )
    db.add(iss); db.flush()
    return iss


# ---- _build_self_correction_block ----

def test_block_empty_when_no_issues(db, world_factory):
    from app.engine.simulator import _build_self_correction_block
    w, br = world_factory()
    out = _build_self_correction_block(db, w)
    assert out == ""


def test_block_renders_open_issues(db, world_factory):
    from app.engine.simulator import _build_self_correction_block
    w, br = world_factory()
    _add_issue(db, br.id, id="i_1", title="阿离前后矛盾", description="前文沉默后文话痨",
               severity="high", category="personality")
    _add_issue(db, br.id, id="i_2", title="时代器物错乱", description="清代器物入宋",
               severity="low", category="rule")
    db.commit()

    out = _build_self_correction_block(db, w)
    assert "编辑反馈" in out
    assert "阿离前后矛盾" in out
    assert "时代器物错乱" in out


def test_block_skips_non_open_status(db, world_factory):
    from app.engine.simulator import _build_self_correction_block
    w, br = world_factory()
    _add_issue(db, br.id, id="i_a", title="已忽略问题", status="ignored")
    _add_issue(db, br.id, id="i_b", title="已解决问题", status="resolved")
    db.commit()

    out = _build_self_correction_block(db, w)
    assert out == ""  # 没 open 的


def test_block_severity_high_first(db, world_factory):
    from app.engine.simulator import _build_self_correction_block
    w, br = world_factory()
    _add_issue(db, br.id, id="i_low", title="低优", severity="low", tick_end=10)
    _add_issue(db, br.id, id="i_high", title="高优", severity="high", tick_end=2)
    _add_issue(db, br.id, id="i_med", title="中优", severity="medium", tick_end=5)
    db.commit()

    out = _build_self_correction_block(db, w)
    # high 必须出现在 medium 之前，medium 在 low 之前
    p_high = out.index("高优")
    p_med = out.index("中优")
    p_low = out.index("低优")
    assert p_high < p_med < p_low


def test_block_caps_at_5_issues(db, world_factory):
    from app.engine.simulator import _build_self_correction_block
    w, br = world_factory()
    for i in range(8):
        _add_issue(db, br.id, id=f"i_{i}", title=f"问题{i}", severity="medium")
    db.commit()

    out = _build_self_correction_block(db, w)
    # 应只有 5 条 - 题目从 0 到 4 出现，5/6/7 不出现
    appearing = sum(1 for i in range(8) if f"问题{i}" in out)
    assert appearing == 5


def test_block_disabled_via_world_rules(db, world_factory):
    from app.engine.simulator import _build_self_correction_block
    w, br = world_factory(rules={"disable_self_correction": True})
    _add_issue(db, br.id, id="i_x", title="不该出现", severity="high")
    db.commit()

    out = _build_self_correction_block(db, w)
    assert out == ""


def test_block_truncates_long_text(db, world_factory):
    from app.engine.simulator import _build_self_correction_block
    w, br = world_factory()
    long_desc = "X" * 500
    long_sug = "Y" * 500
    _add_issue(db, br.id, id="i_long", title="长", description=long_desc, suggestion=long_sug)
    db.commit()

    out = _build_self_correction_block(db, w)
    # description 截 120, suggestion 截 120
    assert "X" * 121 not in out
    assert "Y" * 121 not in out


def test_block_only_current_branch(db, world_factory):
    """另一 branch 的 issue 不应泄露到本 branch 的 prompt 里。"""
    from app.engine.simulator import _build_self_correction_block
    from app.models import Branch
    import uuid
    w, br = world_factory()
    br2 = Branch(id=f"br_{uuid.uuid4().hex[:6]}", world_id=w.id, name="alt",
                 description="", parent_branch_id=br.id, diverged_at_tick=0)
    db.add(br2); db.flush()
    _add_issue(db, br2.id, id="i_other", title="其它分支问题", severity="high")
    db.commit()

    out = _build_self_correction_block(db, w)
    assert "其它分支问题" not in out
    assert out == ""


# ---- _build_user_prompt 集成 ----

def test_user_prompt_includes_feedback_block(db, world_factory):
    from app.engine.simulator import _build_user_prompt
    from app.engine.state import build_state_snapshot
    w, br = world_factory()
    _add_issue(db, br.id, id="i_p", title="某问题", severity="high")
    db.commit()

    snap = build_state_snapshot(db, w)
    prompt = _build_user_prompt(db, snap, None, w)
    assert "编辑反馈" in prompt
    assert "某问题" in prompt


def test_user_prompt_no_feedback_when_disabled(db, world_factory):
    from app.engine.simulator import _build_user_prompt
    from app.engine.state import build_state_snapshot
    w, br = world_factory(rules={"disable_self_correction": True})
    _add_issue(db, br.id, id="i_q", title="不该出现的问题", severity="high")
    db.commit()

    snap = build_state_snapshot(db, w)
    prompt = _build_user_prompt(db, snap, None, w)
    assert "编辑反馈" not in prompt
    assert "不该出现的问题" not in prompt
