"""世界统计仪表盘 路由。

E1: 从 routes.py 中抽离的子路由模块。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..models import (
    get_db, World, Entity, Event, NarrativeLog, ChapterMarker,
    ConsistencyIssue, CausalLink,
)


router = APIRouter()


@router.get("/worlds/{world_id}/stats")
def world_stats(world_id: str, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    branch_id = world.active_branch_id

    entities = db.query(Entity).filter_by(branch_id=branch_id).all()
    events = db.query(Event).filter_by(branch_id=branch_id, deleted=0).all()
    narrations = db.query(NarrativeLog).filter_by(branch_id=branch_id).order_by(NarrativeLog.tick.asc()).all()
    chapters = db.query(ChapterMarker).filter_by(branch_id=branch_id).order_by(ChapterMarker.tick.asc()).all()
    issues = db.query(ConsistencyIssue).filter_by(world_id=world_id).all()
    links = db.query(CausalLink).filter_by(branch_id=branch_id).all()

    appearances: dict[str, int] = {}
    for ev in events:
        for pid in (ev.participants or []):
            appearances[pid] = appearances.get(pid, 0) + 1
    name_lookup = {e.id: e.name for e in entities}
    char_freq = sorted(
        [
            {"id": eid, "name": name_lookup.get(eid, eid[:8]), "count": cnt}
            for eid, cnt in appearances.items()
            if eid in name_lookup
        ],
        key=lambda x: -x["count"],
    )[:15]

    type_counts: dict[str, int] = {}
    for e in entities:
        type_counts[e.type] = type_counts.get(e.type, 0) + 1

    chapter_lens = []
    if chapters:
        boundaries = [c.tick for c in chapters] + [10**9]
        for i, c in enumerate(chapters):
            lo, hi = c.tick, boundaries[i + 1]
            seg = [n for n in narrations if lo <= n.tick < hi]
            chapter_lens.append({
                "title": c.title or f"第{i+1}章",
                "tick_start": lo,
                "narration_count": len(seg),
                "char_count": sum(len(n.text or "") for n in seg),
            })
    else:
        chapter_lens.append({
            "title": "全部",
            "tick_start": 0,
            "narration_count": len(narrations),
            "char_count": sum(len(n.text or "") for n in narrations),
        })

    tick_event_counts: dict[int, int] = {}
    for ev in events:
        tick_event_counts[ev.tick] = tick_event_counts.get(ev.tick, 0) + 1
    pace = sorted(
        [{"tick": t, "events": n} for t, n in tick_event_counts.items()],
        key=lambda x: x["tick"],
    )

    issue_by_cat: dict[str, int] = {}
    issue_by_sev: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    for i in issues:
        issue_by_cat[i.category] = issue_by_cat.get(i.category, 0) + 1
        if i.severity in issue_by_sev:
            issue_by_sev[i.severity] += 1
    issue_open = sum(1 for i in issues if i.status == "open")

    total_chars = sum(len(n.text or "") for n in narrations)

    return {
        "summary": {
            "current_tick": world.current_tick or 0,
            "max_tick": world.max_tick or 0,
            "entity_count": len(entities),
            "alive_count": sum(1 for e in entities if e.alive == 1),
            "event_count": len(events),
            "narration_count": len(narrations),
            "chapter_count": len(chapters),
            "causal_link_count": len(links),
            "issue_count": len(issues),
            "issue_open": issue_open,
            "total_chars": total_chars,
        },
        "character_frequency": char_freq,
        "entity_types": [{"type": k, "count": v} for k, v in sorted(type_counts.items(), key=lambda x: -x[1])],
        "chapter_lengths": chapter_lens,
        "pace": pace,
        "issue_by_category": [{"category": k, "count": v} for k, v in issue_by_cat.items()],
        "issue_by_severity": issue_by_sev,
    }
