"""persona_extract 测试 —— 主要测纯函数 (_parse_json_object / _as_str_list) 与 extract_persona 的早返/解析路径。"""
from __future__ import annotations
import pytest

from app.providers.base import LLMResponse
from app.engine.executor import execute_tool


# ---- _parse_json_object ----

def test_parse_json_naked_object():
    from app.engine.persona_extract import _parse_json_object
    assert _parse_json_object('{"a": 1}') == {"a": 1}


def test_parse_json_with_fence():
    from app.engine.persona_extract import _parse_json_object
    assert _parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_with_preamble():
    from app.engine.persona_extract import _parse_json_object
    # 前面有废话也能找出来
    assert _parse_json_object('好的，我的回答是：{"x": "y"}') == {"x": "y"}


def test_parse_json_returns_none():
    from app.engine.persona_extract import _parse_json_object
    assert _parse_json_object("") is None
    assert _parse_json_object("纯文本无对象") is None


def test_parse_json_handles_nested():
    from app.engine.persona_extract import _parse_json_object
    s = '{"a": {"b": [1, 2]}, "c": "ok"}'
    assert _parse_json_object(s) == {"a": {"b": [1, 2]}, "c": "ok"}


# ---- _as_str_list ----

def test_as_str_list_from_list():
    from app.engine.persona_extract import _as_str_list
    assert _as_str_list(["a", "b"], 5) == ["a", "b"]


def test_as_str_list_from_csv_string():
    from app.engine.persona_extract import _as_str_list
    assert _as_str_list("a, b, c", 5) == ["a", "b", "c"]


def test_as_str_list_dedup_and_truncate():
    from app.engine.persona_extract import _as_str_list
    out = _as_str_list(["a", "a", "b", "c", "d"], 2)
    assert out == ["a", "b"]


def test_as_str_list_empty_inputs():
    from app.engine.persona_extract import _as_str_list
    assert _as_str_list(None, 3) == []
    assert _as_str_list("", 3) == []
    assert _as_str_list({}, 3) == []  # 非 list 非 str


# ---- extract_persona 早返与解析 ----

def test_extract_persona_unknown_entity(db, world_factory):
    from app.engine.persona_extract import extract_persona
    w, _ = world_factory()
    with pytest.raises(ValueError):
        extract_persona(db, "ent_nope")


def test_extract_persona_too_few_events(db, world_factory):
    """事件少于 2 时不调 LLM。"""
    from app.engine.persona_extract import extract_persona
    w, _ = world_factory()
    eid = execute_tool(db, w, "create_entity", {"type": "character", "name": "孤鸟"})["id"]

    class BoomP:
        name = "boom"
        def chat(self, *a, **k):
            raise AssertionError("不应调 LLM")

    res = extract_persona(db, eid, provider=BoomP())
    assert res["ok"] is False
    assert "事件太少" in res["reason"]
    assert res["event_count"] == 0


def test_extract_persona_parses_llm_output(db, world_factory):
    """LLM 返回有效 JSON 时，归一化到 suggestion。"""
    from app.engine.persona_extract import extract_persona
    w, _ = world_factory()
    eid = execute_tool(db, w, "create_entity", {"type": "character", "name": "主角"})["id"]
    # 至少 2 个相关事件
    for i in range(3):
        execute_tool(db, w, "add_event", {
            "title": f"事件{i}", "description": "x",
            "participants": [eid],
        })

    class FakeP:
        name = "fake"
        def chat(self, *a, **k):
            return LLMResponse(text='''```json
            {
              "drives": ["复仇", "保护妹妹"],
              "voice": "冷静低沉",
              "blindspots": "重感情",
              "knowledge_of": ["反派A"],
              "rationale": "由事件推出"
            }
            ```''')

    res = extract_persona(db, eid, provider=FakeP())
    assert res["ok"] is True
    s = res["suggestion"]
    assert s["drives"] == ["复仇", "保护妹妹"]
    assert s["voice"] == "冷静低沉"
    # blindspots 是字符串也应转成 list
    assert s["blindspots"] == ["重感情"]
    assert "knowledge_of_resolved" in s


def test_extract_persona_unparseable_llm(db, world_factory):
    """LLM 返回非 JSON 时，应优雅降级返回 ok=False。"""
    from app.engine.persona_extract import extract_persona
    w, _ = world_factory()
    eid = execute_tool(db, w, "create_entity", {"type": "character", "name": "主角"})["id"]
    for i in range(2):
        execute_tool(db, w, "add_event", {"title": "x", "description": "x",
                                          "participants": [eid]})

    class FakeP:
        name = "fake"
        def chat(self, *a, **k):
            return LLMResponse(text="no json here")

    res = extract_persona(db, eid, provider=FakeP())
    assert res["ok"] is False
    assert "解析" in res["reason"] or "JSON" in res["reason"]


def test_extract_persona_llm_exception_is_caught(db, world_factory):
    """provider.chat 抛异常时 extract_persona 不应崩。"""
    from app.engine.persona_extract import extract_persona
    w, _ = world_factory()
    eid = execute_tool(db, w, "create_entity", {"type": "character", "name": "主角"})["id"]
    for i in range(2):
        execute_tool(db, w, "add_event", {"title": "x", "description": "x",
                                          "participants": [eid]})

    class BoomP:
        name = "boom"
        def chat(self, *a, **k):
            raise RuntimeError("502")

    res = extract_persona(db, eid, provider=BoomP())
    assert res["ok"] is False
    assert "502" in res["reason"] or "失败" in res["reason"]
