"""B2 角色 arc 聚合测试：open issues / 因果链 / stats。

只覆盖 B2 这一刀新加的字段，arc 已有部分（events/relations/narration）已被
其它测试间接覆盖；此处主要保护新加的 issue 聚合 + 因果链不混入它人。
"""
from __future__ import annotations
import uuid

from app.models import Entity, Event, CausalLink, ConsistencyIssue


def _add_entity(db, branch_id, name, type_="character", **kw):
    ent = Entity(
        id=f"ent_{uuid.uuid4().hex[:8]}",
        branch_id=branch_id, type=type_, name=name,
        attributes={}, state={}, persona={}, memories=[], **kw,
    )
    db.add(ent); db.flush()
    return ent


def _add_event(db, branch_id, tick, title, participants, **kw):
    ev = Event(
        id=f"ev_{uuid.uuid4().hex[:8]}",
        branch_id=branch_id, tick=tick, title=title,
        participants=participants, **kw,
    )
    db.add(ev); db.flush()
    return ev


def _add_link(db, branch_id, cause_id, effect_id, weight=1.0):
    lk = CausalLink(
        id=f"cl_{uuid.uuid4().hex[:8]}",
        branch_id=branch_id, cause_event_id=cause_id, effect_event_id=effect_id,
        weight=weight,
    )
    db.add(lk); db.flush()
    return lk


def _add_issue(db, world_id, branch_id, entity_ids, status="open", severity="medium", **kw):
    iss = ConsistencyIssue(
        id=f"is_{uuid.uuid4().hex[:8]}",
        world_id=world_id, branch_id=branch_id,
        entity_ids=entity_ids, status=status, severity=severity,
        category=kw.pop("category", "personality"),
        title=kw.pop("title", "issue"),
        description=kw.pop("description", "desc"),
        suggestion=kw.pop("suggestion", ""),
        tick_start=kw.pop("tick_start", 0),
        tick_end=kw.pop("tick_end", 0),
    )
    db.add(iss); db.flush()
    return iss


def test_arc_includes_open_issues_for_this_entity(client, db, world_factory):
    w, br = world_factory()
    a = _add_entity(db, br.id, "阿离")
    b = _add_entity(db, br.id, "老掌柜")
    _add_issue(db, w.id, br.id, entity_ids=[a.id], severity="high",
               title="性格漂移", description="忽然变得多话")
    _add_issue(db, w.id, br.id, entity_ids=[b.id], title="只跟 B 有关")
    db.commit()

    r = client.get(f"/api/entities/{a.id}/arc")
    assert r.status_code == 200
    data = r.json()
    issues = data["open_issues"]
    assert len(issues) == 1
    assert issues[0]["title"] == "性格漂移"
    assert issues[0]["severity"] == "high"
    assert data["stats"]["open_issue_count"] == 1


def test_arc_skips_resolved_and_dismissed_issues(client, db, world_factory):
    w, br = world_factory()
    a = _add_entity(db, br.id, "阿离")
    _add_issue(db, w.id, br.id, entity_ids=[a.id], status="resolved", title="已修")
    _add_issue(db, w.id, br.id, entity_ids=[a.id], status="dismissed", title="忽略")
    _add_issue(db, w.id, br.id, entity_ids=[a.id], status="open", title="开口")
    db.commit()

    data = client.get(f"/api/entities/{a.id}/arc").json()
    titles = [i["title"] for i in data["open_issues"]]
    assert titles == ["开口"]


def test_arc_issues_sorted_by_recency(client, db, world_factory):
    w, br = world_factory()
    a = _add_entity(db, br.id, "阿离")
    _add_issue(db, w.id, br.id, entity_ids=[a.id], title="早", tick_end=2)
    _add_issue(db, w.id, br.id, entity_ids=[a.id], title="晚", tick_end=10)
    _add_issue(db, w.id, br.id, entity_ids=[a.id], title="中", tick_end=5)
    db.commit()

    titles = [i["title"] for i in client.get(f"/api/entities/{a.id}/arc").json()["open_issues"]]
    assert titles == ["晚", "中", "早"]


def test_arc_includes_causal_links_within_relevant_events(client, db, world_factory):
    w, br = world_factory()
    a = _add_entity(db, br.id, "阿离")
    b = _add_entity(db, br.id, "路人")
    e1 = _add_event(db, br.id, 1, "阿离发怒", participants=[a.id])
    e2 = _add_event(db, br.id, 2, "阿离离开", participants=[a.id])
    e_other = _add_event(db, br.id, 3, "路人吃饭", participants=[b.id])
    _add_link(db, br.id, e1.id, e2.id)        # 本角色内：cause/effect 都属于 a
    _add_link(db, br.id, e2.id, e_other.id)   # 跨角色：a 是 cause，b 是 effect
    _add_link(db, br.id, e_other.id, e_other.id)  # 跟 a 无关
    db.commit()

    data = client.get(f"/api/entities/{a.id}/arc").json()
    by_id = {b["event_id"]: b for b in data["arc"]}
    assert e1.id in by_id and e2.id in by_id
    # e1 -> e2 出现在 e1.outgoing 和 e2.incoming
    assert any(x["event_id"] == e2.id for x in by_id[e1.id]["outgoing_links"])
    assert any(x["event_id"] == e1.id for x in by_id[e2.id]["incoming_links"])
    # e2 -> e_other：a 是 cause，所以记 outgoing
    assert any(x["event_id"] == e_other.id for x in by_id[e2.id]["outgoing_links"])
    # 不该泄露 e_other → e_other 这条
    assert e_other.id not in by_id


def test_arc_stats_shape(client, db, world_factory):
    w, br = world_factory()
    a = _add_entity(db, br.id, "阿离")
    _add_event(db, br.id, 3, "登场", participants=[a.id])
    _add_event(db, br.id, 7, "高潮", participants=[a.id])
    db.commit()

    stats = client.get(f"/api/entities/{a.id}/arc").json()["stats"]
    assert stats["first_tick"] == 3
    assert stats["last_tick"] == 7
    assert stats["event_count"] == 2
    assert stats["open_issue_count"] == 0


def test_arc_stats_when_no_events(client, db, world_factory):
    w, br = world_factory()
    a = _add_entity(db, br.id, "阿离")
    db.commit()

    data = client.get(f"/api/entities/{a.id}/arc").json()
    assert data["arc"] == []
    assert data["stats"]["first_tick"] is None
    assert data["stats"]["event_count"] == 0
    assert data["open_issues"] == []
