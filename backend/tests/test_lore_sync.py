"""lore_sync: Director 漏注册的世界设定从事件/叙事里反扫一遍补登。

走 FakeProvider，验证：
- 空步（无事件无叙事）→ 不打 LLM，返回 []
- 有产出 + LLM 给出有效 lore → 写入 WorldLore，priority=-1（待 review）
- LLM 给重复 title → 跳过去重
- LLM 返回非法 JSON → 静默吞掉，返回 []
- LLM 异常 → 静默吞掉，返回 []
- category 非法 → 落库时降级到 'setting'
- 最多取 3 条
"""
from __future__ import annotations

import pytest

from app.engine.agents.lore_sync import extract_lore_from_step
from app.models import Event, NarrativeLog, WorldLore
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
        return self.response or LLMResponse(text='{"lore":[]}')


@pytest.fixture
def world(db, world_factory):
    w, br = world_factory(name="测试世界")
    return w, br


def _add_event(db, world, branch, tick=1, title="事件", desc="描述"):
    import uuid
    ev = Event(
        id=f"ev_{uuid.uuid4().hex[:8]}",
        branch_id=branch.id,
        tick=tick,
        title=title,
        description=desc,
    )
    db.add(ev)
    db.commit()
    return ev


def _add_narration(db, world, branch, tick=1, text="一段叙事内容写得长一点能过 50 字阈值。" * 3):
    import uuid
    n = NarrativeLog(
        id=f"n_{uuid.uuid4().hex[:8]}",
        branch_id=branch.id,
        tick=tick,
        role="director_draft",
        text=text,
    )
    db.add(n)
    db.commit()
    return n


def test_no_events_no_narration_skips_llm(db, world):
    w, br = world
    llm = _FakeProvider()
    result = extract_lore_from_step(db, w, br.id, tick=1, llm=llm)
    assert result == []
    assert llm.calls == 0


def test_too_short_source_returns_empty(db, world):
    w, br = world
    _add_event(db, w, br, title="t", desc="d")
    llm = _FakeProvider()
    result = extract_lore_from_step(db, w, br.id, tick=1, llm=llm)
    assert result == []
    assert llm.calls == 0


def test_extracts_lore_and_persists(db, world):
    w, br = world
    _add_narration(db, w, br)
    llm = _FakeProvider(LLMResponse(text='''
        {"lore":[
          {"title":"魔力来自月光","content":"夜间施法效果加倍。","category":"magic"},
          {"title":"东境寒冷","content":"东境冬季漫长。","category":"geography"}
        ]}
    '''))
    result = extract_lore_from_step(db, w, br.id, tick=1, llm=llm)

    assert len(result) == 2
    assert llm.calls == 1
    rows = db.query(WorldLore).filter_by(world_id=w.id).all()
    assert len(rows) == 2
    assert all(r.priority == -1 and r.pinned == 0 for r in rows)
    cats = {r.category for r in rows}
    assert cats == {"magic", "geography"}


def test_skips_duplicates_case_insensitive(db, world):
    w, br = world
    _add_narration(db, w, br)
    import uuid
    db.add(WorldLore(
        id=f"lore_{uuid.uuid4().hex[:8]}",
        world_id=w.id, category="magic",
        title="魔力来自月光", content="已有", priority=0, pinned=0,
    ))
    db.commit()

    llm = _FakeProvider(LLMResponse(text='''
        {"lore":[
          {"title":"魔力来自月光","content":"重复的","category":"magic"},
          {"title":"全新设定","content":"这个会进。","category":"setting"}
        ]}
    '''))
    result = extract_lore_from_step(db, w, br.id, tick=1, llm=llm)

    assert len(result) == 1
    assert result[0]["title"] == "全新设定"


def test_invalid_json_returns_empty(db, world):
    w, br = world
    _add_narration(db, w, br)
    llm = _FakeProvider(LLMResponse(text="一坨非 JSON 的废话"))
    result = extract_lore_from_step(db, w, br.id, tick=1, llm=llm)
    assert result == []


def test_llm_exception_swallowed(db, world):
    w, br = world
    _add_narration(db, w, br)
    llm = _FakeProvider(RuntimeError("network down"))
    result = extract_lore_from_step(db, w, br.id, tick=1, llm=llm)
    assert result == []


def test_invalid_category_downgrades_to_setting(db, world):
    w, br = world
    _add_narration(db, w, br)
    llm = _FakeProvider(LLMResponse(text='''
        {"lore":[{"title":"奇怪条目","content":"测试用。","category":"banana"}]}
    '''))
    result = extract_lore_from_step(db, w, br.id, tick=1, llm=llm)
    assert len(result) == 1
    row = db.query(WorldLore).filter_by(world_id=w.id).first()
    assert row.category == "setting"


def test_caps_at_3_entries(db, world):
    w, br = world
    _add_narration(db, w, br)
    llm = _FakeProvider(LLMResponse(text='''
        {"lore":[
          {"title":"A","content":"a","category":"setting"},
          {"title":"B","content":"b","category":"setting"},
          {"title":"C","content":"c","category":"setting"},
          {"title":"D","content":"d","category":"setting"},
          {"title":"E","content":"e","category":"setting"}
        ]}
    '''))
    result = extract_lore_from_step(db, w, br.id, tick=1, llm=llm)
    assert len(result) == 3


def test_fenced_json_parsed(db, world):
    w, br = world
    _add_narration(db, w, br)
    llm = _FakeProvider(LLMResponse(text='''解释一下：
```json
{"lore":[{"title":"代码块里的设定","content":"内容","category":"culture"}]}
```
完毕'''))
    result = extract_lore_from_step(db, w, br.id, tick=1, llm=llm)
    assert len(result) == 1
    assert result[0]["title"] == "代码块里的设定"
