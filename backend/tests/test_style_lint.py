"""程序化 AI 腔检测的单元测试。纯 regex/统计，无 LLM 依赖。"""
from __future__ import annotations

from app.engine.agents.style_lint import (
    FAIL_THRESHOLD,
    format_lint_feedback,
    lint_text,
)


def test_clean_short_text_passes():
    text = "他走进房间，看见桌上的信。\n他把信收进口袋。"
    r = lint_text(text)
    assert r.passed
    assert r.score < FAIL_THRESHOLD


def test_dash_density_flags_double_dash_in_paragraph():
    text = "他停下了——心里说不出滋味——又走了几步。"
    r = lint_text(text)
    assert any(v.rule == "dash_density" for v in r.violations)


def test_ai_phrase_single_hit_minor():
    text = "那一瞬间，他没有说话。"
    r = lint_text(text)
    hits = [v for v in r.violations if v.rule == "ai_phrase"]
    assert len(hits) == 1
    assert hits[0].severity == 1


def test_ai_phrase_repeat_major():
    text = "那一瞬间，他没有说话。\n那一瞬间，所有人都安静了。"
    r = lint_text(text)
    hits = [v for v in r.violations if v.rule == "ai_phrase"]
    assert hits and hits[0].severity == 2


def test_concession_stack_needs_two():
    one = "虽然他走得很慢，但他终于至少能站起来了。"
    r1 = lint_text(one)
    assert not any(v.rule == "concession_stack" for v in r1.violations)

    two = one + "\n虽然她不愿意，但她还是总算答应了下来。"
    r2 = lint_text(two)
    assert any(v.rule == "concession_stack" for v in r2.violations)


def test_trailing_philosophy_minor_then_major():
    one = "他终于明白，也许沉默才是最好的回答。"
    r1 = lint_text(one)
    p1 = [v for v in r1.violations if v.rule == "trailing_philosophy"]
    assert p1 and p1[0].severity == 1

    two = one + "\n或许人本来就从来不属于自己的命运。"
    r2 = lint_text(two)
    p2 = [v for v in r2.violations if v.rule == "trailing_philosophy"]
    assert p2 and p2[0].severity == 2


def test_action_decompose_pair():
    text = "他伸出手，又抬起头。\n她放下笔，握住他的手。"
    r = lint_text(text)
    assert any(v.rule == "action_decompose" for v in r.violations)


def test_uniform_length_with_4plus_paragraphs():
    para = "这一段刚好二十个字符够用了来测试。"
    text = "\n".join([para] * 4)
    r = lint_text(text)
    assert any(v.rule == "uniform_length" for v in r.violations)


def test_uniform_length_skips_below_4_paragraphs():
    para = "这一段刚好二十个字符够用了来测试。"
    text = "\n".join([para] * 3)
    r = lint_text(text)
    assert not any(v.rule == "uniform_length" for v in r.violations)


def test_score_aggregates_severity():
    text = "那一瞬间——隐隐——某种东西的影子在。"
    r = lint_text(text)
    assert r.score == sum(v.severity for v in r.violations)


def test_fail_threshold_triggers_not_passed():
    text = "\n".join([
        "那一瞬间，他没有说话。",
        "那一瞬间，他终于沉默了。",
        "隐隐有什么在心底涌起。",
        "隐隐还有什么在心底升起。",
    ])
    r = lint_text(text)
    assert r.score >= FAIL_THRESHOLD
    assert not r.passed


def test_format_feedback_includes_all_rules():
    text = "那一瞬间，他停了下来——又再次停下——隐隐感到不安。"
    r = lint_text(text)
    fb = format_lint_feedback(r)
    assert "程序化风格检测未通过" in fb
    for v in r.violations:
        assert v.rule in fb
