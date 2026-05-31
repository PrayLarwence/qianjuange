"""Reader Agent 单元测试 — 走 FakeProvider，验证状态读写、容错、brief 产出。"""
from __future__ import annotations

import json
import uuid

import pytest

from app.engine.agents.reader import (
    build_slim_context,
    get_current_brief,
    get_or_create_reader_state,
    run_reader_review,
)
from app.models import NarrativeLog, ReaderState
from app.providers.base import LLMResponse


class _FakeProvider:
    name = "fake"

    def __init__(self, response: LLMResponse | Exception | None = None):
        self.response = response
        self.calls = 0

    def chat(self, **_):
        self.calls += 1
        if isinstance(self.response, Exception):
            raise self.response
        return self.response or LLMResponse(text="{}")


@pytest.fixture
def world(db, world_factory):
    w, br = world_factory(name="test", outline="一个测试世界的大纲。")
    return w, br


def test_get_or_create_state_returns_same_row(db, world):
    w, _ = world
    s1 = get_or_create_reader_state(db, w)
    s2 = get_or_create_reader_state(db, w)
    assert s1.id == s2.id
    assert s1.character_states == [] and s1.foreshadowing == []


def test_empty_chapter_short_circuits(db, world):
    w, _ = world
    llm = _FakeProvider()
    r = run_reader_review(db, w, "   \n\n  ", chapter_number=1, provider=llm)
    assert r == {"passed": True, "issues": [], "brief": "", "llm_calls": 0}
    assert llm.calls == 0


def test_no_provider_short_circuits(monkeypatch, db, world):
    """provider 显式 None 且 get_provider_for_role 返回 None 时，安全跳过。"""
    w, _ = world
    import app.engine.agents.reader as reader_mod
    monkeypatch.setattr(reader_mod, "get_provider_for_role", lambda *a, **k: None)
    r = run_reader_review(db, w, "本章正文。", chapter_number=1, provider=None)
    assert r == {"passed": True, "issues": [], "brief": "", "llm_calls": 0}


def test_full_review_updates_state(db, world):
    w, _ = world
    payload = {
        "validation": {"passed": True, "issues": []},
        "updated_characters": [
            {"name": "林夏", "location": "图书馆", "emotion": "紧张",
             "status": "存活", "inventory": ["旧信"], "notes": ""}
        ],
        "updated_foreshadowing": [
            {"description": "门后有什么", "planted_chapter": 1, "resolved": False}
        ],
        "updated_prohibitions": [
            {"description": "不能提前揭示父亲身份", "until_chapter": 5}
        ],
        "chapter_summary": "林夏发现旧信。",
        "next_brief": {
            "plot_advance": "林夏寻找寄信人",
            "character_positions": "林夏在图书馆",
            "foreshadowing_to_resolve": "",
            "continuation_point": "她拆开信封",
            "prohibitions": "父亲身份保密",
        },
    }
    llm = _FakeProvider(LLMResponse(text=json.dumps(payload, ensure_ascii=False)))
    r = run_reader_review(db, w, "林夏走进图书馆，找到一封旧信。", chapter_number=1, provider=llm)

    assert r["passed"] is True
    assert r["llm_calls"] == 1
    assert "林夏" in r["brief"]
    assert "图书馆" in r["brief"]

    state = db.query(ReaderState).filter_by(world_id=w.id).first()
    assert len(state.character_states) == 1
    assert state.character_states[0]["name"] == "林夏"
    assert len(state.foreshadowing) == 1 and state.foreshadowing[0]["id"]
    assert len(state.prohibitions) == 1
    assert len(state.chapter_summaries) == 1
    assert state.last_brief == r["brief"]


def test_validation_failure_propagates(db, world):
    w, _ = world
    payload = {
        "validation": {
            "passed": False,
            "issues": [{"paragraph": "段首...", "problem": "时间矛盾", "fix_hint": "改"}],
        },
        "next_brief": {},
    }
    llm = _FakeProvider(LLMResponse(text=json.dumps(payload, ensure_ascii=False)))
    r = run_reader_review(db, w, "本章正文。", chapter_number=1, provider=llm)
    assert r["passed"] is False
    assert r["issues"] and r["issues"][0]["problem"] == "时间矛盾"


def test_invalid_json_falls_back_to_last_brief(db, world):
    w, _ = world
    state = get_or_create_reader_state(db, w)
    state.last_brief = "之前的 brief"
    db.commit()

    llm = _FakeProvider(LLMResponse(text="不是 JSON 的废话"))
    r = run_reader_review(db, w, "本章正文。", chapter_number=2, provider=llm)
    assert r["passed"] is True
    assert r["issues"] == []
    assert r["brief"] == "之前的 brief"
    assert r["llm_calls"] == 1


def test_llm_exception_falls_back(db, world):
    w, _ = world
    llm = _FakeProvider(RuntimeError("network down"))
    r = run_reader_review(db, w, "本章正文。", chapter_number=1, provider=llm)
    assert r["passed"] is True
    assert r["llm_calls"] == 1


def test_fenced_json_is_parsed(db, world):
    w, _ = world
    payload = {
        "validation": {"passed": True, "issues": []},
        "next_brief": {"plot_advance": "推进 A 节点"},
    }
    fenced = "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
    llm = _FakeProvider(LLMResponse(text=fenced))
    r = run_reader_review(db, w, "正文。", chapter_number=1, provider=llm)
    assert r["passed"] is True
    assert "推进 A 节点" in r["brief"]


def test_get_current_brief_returns_persisted(db, world):
    w, _ = world
    state = get_or_create_reader_state(db, w)
    state.last_brief = "持久化的 brief"
    db.commit()
    assert get_current_brief(db, w) == "持久化的 brief"


def test_get_current_brief_empty_when_no_state(db, world):
    w, _ = world
    assert get_current_brief(db, w) == ""


def test_build_slim_context_includes_brief_and_tail(db, world):
    w, br = world
    state = get_or_create_reader_state(db, w)
    state.last_brief = "【本章目标】抓住凶手"
    db.commit()

    db.add(NarrativeLog(
        id=f"n_{uuid.uuid4().hex[:8]}",
        branch_id=br.id,
        tick=1,
        role="author_final",
        text="上一章的最后一段，把这段当作衔接尾巴。" * 5,
    ))
    db.commit()

    ctx = build_slim_context(db, w)
    assert "【本章目标】抓住凶手" in ctx
    assert "衔接尾巴" in ctx
