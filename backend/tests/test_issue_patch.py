"""A 收尾：editor 建议 patch 端到端。"""
from __future__ import annotations
from unittest.mock import patch as _mp
import pytest

from app.providers.base import LLMResponse
from app.models import (
    Entity, Event, NarrativeLog, ConsistencyIssue, IssuePatch,
)


def _setup(db, world_factory):
    w, br = world_factory()
    w.current_tick = 5
    db.add(Entity(id="ent_a", branch_id=br.id, type="character", name="阿离",
                  summary="少年", attributes={}, state={}, created_at_tick=0, alive=1))
    db.add_all([
        Event(id="ev1", branch_id=br.id, tick=2, title="阿离冲到酒馆", description="阿离冲进店里",
              participants=["ent_a"], consequences=[], metadata_={}, deleted=0),
        Event(id="ev2", branch_id=br.id, tick=3, title="掌柜出言劝阻", description="老掌柜走过来",
              participants=["ent_a"], consequences=[], metadata_={}, deleted=0),
    ])
    db.add(NarrativeLog(
        id="n2", branch_id=br.id, tick=2, role="narrator",
        text="她流泪了，转身离开了酒馆。",
    ))
    db.add(NarrativeLog(
        id="n3", branch_id=br.id, tick=3, role="narrator",
        text="老掌柜叹了口气。",
    ))
    iss = ConsistencyIssue(
        id="iss_a", world_id=w.id, branch_id=br.id,
        category="character", severity="medium",
        title="情绪不一致", description="阿离前文表现愤怒，此处应为攥拳而非流泪",
        suggestion="把'流泪'改成'攥拳'", entity_ids=["ent_a"],
        tick_start=2, tick_end=3, status="open",
    )
    db.add(iss)
    db.commit()
    return w, br, iss


class FakePatchProvider:
    """返回预设 JSON 的 provider。"""
    def __init__(self, payload: dict | str):
        self.payload = payload

    def chat(self, system, messages, tools=None, max_tokens=None, temperature=None):
        import json
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload, ensure_ascii=False)
        return LLMResponse(text=text, raw={}, usage={})


@pytest.fixture
def fake_provider_factory():
    def _f(payload):
        fp = FakePatchProvider(payload)
        return _mp("app.engine.consistency.patch.get_provider", return_value=fp)
    return _f


# ---------- suggest ----------

def test_suggest_patch_creates_pending(client, db, world_factory, fake_provider_factory):
    w, br, iss = _setup(db, world_factory)
    payload = {"patches": [
        {"target_kind": "narration", "target_id": "n2",
         "before_excerpt": "她流泪了", "after_text": "她攥紧了拳",
         "rationale": "保持愤怒情绪一致"},
    ]}
    with fake_provider_factory(payload):
        r = client.post(f"/api/issues/{iss.id}/suggest_patch", json={})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["created"] == 1
    p = data["patches"][0]
    assert p["status"] == "pending"
    assert p["target_id"] == "n2"
    assert p["after_text"] == "她攥紧了拳"

    # 已经入库
    rows = db.query(IssuePatch).filter_by(issue_id=iss.id).all()
    assert len(rows) == 1


def test_suggest_patch_rejects_invalid_target(client, db, world_factory, fake_provider_factory):
    """target_id 不存在的 patch 应被丢弃。"""
    w, br, iss = _setup(db, world_factory)
    payload = {"patches": [
        {"target_kind": "narration", "target_id": "n_NOPE",
         "before_excerpt": "x", "after_text": "y", "rationale": "x"},
        {"target_kind": "narration", "target_id": "n2",
         "before_excerpt": "她流泪了", "after_text": "她攥紧了拳", "rationale": "ok"},
    ]}
    with fake_provider_factory(payload):
        r = client.post(f"/api/issues/{iss.id}/suggest_patch", json={})
    assert r.json()["created"] == 1


def test_suggest_patch_rejects_missing_before_excerpt(client, db, world_factory, fake_provider_factory):
    """before_excerpt 不在原文中应被丢弃。"""
    w, br, iss = _setup(db, world_factory)
    payload = {"patches": [
        {"target_kind": "narration", "target_id": "n2",
         "before_excerpt": "完全不在原文里的句子", "after_text": "y", "rationale": "x"},
    ]}
    with fake_provider_factory(payload):
        r = client.post(f"/api/issues/{iss.id}/suggest_patch", json={})
    assert r.json()["created"] == 0


def test_suggest_patch_rejects_after_equals_before(client, db, world_factory, fake_provider_factory):
    w, br, iss = _setup(db, world_factory)
    payload = {"patches": [
        {"target_kind": "narration", "target_id": "n2",
         "before_excerpt": "她流泪了", "after_text": "她流泪了", "rationale": "noop"},
    ]}
    with fake_provider_factory(payload):
        r = client.post(f"/api/issues/{iss.id}/suggest_patch", json={})
    assert r.json()["created"] == 0


def test_suggest_patch_404_for_missing_issue(client):
    r = client.post("/api/issues/nope/suggest_patch", json={})
    assert r.status_code == 404


# ---------- list ----------

def test_list_patches(client, db, world_factory, fake_provider_factory):
    w, br, iss = _setup(db, world_factory)
    payload = {"patches": [
        {"target_kind": "narration", "target_id": "n2",
         "before_excerpt": "她流泪了", "after_text": "她攥紧了拳", "rationale": "ok"},
    ]}
    with fake_provider_factory(payload):
        client.post(f"/api/issues/{iss.id}/suggest_patch", json={})
    r = client.get(f"/api/issues/{iss.id}/patches")
    assert r.status_code == 200
    assert len(r.json()["patches"]) == 1


# ---------- apply ----------

def test_apply_patch_modifies_narration_and_marks_applied(client, db, world_factory, fake_provider_factory):
    w, br, iss = _setup(db, world_factory)
    payload = {"patches": [
        {"target_kind": "narration", "target_id": "n2",
         "before_excerpt": "她流泪了", "after_text": "她攥紧了拳", "rationale": "ok"},
    ]}
    with fake_provider_factory(payload):
        sr = client.post(f"/api/issues/{iss.id}/suggest_patch", json={})
    pid = sr.json()["patches"][0]["id"]

    r = client.post(f"/api/issue_patches/{pid}/apply")
    assert r.status_code == 200
    assert r.json()["patch"]["status"] == "applied"
    db.expire_all()
    n2 = db.query(NarrativeLog).filter_by(id="n2").first()
    assert "她攥紧了拳" in n2.text
    assert "她流泪了" not in n2.text
    # 其它部分保留
    assert "转身离开了酒馆" in n2.text


def test_apply_patch_event_title(client, db, world_factory, fake_provider_factory):
    w, br, iss = _setup(db, world_factory)
    payload = {"patches": [
        {"target_kind": "event_title", "target_id": "ev1",
         "before_excerpt": "冲到", "after_text": "踏进", "rationale": "调整动作强度"},
    ]}
    with fake_provider_factory(payload):
        sr = client.post(f"/api/issues/{iss.id}/suggest_patch", json={})
    pid = sr.json()["patches"][0]["id"]
    client.post(f"/api/issue_patches/{pid}/apply")
    db.expire_all()
    ev = db.query(Event).filter_by(id="ev1").first()
    assert ev.title == "阿离踏进酒馆"


def test_apply_patch_twice_rejects(client, db, world_factory, fake_provider_factory):
    w, br, iss = _setup(db, world_factory)
    payload = {"patches": [
        {"target_kind": "narration", "target_id": "n2",
         "before_excerpt": "她流泪了", "after_text": "她攥紧了拳", "rationale": "ok"},
    ]}
    with fake_provider_factory(payload):
        sr = client.post(f"/api/issues/{iss.id}/suggest_patch", json={})
    pid = sr.json()["patches"][0]["id"]
    client.post(f"/api/issue_patches/{pid}/apply")
    r2 = client.post(f"/api/issue_patches/{pid}/apply")
    assert r2.status_code == 400


# ---------- reject ----------

def test_reject_patch(client, db, world_factory, fake_provider_factory):
    w, br, iss = _setup(db, world_factory)
    payload = {"patches": [
        {"target_kind": "narration", "target_id": "n2",
         "before_excerpt": "她流泪了", "after_text": "她攥紧了拳", "rationale": "ok"},
    ]}
    with fake_provider_factory(payload):
        sr = client.post(f"/api/issues/{iss.id}/suggest_patch", json={})
    pid = sr.json()["patches"][0]["id"]
    r = client.post(f"/api/issue_patches/{pid}/reject")
    assert r.status_code == 200
    assert r.json()["patch"]["status"] == "rejected"
    # 不能再 apply
    r2 = client.post(f"/api/issue_patches/{pid}/apply")
    assert r2.status_code == 400


def test_apply_404(client):
    r = client.post("/api/issue_patches/nope/apply")
    assert r.status_code == 404


# ---------- A2: undo ----------

def _suggest_one(client, db, world_factory, fake_provider_factory, after="她攥紧了拳"):
    w, br, iss = _setup(db, world_factory)
    payload = {"patches": [
        {"target_kind": "narration", "target_id": "n2",
         "before_excerpt": "她流泪了", "after_text": after, "rationale": "ok"},
    ]}
    with fake_provider_factory(payload):
        sr = client.post(f"/api/issues/{iss.id}/suggest_patch", json={})
    return iss, sr.json()["patches"][0]["id"]


def test_undo_restores_narration_text(client, db, world_factory, fake_provider_factory):
    iss, pid = _suggest_one(client, db, world_factory, fake_provider_factory)
    client.post(f"/api/issue_patches/{pid}/apply")

    db.expire_all()
    n2 = db.query(NarrativeLog).filter_by(id="n2").first()
    assert "她攥紧了拳" in n2.text  # 已改

    r = client.post(f"/api/issue_patches/{pid}/undo")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["patch"]["status"] == "pending"
    assert body["patch"]["can_undo"] is False
    assert body["patch"]["applied_at"] is None

    db.expire_all()
    n2 = db.query(NarrativeLog).filter_by(id="n2").first()
    assert n2.text == "她流泪了，转身离开了酒馆。"  # 还原


def test_undo_then_reapply(client, db, world_factory, fake_provider_factory):
    """undo 后 patch 回到 pending，可以再次 apply。"""
    iss, pid = _suggest_one(client, db, world_factory, fake_provider_factory)
    client.post(f"/api/issue_patches/{pid}/apply")
    client.post(f"/api/issue_patches/{pid}/undo")
    r = client.post(f"/api/issue_patches/{pid}/apply")
    assert r.status_code == 200
    db.expire_all()
    n2 = db.query(NarrativeLog).filter_by(id="n2").first()
    assert "她攥紧了拳" in n2.text


def test_undo_pending_rejected(client, db, world_factory, fake_provider_factory):
    """pending 状态不能 undo。"""
    iss, pid = _suggest_one(client, db, world_factory, fake_provider_factory)
    r = client.post(f"/api/issue_patches/{pid}/undo")
    assert r.status_code == 400


def test_undo_after_reject_rejected(client, db, world_factory, fake_provider_factory):
    iss, pid = _suggest_one(client, db, world_factory, fake_provider_factory)
    client.post(f"/api/issue_patches/{pid}/reject")
    r = client.post(f"/api/issue_patches/{pid}/undo")
    assert r.status_code == 400


def test_undo_404(client):
    r = client.post("/api/issue_patches/nope/undo")
    assert r.status_code == 404


def test_undo_event_title(client, db, world_factory, fake_provider_factory):
    w, br, iss = _setup(db, world_factory)
    payload = {"patches": [
        {"target_kind": "event_title", "target_id": "ev1",
         "before_excerpt": "冲到", "after_text": "踏进", "rationale": "x"},
    ]}
    with fake_provider_factory(payload):
        sr = client.post(f"/api/issues/{iss.id}/suggest_patch", json={})
    pid = sr.json()["patches"][0]["id"]
    client.post(f"/api/issue_patches/{pid}/apply")
    db.expire_all()
    assert db.query(Event).filter_by(id="ev1").first().title == "阿离踏进酒馆"
    client.post(f"/api/issue_patches/{pid}/undo")
    db.expire_all()
    assert db.query(Event).filter_by(id="ev1").first().title == "阿离冲到酒馆"


def test_undo_lifo_two_patches_same_target(client, db, world_factory, fake_provider_factory):
    """两个 patch 先后 apply 到同一 narration，按 LIFO undo 能层层还原。"""
    w, br, iss = _setup(db, world_factory)
    p1 = {"patches": [{"target_kind": "narration", "target_id": "n2",
                       "before_excerpt": "她流泪了", "after_text": "她攥拳", "rationale": "ok"}]}
    with fake_provider_factory(p1):
        r1 = client.post(f"/api/issues/{iss.id}/suggest_patch", json={})
    pid1 = r1.json()["patches"][0]["id"]
    client.post(f"/api/issue_patches/{pid1}/apply")
    # 第二个 patch 改另一处
    p2 = {"patches": [{"target_kind": "narration", "target_id": "n2",
                       "before_excerpt": "转身离开", "after_text": "夺门而出", "rationale": "ok"}]}
    with fake_provider_factory(p2):
        r2 = client.post(f"/api/issues/{iss.id}/suggest_patch", json={})
    pid2 = r2.json()["patches"][0]["id"]
    client.post(f"/api/issue_patches/{pid2}/apply")

    db.expire_all()
    text_after_both = db.query(NarrativeLog).filter_by(id="n2").first().text
    assert "她攥拳" in text_after_both and "夺门而出" in text_after_both

    # LIFO：先 undo p2 → 还原到只有 p1 应用的状态
    client.post(f"/api/issue_patches/{pid2}/undo")
    db.expire_all()
    t1 = db.query(NarrativeLog).filter_by(id="n2").first().text
    assert "她攥拳" in t1
    assert "夺门而出" not in t1
    assert "转身离开" in t1

    # 再 undo p1 → 完全还原
    client.post(f"/api/issue_patches/{pid1}/undo")
    db.expire_all()
    t0 = db.query(NarrativeLog).filter_by(id="n2").first().text
    assert t0 == "她流泪了，转身离开了酒馆。"


# ---------- A3: 批量改稿建议 ----------

def _setup_two_issues(db, world_factory):
    """两个 open issue：iss_a 涉及 n2，iss_b 涉及 n3。"""
    w, br = world_factory()
    w.current_tick = 5
    db.add(Entity(id="ent_a", branch_id=br.id, type="character", name="阿离",
                  summary="少年", attributes={}, state={}, created_at_tick=0, alive=1))
    db.add_all([
        Event(id="ev1", branch_id=br.id, tick=2, title="冲到酒馆", description="",
              participants=["ent_a"], consequences=[], metadata_={}, deleted=0),
        Event(id="ev2", branch_id=br.id, tick=3, title="掌柜劝阻", description="",
              participants=["ent_a"], consequences=[], metadata_={}, deleted=0),
    ])
    db.add_all([
        NarrativeLog(id="n2", branch_id=br.id, tick=2, role="narrator",
                     text="她流泪了，转身离开了酒馆。"),
        NarrativeLog(id="n3", branch_id=br.id, tick=3, role="narrator",
                     text="老掌柜叹了口气。"),
    ])
    db.add_all([
        ConsistencyIssue(id="iss_a", world_id=w.id, branch_id=br.id,
                         category="character", severity="medium",
                         title="情绪不一致 A", description="x", suggestion="x",
                         entity_ids=["ent_a"], tick_start=2, tick_end=2, status="open"),
        ConsistencyIssue(id="iss_b", world_id=w.id, branch_id=br.id,
                         category="character", severity="low",
                         title="情绪不一致 B", description="y", suggestion="y",
                         entity_ids=["ent_a"], tick_start=3, tick_end=3, status="open"),
    ])
    db.commit()
    return w


def test_batch_suggest_processes_all_open(client, db, world_factory, fake_provider_factory):
    w = _setup_two_issues(db, world_factory)
    payload = {"patches": [
        {"target_kind": "narration", "target_id": "n2",
         "before_excerpt": "她流泪了", "after_text": "她攥拳", "rationale": "x"},
    ]}
    with fake_provider_factory(payload):
        # 注意：此测试里所有 issue 都会用同一个 mock 返回，所以 iss_b 也会收到
        # n2 patch — 这是合理的（fake provider 不区分），但 iss_b tick=3 ± 1，n2 tick=2 在范围里
        r = client.post(f"/api/worlds/{w.id}/issues/suggest_all_patches", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_open"] == 2
    assert body["processed"] == 2
    assert body["total_created"] == 2  # 每个 issue 1 个 patch
    assert len(body["results"]) == 2
    assert all(rr["ok"] for rr in body["results"])


def test_batch_suggest_skips_existing(client, db, world_factory, fake_provider_factory):
    w = _setup_two_issues(db, world_factory)
    payload = {"patches": [
        {"target_kind": "narration", "target_id": "n2",
         "before_excerpt": "她流泪了", "after_text": "她攥拳", "rationale": "x"},
    ]}
    # 先给 iss_a 单独生成一次
    with fake_provider_factory(payload):
        client.post("/api/issues/iss_a/suggest_patch", json={})
    # 批量时应只处理 iss_b
    with fake_provider_factory(payload):
        r = client.post(f"/api/worlds/{w.id}/issues/suggest_all_patches",
                        json={"skip_existing": True})
    body = r.json()
    assert body["processed"] == 1
    assert body["skipped_existing"] == 1
    assert body["results"][0]["issue_id"] == "iss_b"


def test_batch_suggest_no_skip_when_disabled(client, db, world_factory, fake_provider_factory):
    w = _setup_two_issues(db, world_factory)
    payload = {"patches": [
        {"target_kind": "narration", "target_id": "n2",
         "before_excerpt": "她流泪了", "after_text": "她攥拳", "rationale": "x"},
    ]}
    with fake_provider_factory(payload):
        client.post("/api/issues/iss_a/suggest_patch", json={})
    with fake_provider_factory(payload):
        r = client.post(f"/api/worlds/{w.id}/issues/suggest_all_patches",
                        json={"skip_existing": False})
    body = r.json()
    assert body["processed"] == 2
    assert body["skipped_existing"] == 0


def test_batch_suggest_respects_limit(client, db, world_factory, fake_provider_factory):
    w = _setup_two_issues(db, world_factory)
    payload = {"patches": [
        {"target_kind": "narration", "target_id": "n2",
         "before_excerpt": "她流泪了", "after_text": "她攥拳", "rationale": "x"},
    ]}
    with fake_provider_factory(payload):
        r = client.post(f"/api/worlds/{w.id}/issues/suggest_all_patches",
                        json={"limit": 1})
    body = r.json()
    assert body["processed"] == 1
    assert body["total_open"] == 2


def test_batch_suggest_isolates_failures(client, db, world_factory, monkeypatch):
    """单个 issue 的 LLM 异常不影响其它 issue。"""
    from app.engine import patch as patch_mod

    w = _setup_two_issues(db, world_factory)
    call_count = {"n": 0}
    real_suggest = patch_mod.suggest_patches_for_issue

    def flaky(db_, world_, issue_, **kwargs):
        call_count["n"] += 1
        if issue_.id == "iss_a":
            raise RuntimeError("boom")
        return []  # iss_b 返回空 patch 不算失败

    monkeypatch.setattr(patch_mod, "suggest_patches_for_issue", flaky)
    # routes.py 使用的是 from ..engine.patch import suggest_patches_for_issue
    # 也要打到 routes 模块里
    from app.api import routes as routes_mod
    monkeypatch.setattr(routes_mod, "suggest_patches_for_issue", flaky, raising=False)

    r = client.post(f"/api/worlds/{w.id}/issues/suggest_all_patches", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["processed"] == 2
    oks = [rr["ok"] for rr in body["results"]]
    assert oks.count(True) == 1 and oks.count(False) == 1
    fail = next(rr for rr in body["results"] if not rr["ok"])
    assert "boom" in fail["error"]


def test_batch_suggest_world_404(client):
    r = client.post("/api/worlds/nope/issues/suggest_all_patches", json={})
    assert r.status_code == 404


# ---------- A4: preview ----------

def test_preview_narration_excerpt_match(client, db, world_factory, fake_provider_factory):
    w, br, iss = _setup(db, world_factory)
    payload = {"patches": [
        {"target_kind": "narration", "target_id": "n2",
         "before_excerpt": "她流泪了", "after_text": "她攥紧了拳", "rationale": "x"},
    ]}
    with fake_provider_factory(payload):
        sr = client.post(f"/api/issues/{iss.id}/suggest_patch", json={})
    pid = sr.json()["patches"][0]["id"]

    r = client.get(f"/api/issue_patches/{pid}/preview")
    assert r.status_code == 200
    body = r.json()
    assert body["found_target"] is True
    assert body["excerpt_match"] is True
    assert body["original"] == "她流泪了，转身离开了酒馆。"
    assert body["replaced"] == "她攥紧了拳，转身离开了酒馆。"
    assert body["before_context"] == ""  # 命中位置在开头
    assert body["original_changed"] == "她流泪了"
    assert body["new_changed"] == "她攥紧了拳"
    assert body["after_context"] == "，转身离开了酒馆。"
    # patch 状态没变（只是预览）
    db.expire_all()
    from app.models import IssuePatch
    p = db.query(IssuePatch).filter_by(id=pid).first()
    assert p.status == "pending"


def test_preview_excerpt_in_middle(client, db, world_factory, fake_provider_factory):
    """命中位置不在开头 → before_context 非空。"""
    w, br, iss = _setup(db, world_factory)
    payload = {"patches": [
        {"target_kind": "narration", "target_id": "n2",
         "before_excerpt": "转身离开", "after_text": "夺门而出", "rationale": "x"},
    ]}
    with fake_provider_factory(payload):
        sr = client.post(f"/api/issues/{iss.id}/suggest_patch", json={})
    pid = sr.json()["patches"][0]["id"]
    body = client.get(f"/api/issue_patches/{pid}/preview").json()
    assert body["excerpt_match"] is True
    assert body["before_context"] == "她流泪了，"
    assert body["after_context"] == "了酒馆。"
    assert body["replaced"] == "她流泪了，夺门而出了酒馆。"


def test_preview_excerpt_no_match_falls_back_to_full_replace(client, db, world_factory, fake_provider_factory, monkeypatch):
    """before_excerpt 不在原文 → preview 反映"整段替换"语义（apply 也是这么做的）。"""
    w, br, iss = _setup(db, world_factory)
    payload = {"patches": [
        {"target_kind": "narration", "target_id": "n2",
         "before_excerpt": "她流泪了", "after_text": "新文本", "rationale": "x"},
    ]}
    with fake_provider_factory(payload):
        sr = client.post(f"/api/issues/{iss.id}/suggest_patch", json={})
    pid = sr.json()["patches"][0]["id"]
    # 手动让 narration 文本与 excerpt 不匹配
    db.query(NarrativeLog).filter_by(id="n2").update({"text": "完全无关的内容"})
    db.commit()

    body = client.get(f"/api/issue_patches/{pid}/preview").json()
    assert body["found_target"] is True
    assert body["excerpt_match"] is False
    assert body["original"] == "完全无关的内容"
    assert body["replaced"] == "新文本"
    assert body["original_changed"] == "完全无关的内容"  # 整段算改动
    assert body["new_changed"] == "新文本"
    assert body["before_context"] == "" and body["after_context"] == ""


def test_preview_event_title(client, db, world_factory, fake_provider_factory):
    w, br, iss = _setup(db, world_factory)
    payload = {"patches": [
        {"target_kind": "event_title", "target_id": "ev1",
         "before_excerpt": "冲到", "after_text": "踏进", "rationale": "x"},
    ]}
    with fake_provider_factory(payload):
        sr = client.post(f"/api/issues/{iss.id}/suggest_patch", json={})
    pid = sr.json()["patches"][0]["id"]
    body = client.get(f"/api/issue_patches/{pid}/preview").json()
    assert body["target_kind"] == "event_title"
    assert body["original"] == "阿离冲到酒馆"
    assert body["replaced"] == "阿离踏进酒馆"


def test_preview_event_description(client, db, world_factory, fake_provider_factory):
    w, br, iss = _setup(db, world_factory)
    payload = {"patches": [
        {"target_kind": "event_description", "target_id": "ev1",
         "before_excerpt": "冲进", "after_text": "踏进", "rationale": "x"},
    ]}
    with fake_provider_factory(payload):
        sr = client.post(f"/api/issues/{iss.id}/suggest_patch", json={})
    pid = sr.json()["patches"][0]["id"]
    body = client.get(f"/api/issue_patches/{pid}/preview").json()
    assert body["original"] == "阿离冲进店里"
    assert body["replaced"] == "阿离踏进店里"


def test_preview_after_apply_shows_already_replaced_state(client, db, world_factory, fake_provider_factory):
    """apply 后再 preview：original 已是替换后文本，excerpt 不再命中。"""
    w, br, iss = _setup(db, world_factory)
    payload = {"patches": [
        {"target_kind": "narration", "target_id": "n2",
         "before_excerpt": "她流泪了", "after_text": "她攥拳", "rationale": "x"},
    ]}
    with fake_provider_factory(payload):
        sr = client.post(f"/api/issues/{iss.id}/suggest_patch", json={})
    pid = sr.json()["patches"][0]["id"]
    client.post(f"/api/issue_patches/{pid}/apply")

    body = client.get(f"/api/issue_patches/{pid}/preview").json()
    assert body["original"] == "她攥拳，转身离开了酒馆。"
    assert body["excerpt_match"] is False  # 原 excerpt 已被替换


def test_preview_target_missing(client, db, world_factory, fake_provider_factory):
    w, br, iss = _setup(db, world_factory)
    payload = {"patches": [
        {"target_kind": "narration", "target_id": "n2",
         "before_excerpt": "她流泪了", "after_text": "x", "rationale": "x"},
    ]}
    with fake_provider_factory(payload):
        sr = client.post(f"/api/issues/{iss.id}/suggest_patch", json={})
    pid = sr.json()["patches"][0]["id"]
    db.query(NarrativeLog).filter_by(id="n2").delete()
    db.commit()
    body = client.get(f"/api/issue_patches/{pid}/preview").json()
    assert body["found_target"] is False
    assert body["original"] == ""


def test_preview_404(client):
    r = client.get("/api/issue_patches/nope/preview")
    assert r.status_code == 404
