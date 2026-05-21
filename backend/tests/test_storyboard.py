"""C2: 章节故事板聚合端点。"""
from __future__ import annotations

from app.models import (
    Entity, Event, ChapterMarker, ConsistencyIssue, PlotThread,
)


def _setup(db, world_factory):
    """两章故事：第一章 tick 1-3 (爱丽丝主),第二章 tick 4-6 (鲍勃登场)。"""
    w, br = world_factory()
    w.current_tick = 6
    db.add_all([
        Entity(id="ent_alice", branch_id=br.id, type="character", name="爱丽丝",
               summary="", attributes={}, state={}, created_at_tick=0, alive=1),
        Entity(id="ent_bob", branch_id=br.id, type="character", name="鲍勃",
               summary="", attributes={}, state={}, created_at_tick=0, alive=1),
        Entity(id="ent_loc", branch_id=br.id, type="location", name="酒馆",
               summary="", attributes={}, state={}, created_at_tick=0, alive=1),
    ])
    db.add_all([
        Event(id="ev1", branch_id=br.id, tick=1, title="开场", description="d1",
              participants=["ent_alice"], consequences=[], metadata_={}, deleted=0),
        Event(id="ev2", branch_id=br.id, tick=2, title="独白", description="d2",
              participants=["ent_alice"], consequences=[], metadata_={}, deleted=0),
        Event(id="ev3", branch_id=br.id, tick=3, title="冲突", description="d3",
              participants=["ent_alice"], consequences=[], metadata_={}, deleted=0),
        Event(id="ev4", branch_id=br.id, tick=4, title="鲍勃出场", description="d4",
              participants=["ent_bob", "ent_alice"], consequences=[], metadata_={}, deleted=0),
        Event(id="ev5", branch_id=br.id, tick=5, title="对峙", description="d5",
              participants=["ent_alice", "ent_bob"], consequences=[], metadata_={}, deleted=0),
        Event(id="ev6", branch_id=br.id, tick=6, title="布景", description="d6",
              participants=["ent_loc"], consequences=[], metadata_={}, deleted=0),
    ])
    db.add_all([
        ChapterMarker(id="ch1", branch_id=br.id, tick=1, title="第一章·序", summary="爱丽丝独行"),
        ChapterMarker(id="ch2", branch_id=br.id, tick=4, title="第二章·相遇", summary="两人相会"),
    ])
    db.add(ConsistencyIssue(
        id="iss_a", world_id=w.id, branch_id=br.id,
        category="character", severity="high", title="性格不一致",
        description="x", suggestion="", entity_ids=["ent_alice"],
        tick_start=2, tick_end=2, status="open",
    ))
    db.add(ConsistencyIssue(
        id="iss_b", world_id=w.id, branch_id=br.id,
        category="plot", severity="low", title="次要瑕疵",
        description="x", suggestion="", entity_ids=[],
        tick_start=5, tick_end=5, status="open",
    ))
    db.add(ConsistencyIssue(
        id="iss_resolved", world_id=w.id, branch_id=br.id,
        category="plot", severity="low", title="已修",
        description="x", suggestion="", entity_ids=[],
        tick_start=2, tick_end=2, status="resolved",
    ))
    db.add_all([
        PlotThread(id="th_open", branch_id=br.id, title="复仇", summary="x",
                   opened_tick=2, closed_tick=None, status="open"),
        PlotThread(id="th_closed", branch_id=br.id, title="寻人", summary="x",
                   opened_tick=1, closed_tick=5, status="closed"),
        PlotThread(id="th_late", branch_id=br.id, title="未启用",
                   summary="x", opened_tick=10, closed_tick=None, status="open"),
    ])
    db.commit()
    return w


def test_storyboard_returns_two_chapters(client, db, world_factory):
    w = _setup(db, world_factory)
    r = client.get(f"/api/worlds/{w.id}/storyboard")
    assert r.status_code == 200
    body = r.json()
    assert body["world_id"] == w.id
    assert body["max_tick"] >= 6
    chapters = body["chapters"]
    assert len(chapters) == 2
    assert chapters[0]["id"] == "ch1"
    assert chapters[0]["title"] == "第一章·序"
    assert chapters[0]["tick_start"] == 1 and chapters[0]["tick_end"] == 3
    assert chapters[1]["id"] == "ch2"
    assert chapters[1]["tick_start"] == 4 and chapters[1]["tick_end"] >= 6


def test_storyboard_chapter_event_partition(client, db, world_factory):
    """事件按 tick 区间归到对应章。"""
    w = _setup(db, world_factory)
    body = client.get(f"/api/worlds/{w.id}/storyboard").json()
    ch1, ch2 = body["chapters"]
    e1_ids = [e["id"] for e in ch1["events"]]
    e2_ids = [e["id"] for e in ch2["events"]]
    assert e1_ids == ["ev1", "ev2", "ev3"]
    assert "ev4" in e2_ids and "ev5" in e2_ids and "ev6" in e2_ids
    assert ch1["event_count"] == 3
    assert ch2["event_count"] == 3


def test_storyboard_characters_freq(client, db, world_factory):
    """章内角色按出场频次排（章 1 只有爱丽丝；章 2 鲍勃和爱丽丝都出现）。"""
    w = _setup(db, world_factory)
    body = client.get(f"/api/worlds/{w.id}/storyboard").json()
    ch1, ch2 = body["chapters"]
    ch1_chars = [c["name"] for c in ch1["characters"]]
    assert ch1_chars == ["爱丽丝"]
    assert ch1["characters"][0]["appearances"] == 3

    ch2_names = {c["name"] for c in ch2["characters"]}
    assert "鲍勃" in ch2_names and "爱丽丝" in ch2_names
    # 地点不算 character
    assert "酒馆" not in ch2_names


def test_storyboard_issues_partition_by_tick(client, db, world_factory):
    """open issue 按 tick_start 落入对应章；resolved 不计。"""
    w = _setup(db, world_factory)
    body = client.get(f"/api/worlds/{w.id}/storyboard").json()
    ch1, ch2 = body["chapters"]
    ch1_iids = [i["id"] for i in ch1["issues"]]
    ch2_iids = [i["id"] for i in ch2["issues"]]
    assert "iss_a" in ch1_iids
    assert "iss_b" in ch2_iids
    assert "iss_resolved" not in ch1_iids and "iss_resolved" not in ch2_iids


def test_storyboard_threads_phases(client, db, world_factory):
    w = _setup(db, world_factory)
    body = client.get(f"/api/worlds/{w.id}/storyboard").json()
    ch1, ch2 = body["chapters"]

    # th_open opened_tick=2 → 章 1 phase=opened；章 2 进行中
    th1 = {t["id"]: t["phase"] for t in ch1["threads"]}
    th2 = {t["id"]: t["phase"] for t in ch2["threads"]}
    assert th1.get("th_open") == "opened"
    assert th2.get("th_open") == "ongoing"

    # th_closed opened=1 章 1 → opened；closed=5 章 2 → closed
    assert th1.get("th_closed") == "opened"
    assert th2.get("th_closed") == "closed"

    # th_late opened=10 不在两章范围 → 不出现
    assert "th_late" not in th1 and "th_late" not in th2


def test_storyboard_top_caps(client, db, world_factory):
    w = _setup(db, world_factory)
    r = client.get(f"/api/worlds/{w.id}/storyboard?top_events=2&top_characters=1")
    body = r.json()
    ch2 = body["chapters"][1]
    assert len(ch2["events"]) == 2
    assert len(ch2["characters"]) == 1


def test_storyboard_no_markers_synthetic_chapter(client, db, world_factory):
    """没有 ChapterMarker 时返回单章 _unmarked 覆盖整个时间线。"""
    w, br = world_factory()
    w.current_tick = 3
    db.add(Entity(id="ent_x", branch_id=br.id, type="character", name="X",
                  summary="", attributes={}, state={}, created_at_tick=0, alive=1))
    db.add(Event(id="ex1", branch_id=br.id, tick=1, title="t", description="",
                 participants=["ent_x"], consequences=[], metadata_={}, deleted=0))
    db.commit()
    body = client.get(f"/api/worlds/{w.id}/storyboard").json()
    assert len(body["chapters"]) == 1
    ch = body["chapters"][0]
    assert ch["id"] == "_unmarked"
    assert ch["is_synthetic"] is True
    assert ch["tick_start"] == 0
    assert ch["event_count"] == 1


def test_storyboard_prologue_when_first_marker_after_zero(client, db, world_factory):
    """首个 marker 不在 tick 0 时插入合成的"序章"。"""
    w, br = world_factory()
    w.current_tick = 5
    db.add(Entity(id="ent_x", branch_id=br.id, type="character", name="X",
                  summary="", attributes={}, state={}, created_at_tick=0, alive=1))
    db.add_all([
        Event(id="e0", branch_id=br.id, tick=0, title="序", description="",
              participants=["ent_x"], consequences=[], metadata_={}, deleted=0),
        Event(id="e1", branch_id=br.id, tick=2, title="正", description="",
              participants=["ent_x"], consequences=[], metadata_={}, deleted=0),
    ])
    db.add(ChapterMarker(id="ch_only", branch_id=br.id, tick=2, title="第一章", summary=""))
    db.commit()
    body = client.get(f"/api/worlds/{w.id}/storyboard").json()
    chs = body["chapters"]
    assert len(chs) == 2
    assert chs[0]["id"] == "_prologue" and chs[0]["is_synthetic"] is True
    assert chs[0]["tick_start"] == 0 and chs[0]["tick_end"] == 1
    assert [e["id"] for e in chs[0]["events"]] == ["e0"]
    assert chs[1]["id"] == "ch_only"


def test_storyboard_world_404(client):
    r = client.get("/api/worlds/nope/storyboard")
    assert r.status_code == 404


def test_storyboard_no_branch_returns_empty(client, db, world_factory):
    w, br = world_factory()
    w.active_branch_id = None
    db.commit()
    body = client.get(f"/api/worlds/{w.id}/storyboard").json()
    assert body["chapters"] == []
