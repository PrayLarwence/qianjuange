"""consistency 一致性扫描测试。

分两层：
1. 纯函数：_extract_json + _normalize_issue 各种边界
2. run_scan：用 monkeypatch 把 get_provider 替换为 FakeProvider
"""
from __future__ import annotations
from app.providers.base import LLMResponse


# ---- _extract_json ----

def test_extract_json_from_fenced_code():
    from app.engine.consistency.consistency import _extract_json
    text = '```json\n{"issues": [{"x": 1}]}\n```'
    assert _extract_json(text) == {"issues": [{"x": 1}]}


def test_extract_json_from_naked_braces():
    from app.engine.consistency.consistency import _extract_json
    text = '废话开头 {"issues": []} 废话结尾'
    assert _extract_json(text) == {"issues": []}


def test_extract_json_returns_none_when_no_json():
    from app.engine.consistency.consistency import _extract_json
    assert _extract_json("纯散文，没有任何对象") is None
    assert _extract_json("") is None


def test_extract_json_handles_invalid_json():
    from app.engine.consistency.consistency import _extract_json
    # 看起来像 JSON 但坏了
    assert _extract_json("{not real json}") is None


# ---- _normalize_issue ----

def test_normalize_issue_minimum_valid():
    from app.engine.consistency.consistency import _normalize_issue
    raw = {"category": "personality", "severity": "high",
           "description": "前后矛盾"}
    out = _normalize_issue(raw, valid_ids=set(), tick_from=0, tick_to=10)
    assert out is not None
    assert out["category"] == "personality"
    assert out["severity"] == "high"
    assert out["description"] == "前后矛盾"
    # title 缺失走 category 默认标签
    assert out["title"] == "性格冲突"


def test_normalize_issue_unknown_category_falls_back():
    from app.engine.consistency.consistency import _normalize_issue
    raw = {"category": "wat", "severity": "low", "description": "?"}
    out = _normalize_issue(raw, set(), 0, 5)
    assert out["category"] == "other"


def test_normalize_issue_unknown_severity_falls_back():
    from app.engine.consistency.consistency import _normalize_issue
    raw = {"category": "rule", "severity": "catastrophic", "description": "?"}
    out = _normalize_issue(raw, set(), 0, 5)
    assert out["severity"] == "medium"


def test_normalize_issue_filters_invalid_entity_ids():
    from app.engine.consistency.consistency import _normalize_issue
    raw = {"category": "rule", "severity": "low", "description": "x",
           "entity_ids": ["e_real", "e_ghost", 123, None]}
    out = _normalize_issue(raw, valid_ids={"e_real"}, tick_from=0, tick_to=5)
    assert out["entity_ids"] == ["e_real"]


def test_normalize_issue_drops_when_no_description():
    from app.engine.consistency.consistency import _normalize_issue
    raw = {"category": "rule", "severity": "low", "description": ""}
    assert _normalize_issue(raw, set(), 0, 5) is None


def test_normalize_issue_clamps_tick_range():
    from app.engine.consistency.consistency import _normalize_issue
    raw = {"category": "rule", "severity": "low", "description": "x",
           "tick_start": -5, "tick_end": 999}
    out = _normalize_issue(raw, set(), 10, 20)
    assert out["tick_start"] == 10
    assert out["tick_end"] == 20


def test_normalize_issue_truncates_long_strings():
    from app.engine.consistency.consistency import _normalize_issue
    raw = {"category": "rule", "severity": "low",
           "title": "x" * 100, "description": "y" * 500,
           "suggestion": "z" * 500}
    out = _normalize_issue(raw, set(), 0, 5)
    assert len(out["title"]) <= 40
    assert len(out["description"]) <= 240
    assert len(out["suggestion"]) <= 240


# ---- run_scan ----

def test_run_scan_empty_world_completes_without_llm(db, world_factory, monkeypatch):
    """空世界（无事件无叙事）应直接完成，不调 LLM。"""
    from app.engine import consistency
    w, _ = world_factory()

    called = {"n": 0}
    def fake_provider(_=None):
        called["n"] += 1
        raise AssertionError("不应调到 provider")
    monkeypatch.setattr(consistency.consistency, "get_provider", fake_provider)

    run = consistency.run_scan(db, w, scope="all")
    assert run.status == "completed"
    assert run.issue_count == 0
    assert called["n"] == 0


def test_run_scan_with_events_calls_provider(db, world_factory, monkeypatch):
    """有事件时应调 provider 并把返回的 issues 落库。"""
    from app.engine import consistency
    from app.engine.core.executor import execute_tool

    w, _ = world_factory()
    execute_tool(db, w, "create_entity", {"type": "character", "name": "甲"})
    execute_tool(db, w, "add_event", {"title": "首战", "description": "开打"})

    fake_resp = LLMResponse(text='''```json
    {"issues": [
      {"category": "personality", "severity": "high",
       "description": "甲前后说话风格反差大",
       "suggestion": "加个铺垫",
       "entity_ids": [], "tick_start": 0, "tick_end": 0}
    ]}
    ```''')

    class FakeP:
        name = "fake"
        def chat(self, system, messages, tools, **kw):
            return fake_resp

    monkeypatch.setattr(consistency.consistency, "get_provider", lambda _=None: FakeP())

    run = consistency.run_scan(db, w, scope="all")
    assert run.status == "completed"
    assert run.issue_count == 1


def test_run_scan_invalid_json_returns_zero_issues(db, world_factory, monkeypatch):
    """LLM 回了垃圾，scan 应安静地完成且 issue_count=0，不崩。"""
    from app.engine import consistency
    from app.engine.core.executor import execute_tool

    w, _ = world_factory()
    execute_tool(db, w, "add_event", {"title": "x", "description": ""})

    class FakeP:
        name = "fake"
        def chat(self, system, messages, tools, **kw):
            return LLMResponse(text="一段没有 JSON 的散文")

    monkeypatch.setattr(consistency.consistency, "get_provider", lambda _=None: FakeP())
    run = consistency.run_scan(db, w, scope="all")
    assert run.status == "completed"
    assert run.issue_count == 0


def test_run_scan_provider_failure_marks_failed(db, world_factory, monkeypatch):
    from app.engine import consistency
    from app.engine.core.executor import execute_tool

    w, _ = world_factory()
    execute_tool(db, w, "add_event", {"title": "x", "description": ""})

    class BoomP:
        name = "boom"
        def chat(self, system, messages, tools, **kw):
            raise RuntimeError("network down")

    monkeypatch.setattr(consistency.consistency, "get_provider", lambda _=None: BoomP())
    run = consistency.run_scan(db, w, scope="all")
    assert run.status == "failed"
    assert "network" in (run.error or "").lower()
