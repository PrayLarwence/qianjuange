"""Manuscript / POV / swimlane / storyboard 渲染 API。

4 端点：
- POST /worlds/{id}/manuscript
- POST /worlds/{id}/pov
- GET  /worlds/{id}/swimlane
- GET  /worlds/{id}/storyboard
"""
from __future__ import annotations
import json
import logging
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..models import (
    get_db, World, Entity, Event, ChapterMarker, ConsistencyIssue, PlotThread, WorldLore,
)
from ..engine.manuscript import build_manuscript

log = logging.getLogger(__name__)
router = APIRouter()


# ===================== 导出成稿 =====================
from ..engine.manuscript import build_manuscript


class ManuscriptRequest(BaseModel):
    format: str = "markdown"
    polish: str = "raw"
    style_hint: str = ""
    chapter_from: Optional[int] = None
    chapter_to: Optional[int] = None
    provider: Optional[str] = None


@router.post("/worlds/{world_id}/manuscript")
def generate_manuscript(world_id: str, payload: ManuscriptRequest, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    fmt = payload.format if payload.format in ("markdown", "text", "json") else "markdown"
    polish = payload.polish if payload.polish in ("raw", "light", "unified") else "raw"
    chap_range = None
    if payload.chapter_from is not None and payload.chapter_to is not None:
        chap_range = (int(payload.chapter_from), int(payload.chapter_to))
    return build_manuscript(
        db, world,
        fmt=fmt, polish=polish,
        style_hint=payload.style_hint or "",
        chapter_range=chap_range,
        provider_key=payload.provider,
    )


# ===================== 角色 POV =====================
from ..engine.pov import build_pov_manuscript


class PovRequest(BaseModel):
    entity_id: str
    format: str = "markdown"
    style_hint: str = ""
    chapter_from: Optional[int] = None
    chapter_to: Optional[int] = None
    provider: Optional[str] = None


@router.post("/worlds/{world_id}/pov")
def generate_pov(world_id: str, payload: PovRequest, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    fmt = payload.format if payload.format in ("markdown", "text", "json") else "markdown"
    chap_range = None
    if payload.chapter_from is not None and payload.chapter_to is not None:
        chap_range = (int(payload.chapter_from), int(payload.chapter_to))
    try:
        return build_pov_manuscript(
            db, world,
            entity_id=payload.entity_id,
            fmt=fmt,
            style_hint=payload.style_hint or "",
            chapter_range=chap_range,
            provider_key=payload.provider,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


# ===================== 统计仪表盘 =====================
# 注：已抽至 app/api/stats_routes.py


# ============================================================
# B3: WorldLore CRUD (世界设定库)
# 注：已抽至 app/api/lore_routes.py
# ============================================================



# ============================================================
# C1: Timeline swimlane (角色横道 + 全局标记聚合)
# ============================================================

@router.get("/worlds/{world_id}/swimlane")
def get_swimlane(world_id: str, branch_id: str | None = None, top_n: int = 8, db: Session = Depends(get_db)):
    """聚合 events / chapters / issues / threads 成 swimlane 视图。

    - 每个角色一条 lane，按"事件出现频次"取 top_n
    - 全局标记：章节边界、issue（按 tick_start 落点）、伏笔 thread 的 open/close
    """
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    bid = branch_id or world.active_branch_id
    if not bid:
        return {"max_tick": 0, "lanes": [], "global_chapters": [], "global_issues": [], "global_threads": []}

    events = db.query(Event).filter_by(branch_id=bid, deleted=0).order_by(Event.tick).all()
    entities = db.query(Entity).filter_by(branch_id=bid).all()
    ent_by_id = {e.id: e for e in entities}

    # 统计每个角色出现次数
    freq: dict[str, int] = {}
    for ev in events:
        for pid in (ev.participants or []):
            ent = ent_by_id.get(pid)
            if ent and ent.type == "character":
                freq[pid] = freq.get(pid, 0) + 1
    top_ids = sorted(freq.keys(), key=lambda i: -freq[i])[: max(1, min(top_n, 20))]

    lanes = []
    for eid in top_ids:
        ent = ent_by_id[eid]
        lane_events = []
        for ev in events:
            if eid in (ev.participants or []):
                lane_events.append({
                    "id": ev.id, "tick": ev.tick,
                    "title": ev.title or "", "description": (ev.description or "")[:200],
                })
        lanes.append({
            "entity": {"id": ent.id, "name": ent.name, "type": ent.type, "alive": bool(ent.alive)},
            "event_count": len(lane_events),
            "events": lane_events,
        })

    chapters = (db.query(ChapterMarker).filter_by(branch_id=bid)
                .order_by(ChapterMarker.tick).all())
    issues = (db.query(ConsistencyIssue)
              .filter_by(world_id=world_id, branch_id=bid, status="open")
              .order_by(ConsistencyIssue.tick_start).all())
    threads = (db.query(PlotThread).filter_by(branch_id=bid)
               .order_by(PlotThread.opened_tick).all())

    max_tick = max([world.max_tick or 0, world.current_tick or 0]
                   + [e.tick for e in events] + [c.tick for c in chapters], default=0)

    return {
        "max_tick": max_tick,
        "lanes": lanes,
        "global_chapters": [
            {"id": c.id, "tick": c.tick, "title": c.title or "", "summary": c.summary or ""}
            for c in chapters
        ],
        "global_issues": [
            {"id": i.id, "tick": i.tick_start or 0, "tick_end": i.tick_end or 0,
             "severity": i.severity, "category": i.category,
             "title": i.title, "entity_ids": i.entity_ids or []}
            for i in issues
        ],
        "global_threads": [
            {"id": t.id, "title": t.title, "status": t.status,
             "opened_tick": t.opened_tick, "closed_tick": t.closed_tick}
            for t in threads
        ],
    }


# ============================================================
# C2: 章节故事板（按 ChapterMarker 聚合）
# ============================================================

@router.get("/worlds/{world_id}/storyboard")
def get_storyboard(
    world_id: str,
    branch_id: str | None = None,
    top_events: int = 8,
    top_characters: int = 6,
    db: Session = Depends(get_db),
):
    """聚合 ChapterMarker 区间内的关键事件 / 出场角色 / 推进 thread / open issue。

    每章范围：[markers[i].tick, markers[i+1].tick - 1]；末章到 max_tick。
    没有 markers 时返回单章覆盖整个时间线。
    """
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    bid = branch_id or world.active_branch_id
    if not bid:
        return {"max_tick": 0, "chapters": []}

    markers = (db.query(ChapterMarker).filter_by(branch_id=bid)
               .order_by(ChapterMarker.tick).all())
    events = db.query(Event).filter_by(branch_id=bid, deleted=0).order_by(Event.tick).all()
    entities = db.query(Entity).filter_by(branch_id=bid).all()
    ent_by_id = {e.id: e for e in entities}
    issues = (db.query(ConsistencyIssue)
              .filter_by(world_id=world_id, branch_id=bid, status="open").all())
    threads = db.query(PlotThread).filter_by(branch_id=bid).all()

    max_tick = max(
        [world.max_tick or 0, world.current_tick or 0]
        + [e.tick for e in events] + [m.tick for m in markers],
        default=0,
    )

    # 构建章节区间
    intervals: list[dict] = []
    if not markers:
        intervals.append({
            "id": "_unmarked",
            "title": "（未分章）",
            "summary": "",
            "tick_start": 0,
            "tick_end": max_tick,
            "is_synthetic": True,
        })
    else:
        if markers[0].tick > 0:
            prologue_events = [e for e in events if e.tick < markers[0].tick]
            if prologue_events:
                intervals.append({
                    "id": "_prologue",
                    "title": "（序章）",
                    "summary": "",
                    "tick_start": 0,
                    "tick_end": markers[0].tick - 1,
                    "is_synthetic": True,
                })
        for i, m in enumerate(markers):
            tick_start = m.tick
            if i + 1 < len(markers):
                tick_end = markers[i + 1].tick - 1
            else:
                tick_end = max(max_tick, m.tick)
            intervals.append({
                "id": m.id,
                "title": m.title or f"第{i+1}章",
                "summary": m.summary or m.note or "",
                "tick_start": tick_start,
                "tick_end": tick_end,
                "is_synthetic": False,
            })

    top_e_cap = max(1, min(int(top_events or 8), 50))
    top_c_cap = max(1, min(int(top_characters or 6), 20))

    out = []
    for idx, ch in enumerate(intervals):
        ts, te = ch["tick_start"], ch["tick_end"]
        chap_events = [e for e in events if ts <= e.tick <= te]

        # 出场角色按章内频次
        freq: dict[str, int] = {}
        for ev in chap_events:
            for pid in (ev.participants or []):
                ent = ent_by_id.get(pid)
                if ent and ent.type == "character":
                    freq[pid] = freq.get(pid, 0) + 1
        char_ids = sorted(freq.keys(), key=lambda i: -freq[i])[:top_c_cap]
        characters = [
            {"id": ent_by_id[cid].id, "name": ent_by_id[cid].name,
             "appearances": freq[cid], "alive": bool(ent_by_id[cid].alive)}
            for cid in char_ids
        ]

        # 关键事件（按 tick 升序，截前 N）
        events_out = [
            {"id": ev.id, "tick": ev.tick,
             "title": ev.title or "", "description": (ev.description or "")[:200],
             "participants": [
                 {"id": p, "name": ent_by_id[p].name if p in ent_by_id else p}
                 for p in (ev.participants or [])
             ]}
            for ev in chap_events[:top_e_cap]
        ]

        # 章内 issue
        chap_issues = [
            {"id": i.id, "title": i.title, "severity": i.severity, "category": i.category,
             "tick": i.tick_start or 0}
            for i in issues
            if (i.tick_start or 0) >= ts and (i.tick_start or 0) <= te
        ]

        # thread 状态
        thread_summary = []
        for t in threads:
            opened_in = ts <= (t.opened_tick or 0) <= te
            closed_in = t.closed_tick is not None and ts <= t.closed_tick <= te
            ongoing = (
                (t.opened_tick or 0) <= te
                and (t.closed_tick is None or t.closed_tick > te)
                and not opened_in
            )
            if opened_in or closed_in or ongoing:
                thread_summary.append({
                    "id": t.id, "title": t.title, "status": t.status,
                    "phase": "opened" if opened_in else ("closed" if closed_in else "ongoing"),
                })

        out.append({
            "id": ch["id"],
            "index": idx,
            "title": ch["title"],
            "summary": ch["summary"],
            "tick_start": ts,
            "tick_end": te,
            "is_synthetic": ch["is_synthetic"],
            "event_count": len(chap_events),
            "events": events_out,
            "characters": characters,
            "issues": chap_issues,
            "threads": thread_summary,
        })

    return {
        "world_id": world_id,
        "branch_id": bid,
        "max_tick": max_tick,
        "chapters": out,
    }


# 注：transitions/evaluate 与 threads/aging 已抽至 app/api/storyboard_aux_routes.py

