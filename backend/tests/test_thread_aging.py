"""C4: 伏笔超期检测端到端。"""
from __future__ import annotations

from app.models import PlotThread


def _setup(db, world_factory, current_tick=20):
    w, br = world_factory()
    w.current_tick = current_tick
    w.max_tick = current_tick
    db.add_all([
        PlotThread(id="t_fresh", branch_id=br.id, title="新钩子",
                   opened_tick=current_tick - 1, status="open"),
        PlotThread(id="t_warn", branch_id=br.id, title="中年钩子",
                   opened_tick=current_tick - 6, status="open"),
        PlotThread(id="t_stale", branch_id=br.id, title="老钩子",
                   opened_tick=current_tick - 15, status="open"),
        PlotThread(id="t_closed", branch_id=br.id, title="已收回",
                   opened_tick=current_tick - 20, closed_tick=current_tick - 5, status="closed"),
    ])
    db.commit()
    return w, br


def test_aging_levels_default_thresholds(client, db, world_factory):
    w, _ = _setup(db, world_factory)
    body = client.get(f"/api/worlds/{w.id}/threads/aging").json()
    assert body["current_tick"] == 20
    assert body["stale_after"] == 10
    assert body["warn_after"] == 5
    levels = {t["id"]: t["level"] for t in body["threads"]}
    assert levels["t_fresh"] == "fresh"
    assert levels["t_warn"] == "warn"
    assert levels["t_stale"] == "stale"
    assert "t_closed" not in levels  # closed 不返回
    assert body["counts"] == {"fresh": 1, "warn": 1, "stale": 1}


def test_aging_sorted_by_age_desc(client, db, world_factory):
    w, _ = _setup(db, world_factory)
    body = client.get(f"/api/worlds/{w.id}/threads/aging").json()
    ages = [t["age"] for t in body["threads"]]
    assert ages == sorted(ages, reverse=True)
    assert body["threads"][0]["id"] == "t_stale"


def test_aging_custom_thresholds(client, db, world_factory):
    w, _ = _setup(db, world_factory)
    body = client.get(f"/api/worlds/{w.id}/threads/aging?stale_after=3&warn_after=2").json()
    levels = {t["id"]: t["level"] for t in body["threads"]}
    # current=20, fresh opened=19 → age=1 → fresh
    # warn opened=14 → age=6 → stale (>=3)
    # stale opened=5 → age=15 → stale
    assert levels["t_fresh"] == "fresh"
    assert levels["t_warn"] == "stale"
    assert levels["t_stale"] == "stale"


def test_aging_empty_when_no_branch(client, db, world_factory):
    w, br = world_factory()
    w.active_branch_id = None
    db.commit()
    body = client.get(f"/api/worlds/{w.id}/threads/aging").json()
    assert body["threads"] == []
    assert body["counts"] == {"fresh": 0, "warn": 0, "stale": 0}


def test_aging_no_open_threads(client, db, world_factory):
    w, br = world_factory()
    w.current_tick = 5
    db.add(PlotThread(id="t_only_closed", branch_id=br.id, title="x",
                      opened_tick=1, closed_tick=4, status="closed"))
    db.commit()
    body = client.get(f"/api/worlds/{w.id}/threads/aging").json()
    assert body["threads"] == []


def test_aging_uses_max_tick_when_higher(client, db, world_factory):
    """current_tick 落后时按 max_tick 算。"""
    w, br = world_factory()
    w.current_tick = 5
    w.max_tick = 30
    db.add(PlotThread(id="t1", branch_id=br.id, title="x",
                      opened_tick=10, status="open"))
    db.commit()
    body = client.get(f"/api/worlds/{w.id}/threads/aging").json()
    assert body["current_tick"] == 30
    assert body["threads"][0]["age"] == 20
    assert body["threads"][0]["level"] == "stale"


def test_aging_world_404(client):
    r = client.get("/api/worlds/nope/threads/aging")
    assert r.status_code == 404


def test_aging_warn_capped_to_stale(client, db, world_factory):
    """warn_after > stale_after 时被夹紧。"""
    w, _ = _setup(db, world_factory)
    body = client.get(f"/api/worlds/{w.id}/threads/aging?stale_after=3&warn_after=99").json()
    # warn 被夹到 stale_after=3 → 实际只有 fresh/stale 两档
    assert body["warn_after"] == 3
