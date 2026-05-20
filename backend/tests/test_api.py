"""API 集成冒烟 —— 走 FastAPI TestClient + 内存 DB，全程不打 LLM。"""
from __future__ import annotations


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_create_world_then_list(client):
    r = client.post("/api/worlds", json={"name": "测试世界", "description": "desc"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "id" in body and "active_branch_id" in body
    wid = body["id"]

    r2 = client.get("/api/worlds")
    assert r2.status_code == 200
    worlds = r2.json()
    assert any(w["id"] == wid and w["name"] == "测试世界" for w in worlds)


def test_get_world_returns_snapshot(client):
    wid = client.post("/api/worlds", json={"name": "S"}).json()["id"]
    r = client.get(f"/api/worlds/{wid}")
    assert r.status_code == 200
    snap = r.json()
    assert snap["world"]["id"] == wid
    assert snap["entities"] == []
    assert snap["recent_events"] == []


def test_get_world_404(client):
    r = client.get("/api/worlds/w_nonexistent")
    assert r.status_code == 404


def test_create_world_with_rules(client):
    r = client.post("/api/worlds", json={
        "name": "有规则", "rules": {"genre": "武侠", "tone": "悲壮"}
    })
    assert r.status_code == 200
    wid = r.json()["id"]
    snap = client.get(f"/api/worlds/{wid}").json()
    assert snap["world"]["rules"] == {"genre": "武侠", "tone": "悲壮"}


def test_list_branches_has_main(client):
    wid = client.post("/api/worlds", json={"name": "B"}).json()["id"]
    r = client.get(f"/api/worlds/{wid}/branches")
    assert r.status_code == 200
    branches = r.json()
    assert len(branches) == 1
    assert branches[0]["name"] == "main"
    assert branches[0]["is_active"] is True
    assert branches[0]["is_main"] is True
    assert branches[0]["event_count"] == 0


def test_add_entity(client):
    wid = client.post("/api/worlds", json={"name": "E"}).json()["id"]
    r = client.post(f"/api/worlds/{wid}/entities", json={
        "type": "character", "name": "李逵", "summary": "黑旋风"
    })
    assert r.status_code == 200, r.text
    eid = r.json()["id"]

    snap = client.get(f"/api/worlds/{wid}").json()
    names = [e["name"] for e in snap["entities"]]
    assert "李逵" in names


def test_patch_entity(client):
    wid = client.post("/api/worlds", json={"name": "E"}).json()["id"]
    eid = client.post(f"/api/worlds/{wid}/entities",
                      json={"type": "character", "name": "原名"}).json()["id"]

    r = client.patch(f"/api/entities/{eid}",
                     json={"name": "新名", "summary": "改了"})
    assert r.status_code == 200

    snap = client.get(f"/api/worlds/{wid}").json()
    e = next(x for x in snap["entities"] if x["id"] == eid)
    assert e["name"] == "新名"
    assert e["summary"] == "改了"


def test_add_event(client):
    wid = client.post("/api/worlds", json={"name": "EV"}).json()["id"]
    r = client.post(f"/api/worlds/{wid}/events",
                    json={"title": "首战", "description": "打起来了"})
    assert r.status_code == 200
    snap = client.get(f"/api/worlds/{wid}").json()
    titles = [ev["title"] for ev in snap["recent_events"]]
    assert "首战" in titles


def test_delete_event_soft(client):
    wid = client.post("/api/worlds", json={"name": "D"}).json()["id"]
    eid = client.post(f"/api/worlds/{wid}/events",
                      json={"title": "可删", "description": ""}).json()["id"]
    r = client.delete(f"/api/events/{eid}")
    assert r.status_code == 200
    snap = client.get(f"/api/worlds/{wid}").json()
    titles = [ev["title"] for ev in snap["recent_events"]]
    assert "可删" not in titles


def test_delete_world(client):
    wid = client.post("/api/worlds", json={"name": "del"}).json()["id"]
    client.post(f"/api/worlds/{wid}/entities",
                json={"type": "character", "name": "x"})
    r = client.delete(f"/api/worlds/{wid}")
    assert r.status_code == 200
    r2 = client.get(f"/api/worlds/{wid}")
    assert r2.status_code == 404


def test_timeline_endpoint_empty(client):
    wid = client.post("/api/worlds", json={"name": "T"}).json()["id"]
    r = client.get(f"/api/worlds/{wid}/timeline")
    assert r.status_code == 200


def test_world_patch_updates_outline(client):
    wid = client.post("/api/worlds", json={"name": "P"}).json()["id"]
    r = client.patch(f"/api/worlds/{wid}", json={"outline": "全新大纲"})
    assert r.status_code == 200
    snap = client.get(f"/api/worlds/{wid}").json()
    assert snap["world"]["outline"] == "全新大纲"
