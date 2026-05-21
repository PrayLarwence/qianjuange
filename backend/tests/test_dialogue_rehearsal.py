"""P2: 双角色对话演练。"""
from __future__ import annotations
import json
from unittest.mock import patch as _mp

import pytest

from app.providers.base import LLMResponse
from app.models import Entity, NarrativeLog


class FakeProvider:
    def __init__(self, payload):
        self.payload = payload

    def chat(self, system, messages, tools=None, max_tokens=None, temperature=None):
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload, ensure_ascii=False)
        return LLMResponse(text=text, raw={}, usage={})


@pytest.fixture
def fake_dia_provider():
    def _f(payload):
        return _mp("app.engine.agents.dialogue_rehearsal.get_provider", return_value=FakeProvider(payload))
    return _f


def _two(db, branch_id):
    a = Entity(id="ent_a", branch_id=branch_id, name="爱丽丝", type="character",
               summary="谨慎少女", attributes={"性格": "克制"}, alive=1)
    b = Entity(id="ent_b", branch_id=branch_id, name="鲍勃", type="character",
               summary="爽朗剑客", attributes={"性格": "直率"}, alive=1)
    db.add_all([a, b]); db.commit()
    return a, b


def test_rehearse_returns_turns(client, db, world_factory, fake_dia_provider):
    w, br = world_factory()
    a, b = _two(db, br.id)
    payload = {
        "title": "茶馆里的试探",
        "turns": [
            {"speaker_id": a.id, "text": "你为什么来找我？", "beat": "试探"},
            {"speaker_id": b.id, "text": "替老朋友带句话。", "beat": "回避"},
        ],
        "summary": "爱丽丝套不出话来。",
    }
    with fake_dia_provider(payload):
        r = client.post(f"/api/worlds/{w.id}/dialogue/rehearse",
                        json={"actor_a_id": a.id, "actor_b_id": b.id,
                              "scene": "茶馆", "goal": "查口风", "turns": 6})
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "茶馆里的试探"
    assert len(body["turns"]) == 2
    assert {t["speaker_id"] for t in body["turns"]} == {a.id, b.id}
    assert body["actors"][0]["name"] == "爱丽丝"


def test_rehearse_drops_invalid_speaker(client, db, world_factory, fake_dia_provider):
    w, br = world_factory()
    a, b = _two(db, br.id)
    payload = {"turns": [
        {"speaker_id": a.id, "text": "句一"},
        {"speaker_id": "ghost", "text": "鬼说的"},
        {"speaker_id": b.id, "text": "句二"},
        {"speaker_id": a.id, "text": ""},
    ]}
    with fake_dia_provider(payload):
        body = client.post(f"/api/worlds/{w.id}/dialogue/rehearse",
                           json={"actor_a_id": a.id, "actor_b_id": b.id, "turns": 6}).json()
    assert len(body["turns"]) == 2  # ghost 与空文本被丢


def test_rehearse_same_actor_400(client, db, world_factory, fake_dia_provider):
    w, br = world_factory()
    a, _ = _two(db, br.id)
    with fake_dia_provider({"turns": []}):
        r = client.post(f"/api/worlds/{w.id}/dialogue/rehearse",
                        json={"actor_a_id": a.id, "actor_b_id": a.id})
    assert r.status_code == 400


def test_rehearse_unknown_actor_400(client, db, world_factory, fake_dia_provider):
    w, br = world_factory()
    a, _ = _two(db, br.id)
    with fake_dia_provider({"turns": []}):
        r = client.post(f"/api/worlds/{w.id}/dialogue/rehearse",
                        json={"actor_a_id": a.id, "actor_b_id": "nope"})
    assert r.status_code == 400


def test_rehearse_world_404(client, fake_dia_provider):
    with fake_dia_provider({"turns": []}):
        r = client.post("/api/worlds/nope/dialogue/rehearse",
                        json={"actor_a_id": "x", "actor_b_id": "y"})
    assert r.status_code == 404


def test_rehearse_garbage_response(client, db, world_factory, fake_dia_provider):
    w, br = world_factory()
    a, b = _two(db, br.id)
    with fake_dia_provider("not json at all"):
        body = client.post(f"/api/worlds/{w.id}/dialogue/rehearse",
                           json={"actor_a_id": a.id, "actor_b_id": b.id}).json()
    assert body["turns"] == []
    assert body["raw_text"]


def test_rehearse_caps_turns_to_20(client, db, world_factory, fake_dia_provider):
    w, br = world_factory()
    a, b = _two(db, br.id)
    big = {"turns": [
        {"speaker_id": a.id if i % 2 == 0 else b.id, "text": f"句{i}"}
        for i in range(80)
    ]}
    with fake_dia_provider(big):
        body = client.post(f"/api/worlds/{w.id}/dialogue/rehearse",
                           json={"actor_a_id": a.id, "actor_b_id": b.id, "turns": 999}).json()
    # turns 在引擎里被夹到 [3,20]，cap=2*turns=40
    assert len(body["turns"]) <= 40


def test_save_dialogue_creates_narration(client, db, world_factory, fake_dia_provider):
    w, br = world_factory()
    w.current_tick = 4; db.commit()
    a, b = _two(db, br.id)
    payload = {
        "actors": [{"id": a.id, "name": a.name}, {"id": b.id, "name": b.name}],
        "title": "对峙", "summary": "空气凝固",
        "turns": [
            {"speaker_id": a.id, "text": "你走开。", "beat": "拒绝"},
            {"speaker_id": b.id, "text": "我不走。", "beat": "坚持"},
        ],
    }
    r = client.post(f"/api/worlds/{w.id}/dialogue/save", json=payload)
    assert r.status_code == 200
    nl = db.query(NarrativeLog).filter_by(branch_id=br.id, role="dialogue_rehearsal").first()
    assert nl is not None
    assert nl.tick == 4
    assert "爱丽丝" in nl.text and "鲍勃" in nl.text
    assert "对峙" in nl.text
    assert "(拒绝)" in nl.text  # beat 被渲染
    assert "空气凝固" in nl.text  # summary


def test_save_dialogue_empty_400(client, db, world_factory):
    w, _ = world_factory()
    r = client.post(f"/api/worlds/{w.id}/dialogue/save",
                    json={"actors": [], "turns": []})
    assert r.status_code == 400


def test_save_dialogue_world_404(client):
    r = client.post("/api/worlds/nope/dialogue/save",
                    json={"actors": [], "turns": [{"speaker_id": "x", "text": "y"}]})
    assert r.status_code == 404


def test_rehearse_preserves_actor_id_in_response(client, db, world_factory, fake_dia_provider):
    w, br = world_factory()
    a, b = _two(db, br.id)
    payload = {"turns": [{"speaker_id": a.id, "text": "x"}]}
    with fake_dia_provider(payload):
        body = client.post(f"/api/worlds/{w.id}/dialogue/rehearse",
                           json={"actor_a_id": a.id, "actor_b_id": b.id}).json()
    ids = [act["id"] for act in body["actors"]]
    assert a.id in ids and b.id in ids
