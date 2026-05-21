"""C1: timeline swimlane 聚合端点。"""
from __future__ import annotations
import uuid

from app.models import (
    Entity, Event, ChapterMarker, ConsistencyIssue, PlotThread,
)


def _setup_world(db, world_factory, with_threads=True):
    w, br = world_factory()
    w.current_tick = 10
    db.add_all([
        Entity(id="ent_alice", branch_id=br.id, type="character", name="爱丽丝",
               summary="少女", attributes={}, state={}, created_at_tick=0, alive=1),
        Entity(id="ent_bob", branch_id=br.id, type="character", name="鲍勃",
               summary="少年", attributes={}, state={}, created_at_tick=0, alive=1),
        Entity(id="ent_loc", branch_id=br.id, type="location", name="酒馆",
               summary="", attributes={}, state={}, created_at_tick=0, alive=1),
    ])
    # 爱丽丝 4 个事件，鲍勃 2 个；地点不该出现在 lane
    db.add_all([
        Event(id="ev1", branch_id=br.id, tick=1, title="开场", description="x",
              participants=["ent_alice"], consequences=[], metadata_={}, deleted=0),
        Event(id="ev2", branch_id=br.id, tick=2, title="相遇", description="x",
              participants=["ent_alice", "ent_bob"], consequences=[], metadata_={}, deleted=0),
        Event(id="ev3", branch_id=br.id, tick=3, title="争吵", description="x",
              participants=["ent_alice", "ent_bob"], consequences=[], metadata_={}, deleted=0),
        Event(id="ev4", branch_id=br.id, tick=4, title="独白", description="x",
              participants=["ent_alice"], consequences=[], metadata_={}, deleted=0),
        # 此事件的 location 出现在 participants—不计入 character lane
        Event(id="ev5", branch_id=br.id, tick=5, title="布景", description="x",
              participants=["ent_loc"], consequences=[], metadata_={}, deleted=0),
    ])
    db.add(ChapterMarker(id="ch_1", branch_id=br.id, tick=4, title="第一章", summary="开始"))
    db.add(ConsistencyIssue(
        id="iss_1", world_id=w.id, branch_id=br.id,
        category="character", severity="high", title="性格不一致",
        description="x", suggestion="", entity_ids=["ent_alice"],
        tick_start=3, tick_end=3, status="open",
    ))
    if with_threads:
        db.add(PlotThread(
            id="th_1", branch_id=br.id, title="未兑现的承诺", summary="x",
            opened_tick=2, closed_tick=None, status="open", related_entity_ids=[],
        ))
    db.commit()
    return w, br


def test_swimlane_basic_shape(client, db, world_factory):
    w, _ = _setup_world(db, world_factory)
    r = client.get(f"/api/worlds/{w.id}/swimlane")
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) >= {
        "max_tick", "lanes", "global_chapters", "global_issues", "global_threads",
    }
    assert data["max_tick"] >= 5


def test_swimlane_lanes_only_characters_sorted_by_frequency(client, db, world_factory):
    w, _ = _setup_world(db, world_factory)
    data = client.get(f"/api/worlds/{w.id}/swimlane").json()
    names = [l["entity"]["name"] for l in data["lanes"]]
    # 地点不能出现
    assert "酒馆" not in names
    # 出现频次：爱丽丝 4 > 鲍勃 2
    assert names == ["爱丽丝", "鲍勃"]
    alice = data["lanes"][0]
    assert alice["event_count"] == 4
    assert [e["tick"] for e in alice["events"]] == [1, 2, 3, 4]


def test_swimlane_top_n_caps_lanes(client, db, world_factory):
    w, br = world_factory()
    # 5 个角色，每个一个事件
    for i in range(5):
        db.add(Entity(id=f"ent_{i}", branch_id=br.id, type="character",
                      name=f"角色{i}", summary="", attributes={}, state={},
                      created_at_tick=0, alive=1))
        db.add(Event(id=f"ev_{i}", branch_id=br.id, tick=i + 1, title="x",
                     description="", participants=[f"ent_{i}"], consequences=[],
                     metadata_={}, deleted=0))
    db.commit()
    data = client.get(f"/api/worlds/{w.id}/swimlane?top_n=3").json()
    assert len(data["lanes"]) == 3


def test_swimlane_global_markers(client, db, world_factory):
    w, _ = _setup_world(db, world_factory)
    data = client.get(f"/api/worlds/{w.id}/swimlane").json()

    chapters = data["global_chapters"]
    assert len(chapters) == 1 and chapters[0]["tick"] == 4 and chapters[0]["title"] == "第一章"

    issues = data["global_issues"]
    assert len(issues) == 1 and issues[0]["severity"] == "high"
    assert issues[0]["tick"] == 3
    assert "ent_alice" in issues[0]["entity_ids"]

    threads = data["global_threads"]
    assert len(threads) == 1 and threads[0]["status"] == "open"
    assert threads[0]["opened_tick"] == 2 and threads[0]["closed_tick"] is None


def test_swimlane_empty_world(client, world_factory):
    w, _ = world_factory()
    data = client.get(f"/api/worlds/{w.id}/swimlane").json()
    assert data["lanes"] == []
    assert data["global_chapters"] == []
    assert data["global_issues"] == []


def test_swimlane_404(client):
    assert client.get("/api/worlds/nope/swimlane").status_code == 404
