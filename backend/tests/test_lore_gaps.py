"""B7: lore 缺口扫描端到端。"""
from __future__ import annotations
from unittest.mock import patch as _mp

import pytest

from app.providers.base import LLMResponse
from app.models import Entity, Event, NarrativeLog, WorldLore


class FakeProvider:
    def __init__(self, payload):
        self.payload = payload

    def chat(self, system, messages, tools=None, max_tokens=None, temperature=None):
        import json
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload, ensure_ascii=False)
        return LLMResponse(text=text, raw={}, usage={})


@pytest.fixture
def fake_lore_provider():
    def _f(payload):
        return _mp("app.engine.worldgen.lore_gaps.get_provider", return_value=FakeProvider(payload))
    return _f


def _setup(db, world_factory):
    w, br = world_factory()
    w.current_tick = 5
    db.add_all([
        Entity(id="ent_alice", branch_id=br.id, type="character", name="爱丽丝",
               summary="", attributes={}, state={}, created_at_tick=0, alive=1),
    ])
    db.add_all([
        Event(id="e1", branch_id=br.id, tick=1, title="爱丽丝抵达紫霜城",
              description="她带着银钥匙走进城门", participants=["ent_alice"],
              consequences=[], metadata_={}, deleted=0),
        Event(id="e2", branch_id=br.id, tick=2, title="紫霜城议会接见",
              description="议会成员对银钥匙感到震惊", participants=["ent_alice"],
              consequences=[], metadata_={}, deleted=0),
    ])
    db.add(NarrativeLog(id="n1", branch_id=br.id, tick=2, role="narrator",
                        text="紫霜城千年来无人持有银钥匙。"))
    db.add(WorldLore(id="lore_existing", world_id=w.id, category="setting",
                     title="爱丽丝", content="主角", priority=10, pinned=0))
    db.commit()
    return w, br


def test_scan_gaps_basic(client, db, world_factory, fake_lore_provider):
    w, _ = _setup(db, world_factory)
    payload = {"gaps": [
        {"name": "紫霜城", "kind": "location",
         "mentions": ["爱丽丝抵达紫霜城", "紫霜城议会接见"],
         "reason": "反复出现的地点但无设定", "suggested_summary": "古老的城市"},
        {"name": "银钥匙", "kind": "item",
         "mentions": ["她带着银钥匙", "议会对银钥匙感到震惊"],
         "reason": "关键物品", "suggested_summary": "象征权力的钥匙"},
    ]}
    with fake_lore_provider(payload):
        r = client.post(f"/api/worlds/{w.id}/lore/scan_gaps", json={})
    assert r.status_code == 200
    body = r.json()
    names = [g["name"] for g in body["gaps"]]
    assert "紫霜城" in names and "银钥匙" in names
    assert body["scanned"]["events"] == 2
    assert body["scanned"]["narrations"] == 1


def test_scan_gaps_filters_existing_lore_and_entities(client, db, world_factory, fake_lore_provider):
    """模型若返回已知名（爱丽丝），后端二次过滤。"""
    w, _ = _setup(db, world_factory)
    payload = {"gaps": [
        {"name": "爱丽丝", "kind": "person", "mentions": [], "reason": "x", "suggested_summary": "y"},
        {"name": "紫霜城", "kind": "location", "mentions": [], "reason": "x", "suggested_summary": "y"},
    ]}
    with fake_lore_provider(payload):
        body = client.post(f"/api/worlds/{w.id}/lore/scan_gaps", json={}).json()
    names = [g["name"] for g in body["gaps"]]
    assert "爱丽丝" not in names
    assert "紫霜城" in names


def test_scan_gaps_invalid_kind_normalizes(client, db, world_factory, fake_lore_provider):
    w, _ = _setup(db, world_factory)
    payload = {"gaps": [
        {"name": "禁忌", "kind": "weird_kind", "mentions": [], "reason": "", "suggested_summary": ""},
    ]}
    with fake_lore_provider(payload):
        body = client.post(f"/api/worlds/{w.id}/lore/scan_gaps", json={}).json()
    assert body["gaps"][0]["kind"] == "concept"


def test_scan_gaps_dedupes_by_name(client, db, world_factory, fake_lore_provider):
    w, _ = _setup(db, world_factory)
    payload = {"gaps": [
        {"name": "紫霜城", "kind": "location", "mentions": [], "reason": "", "suggested_summary": ""},
        {"name": "紫霜城", "kind": "concept", "mentions": [], "reason": "", "suggested_summary": ""},
    ]}
    with fake_lore_provider(payload):
        body = client.post(f"/api/worlds/{w.id}/lore/scan_gaps", json={}).json()
    assert len([g for g in body["gaps"] if g["name"] == "紫霜城"]) == 1


def test_scan_gaps_respects_max_gaps(client, db, world_factory, fake_lore_provider):
    w, _ = _setup(db, world_factory)
    payload = {"gaps": [
        {"name": f"名词{i}", "kind": "concept", "mentions": [], "reason": "", "suggested_summary": ""}
        for i in range(10)
    ]}
    with fake_lore_provider(payload):
        body = client.post(f"/api/worlds/{w.id}/lore/scan_gaps", json={"max_gaps": 3}).json()
    assert len(body["gaps"]) == 3


def test_scan_gaps_handles_garbage_response(client, db, world_factory, fake_lore_provider):
    w, _ = _setup(db, world_factory)
    with fake_lore_provider("not a json at all"):
        body = client.post(f"/api/worlds/{w.id}/lore/scan_gaps", json={}).json()
    assert body["gaps"] == []


def test_scan_gaps_empty_when_no_branch(client, db, world_factory):
    w, br = world_factory()
    w.active_branch_id = None
    db.commit()
    body = client.post(f"/api/worlds/{w.id}/lore/scan_gaps", json={}).json()
    assert body["gaps"] == []


def test_scan_gaps_empty_when_no_material(client, db, world_factory, fake_lore_provider):
    """没有 events 也没有 narration → 直接空，不调 LLM。"""
    w, br = world_factory()
    db.commit()
    payload = {"gaps": [{"name": "x", "kind": "concept", "mentions": [], "reason": "", "suggested_summary": ""}]}
    # provider 即便给了，也不该被消费
    with fake_lore_provider(payload):
        body = client.post(f"/api/worlds/{w.id}/lore/scan_gaps", json={}).json()
    assert body["gaps"] == []
    assert body["scanned"]["events"] == 0


def test_scan_gaps_world_404(client):
    r = client.post("/api/worlds/nope/lore/scan_gaps", json={})
    assert r.status_code == 404


def test_scan_gaps_truncates_long_fields(client, db, world_factory, fake_lore_provider):
    w, _ = _setup(db, world_factory)
    payload = {"gaps": [
        {"name": "短名", "kind": "concept",
         "mentions": ["m" * 500],
         "reason": "r" * 500, "suggested_summary": "s" * 700},
    ]}
    with fake_lore_provider(payload):
        body = client.post(f"/api/worlds/{w.id}/lore/scan_gaps", json={}).json()
    g = body["gaps"][0]
    assert len(g["mentions"][0]) <= 200
    assert len(g["reason"]) <= 300
    assert len(g["suggested_summary"]) <= 500


def test_scan_gaps_drops_too_long_name(client, db, world_factory, fake_lore_provider):
    w, _ = _setup(db, world_factory)
    payload = {"gaps": [
        {"name": "x" * 80, "kind": "concept", "mentions": [], "reason": "", "suggested_summary": ""},
        {"name": "好名", "kind": "concept", "mentions": [], "reason": "", "suggested_summary": ""},
    ]}
    with fake_lore_provider(payload):
        body = client.post(f"/api/worlds/{w.id}/lore/scan_gaps", json={}).json()
    names = [g["name"] for g in body["gaps"]]
    assert "好名" in names
    assert all(len(n) <= 60 for n in names)
