"""V2 fact-check critic for manuscript event extraction (路线 #7)。"""
from __future__ import annotations
import json

from app.engine.manuscript.manuscript_events import (
    DraftEvent, fact_check_events, extract_events,
)
from app.providers import LLMResponse


def _make_event(tick: int, ch: int, title: str, desc: str, parts=None) -> DraftEvent:
    return DraftEvent(
        chapter_index=ch,
        chapter_title=f"第{ch}章",
        title=title, description=desc,
        participant_names=parts or [],
        participant_ids=[], unresolved_names=[],
        location_name="", location_id=None,
        tick=tick,
    )


class _FactCheckProvider:
    name = "fake-fc"

    def __init__(self, verdicts_by_chapter: dict[int, list[dict]]):
        self.calls = 0
        self.queue: list[LLMResponse] = []
        for ch in sorted(verdicts_by_chapter.keys()):
            payload = {"verdicts": verdicts_by_chapter[ch]}
            self.queue.append(LLMResponse(text=json.dumps(payload, ensure_ascii=False)))

    def chat(self, system, messages, tools, **kw):
        self.calls += 1
        if self.queue:
            return self.queue.pop(0)
        return LLMResponse(text='{"verdicts":[]}')


def test_fact_check_marks_failed_events():
    chunks = [
        {"title": "夜袭", "text": "林冲提刀出门，雪夜里独自上路。"},
    ]
    events = [
        _make_event(1, 1, "出门", "林冲提刀出门", parts=["林冲"]),
        _make_event(2, 1, "杀虎", "林冲在山上猎了一只白虎"),  # 原文没说
    ]
    p = _FactCheckProvider({1: [
        {"tick": 1, "verified": True, "reason": ""},
        {"tick": 2, "verified": False, "reason": "原文未提虎"},
    ]})
    warnings = fact_check_events(events=events, chunks=chunks, llm=p)
    assert warnings == []
    assert events[0].needs_review is False
    assert events[0].review_reason == ""
    assert events[1].needs_review is True
    assert "未提虎" in events[1].review_reason


def test_fact_check_missing_verdict_marks_review():
    """LLM 漏给某个 tick 的 verdict → 兜底标 needs_review。"""
    chunks = [{"title": "x", "text": "短文"}]
    events = [
        _make_event(1, 1, "a", "事件 a"),
        _make_event(2, 1, "b", "事件 b"),
    ]
    p = _FactCheckProvider({1: [
        {"tick": 1, "verified": True, "reason": ""},
        # tick 2 缺失
    ]})
    fact_check_events(events=events, chunks=chunks, llm=p)
    assert events[0].needs_review is False
    assert events[1].needs_review is True
    assert "未给出" in events[1].review_reason


def test_fact_check_invalid_json_emits_warning_no_mark():
    """LLM 输出非 JSON：保留事件原状，警告写出。"""
    chunks = [{"title": "x", "text": "原文"}]
    events = [_make_event(1, 1, "a", "事件 a")]

    class P:
        name = "p"
        def chat(self, *a, **kw): return LLMResponse(text="不是 JSON")
    warnings = fact_check_events(events=events, chunks=chunks, llm=P())
    assert any("非法 JSON" in w for w in warnings)
    assert events[0].needs_review is False  # 没 verdict 时不动


def test_fact_check_missing_chapter_text_skipped():
    """事件 chapter_index 越界，找不到原文 → warn 跳过，事件不变。"""
    chunks = [{"title": "x", "text": "短"}]
    events = [_make_event(1, 5, "a", "在第 5 章")]
    p = _FactCheckProvider({})
    warnings = fact_check_events(events=events, chunks=chunks, llm=p)
    assert any("第 5 章" in w for w in warnings)
    assert events[0].needs_review is False


def test_fact_check_persisted_through_to_dict():
    ev = _make_event(1, 1, "a", "事件")
    ev.needs_review = True
    ev.review_reason = "测试理由"
    d = ev.to_dict()
    assert d["needs_review"] is True
    assert d["review_reason"] == "测试理由"


def test_extract_events_with_fact_check_pass(monkeypatch):
    """extract_events(fact_check=True) 应该跑完抽取后再跑 fact_check, 标记失败事件。"""
    chunks = [
        {"title": "夜袭", "text": "林冲提刀出门。"},
    ]
    extract_payload = {
        "events": [
            {"chapter_index": 1, "title": "出门",
             "description": "林冲提刀出门",
             "participants": ["林冲"], "location": ""},
            {"chapter_index": 1, "title": "杀虎",
             "description": "林冲杀了一只虎",
             "participants": ["林冲"], "location": "山"},
        ]
    }
    fact_check_payload = {
        "verdicts": [
            {"tick": 1, "verified": True, "reason": ""},
            {"tick": 2, "verified": False, "reason": "原文无虎"},
        ]
    }

    class P:
        name = "p"
        def __init__(self):
            self.queue = [
                LLMResponse(text=json.dumps(extract_payload, ensure_ascii=False)),
                LLMResponse(text=json.dumps(fact_check_payload, ensure_ascii=False)),
            ]
        def chat(self, *a, **kw):
            return self.queue.pop(0) if self.queue else LLMResponse(text="{}")

    result = extract_events(
        chunks=chunks,
        name_to_entity_id={},
        location_name_to_id={},
        llm=P(),
        fact_check=True,
    )
    assert len(result.events) == 2
    by_tick = {e.tick: e for e in result.events}
    assert by_tick[1].needs_review is False
    assert by_tick[2].needs_review is True
    assert "无虎" in by_tick[2].review_reason


def test_extract_events_without_fact_check_keeps_default():
    chunks = [{"title": "x", "text": "原文"}]
    extract_payload = {
        "events": [
            {"chapter_index": 1, "title": "a", "description": "事件 a",
             "participants": [], "location": ""},
        ]
    }

    class P:
        name = "p"
        def __init__(self):
            self.queue = [LLMResponse(text=json.dumps(extract_payload, ensure_ascii=False))]
        def chat(self, *a, **kw):
            return self.queue.pop(0) if self.queue else LLMResponse(text="{}")

    p = P()
    result = extract_events(
        chunks=chunks, name_to_entity_id={}, location_name_to_id={},
        llm=p, fact_check=False,
    )
    assert len(result.events) == 1
    assert result.events[0].needs_review is False
    # 没开 fact_check, LLM 只调一次
    assert len(p.queue) == 0
