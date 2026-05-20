from __future__ import annotations
import uuid
import json
import threading
import logging
from datetime import datetime
from typing import Any, Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from ..engine import run_step, run_auto, run_reconcile, build_state_snapshot, CancelledError, create_job, get_job, cancel_job, capture_branch_snapshot, restore_branch_snapshot
from ..engine.tools import render_world_rules
from ..engine.state import state_as_prompt
from ..models import get_db, SessionLocal, World, Branch, Entity, Event, CausalLink, NarrativeLog, Snapshot, ChapterMarker, WorldTemplate, ConsistencyIssue, ScanRun, PlotThread
from ..providers import (
    get_provider, load_config, save_config, mask, PROVIDER_CLASSES,
    Message,
)

log = logging.getLogger(__name__)
router = APIRouter()


class WorldCreate(BaseModel):
    name: str
    description: str = ""
    outline: str = ""
    rules: dict[str, Any] = Field(default_factory=dict)


class StepRequest(BaseModel):
    directive: str | None = None
    provider: str | None = None
    steps: int = 1


def _new_id(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:10]}"


def _id_prefix_for(old_id: str) -> str:
    if not old_id or "_" not in old_id:
        return "id"
    return old_id.split("_", 1)[0]


@router.post("/worlds")
def create_world(payload: WorldCreate, db: Session = Depends(get_db)):
    world = World(
        id=_new_id("w"), name=payload.name,
        description=payload.description, outline=payload.outline,
        rules=payload.rules, current_tick=0,
    )
    db.add(world)
    db.flush()
    main = Branch(id=_new_id("br"), world_id=world.id, name="main", description="主世界线", parent_branch_id=None, diverged_at_tick=0)
    db.add(main)
    db.flush()
    world.active_branch_id = main.id
    db.commit()
    return {"id": world.id, "active_branch_id": main.id}


@router.get("/worlds")
def list_worlds(db: Session = Depends(get_db)):
    worlds = db.query(World).order_by(World.created_at.desc()).all()
    return [{"id": w.id, "name": w.name, "description": w.description, "current_tick": w.current_tick, "active_branch_id": w.active_branch_id} for w in worlds]


@router.get("/worlds/{world_id}")
def get_world(world_id: str, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    return build_state_snapshot(db, world)


@router.delete("/worlds/{world_id}")
def delete_world(world_id: str, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    branches = db.query(Branch).filter_by(world_id=world_id).all()
    bids = [b.id for b in branches]
    if bids:
        db.query(NarrativeLog).filter(NarrativeLog.branch_id.in_(bids)).delete(synchronize_session=False)
        db.query(CausalLink).filter(CausalLink.branch_id.in_(bids)).delete(synchronize_session=False)
        db.query(Event).filter(Event.branch_id.in_(bids)).delete(synchronize_session=False)
        db.query(Entity).filter(Entity.branch_id.in_(bids)).delete(synchronize_session=False)
    world.active_branch_id = None
    db.flush()
    db.query(Branch).filter_by(world_id=world_id).delete(synchronize_session=False)
    db.delete(world)
    db.commit()
    try:
        from ..engine import worldgen
        worldgen.delete(world_id)
    except Exception as e:
        log.warning("failed to delete map for %s: %s", world_id, e)
    return {"ok": True}


@router.get("/worlds/{world_id}/branches")
def list_branches(world_id: str, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    branches = db.query(Branch).filter_by(world_id=world_id).order_by(Branch.created_at).all()
    out = []
    for b in branches:
        event_count = db.query(Event).filter_by(branch_id=b.id, deleted=0).count()
        deleted_count = db.query(Event).filter_by(branch_id=b.id, deleted=1).count()
        max_tick = db.query(Event.tick).filter_by(branch_id=b.id, deleted=0).order_by(Event.tick.desc()).first()
        entity_count = db.query(Entity).filter_by(branch_id=b.id).count()
        out.append({
            "id": b.id,
            "name": b.name,
            "description": b.description,
            "parent_branch_id": b.parent_branch_id,
            "diverged_at_tick": b.diverged_at_tick,
            "is_active": b.id == world.active_branch_id,
            "is_main": b.parent_branch_id is None,
            "event_count": event_count,
            "deleted_event_count": deleted_count,
            "entity_count": entity_count,
            "max_tick": (max_tick[0] if max_tick else 0),
            "created_at": b.created_at.isoformat() if b.created_at else None,
        })
    return out


@router.get("/worlds/{world_id}/gantt")
def world_gantt(
    world_id: str,
    branch_ids: str | None = None,  # comma-separated; default = all
    db: Session = Depends(get_db),
):
    """Compact snapshot for the multi-branch timeline view.

    Returns events, causal links and chapter markers across the requested
    branches in a flat structure. Designed to be cheap (no entity/state) so
    we can re-poll on every step without redrawing the whole world.
    """
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    all_branches = db.query(Branch).filter_by(world_id=world_id).order_by(Branch.created_at).all()
    if branch_ids:
        wanted = {b.strip() for b in branch_ids.split(",") if b.strip()}
        branches = [b for b in all_branches if b.id in wanted]
    else:
        branches = all_branches
    bids = [b.id for b in branches]
    if not bids:
        return {"branches": [], "events": [], "causal_links": [], "chapters": []}

    events = db.query(Event).filter(Event.branch_id.in_(bids), Event.deleted == 0).all()
    links = db.query(CausalLink).filter(CausalLink.branch_id.in_(bids)).all()
    chapters = db.query(ChapterMarker).filter(ChapterMarker.branch_id.in_(bids)).all()
    return {
        "branches": [{
            "id": b.id, "name": b.name,
            "parent_branch_id": b.parent_branch_id,
            "diverged_at_tick": b.diverged_at_tick,
            "is_active": b.id == world.active_branch_id,
        } for b in branches],
        "events": [{
            "id": e.id, "branch_id": e.branch_id, "tick": e.tick,
            "title": e.title, "description": e.description or "",
            "participants": e.participants or [],
            "consequences": e.consequences or [],
        } for e in events],
        "causal_links": [{
            "id": l.id, "branch_id": l.branch_id,
            "cause_event_id": l.cause_event_id, "effect_event_id": l.effect_event_id,
            "weight": l.weight,
        } for l in links],
        "chapters": [{
            "id": cm.id, "branch_id": cm.branch_id,
            "tick": cm.tick, "title": cm.title or "",
        } for cm in chapters],
        "current_tick": world.current_tick,
        "active_branch_id": world.active_branch_id,
    }


class BranchPatch(BaseModel):
    name: str | None = None
    description: str | None = None


@router.patch("/branches/{branch_id}")
def patch_branch(branch_id: str, payload: BranchPatch, db: Session = Depends(get_db)):
    b = db.query(Branch).filter_by(id=branch_id).first()
    if not b:
        raise HTTPException(404, "branch not found")
    if payload.name is not None and payload.name.strip():
        b.name = payload.name.strip()
    if payload.description is not None:
        b.description = payload.description
    db.commit()
    return {"ok": True}


@router.delete("/branches/{branch_id}")
def delete_branch(branch_id: str, db: Session = Depends(get_db)):
    b = db.query(Branch).filter_by(id=branch_id).first()
    if not b:
        raise HTTPException(404, "branch not found")
    if b.parent_branch_id is None:
        raise HTTPException(400, "cannot delete main branch")
    children = db.query(Branch).filter_by(parent_branch_id=branch_id).count()
    if children > 0:
        raise HTTPException(400, f"branch has {children} child branches; delete them first")
    world = db.query(World).filter_by(id=b.world_id).first()
    if world and world.active_branch_id == branch_id:
        main = db.query(Branch).filter_by(world_id=b.world_id, parent_branch_id=None).first()
        if main:
            world.active_branch_id = main.id
    db.query(NarrativeLog).filter_by(branch_id=branch_id).delete(synchronize_session=False)
    db.query(CausalLink).filter_by(branch_id=branch_id).delete(synchronize_session=False)
    db.query(Event).filter_by(branch_id=branch_id).delete(synchronize_session=False)
    db.query(Entity).filter_by(branch_id=branch_id).delete(synchronize_session=False)
    db.delete(b)
    db.commit()
    return {"ok": True}


@router.post("/worlds/{world_id}/switch_branch/{branch_id}")
def switch_branch(world_id: str, branch_id: str, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    branch = db.query(Branch).filter_by(id=branch_id, world_id=world_id).first()
    if not branch:
        raise HTTPException(404, "branch not found")
    world.active_branch_id = branch_id
    db.commit()
    return {"ok": True, "active_branch_id": branch_id}


@router.get("/worlds/{world_id}/timeline")
def get_timeline(world_id: str, branch_id: str | None = None, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    bid = branch_id or world.active_branch_id
    events = db.query(Event).filter_by(branch_id=bid, deleted=0).order_by(Event.tick).all()
    event_ids = {e.id for e in events}
    links = db.query(CausalLink).filter_by(branch_id=bid).all()
    visible_links = [l for l in links if l.cause_event_id in event_ids and l.effect_event_id in event_ids]
    narration = db.query(NarrativeLog).filter_by(branch_id=bid).order_by(NarrativeLog.tick).all()
    threads = (db.query(PlotThread)
                 .filter_by(branch_id=bid)
                 .order_by(PlotThread.opened_tick)
                 .all())
    return {
        "events": [{
            "id": e.id, "tick": e.tick, "title": e.title, "description": e.description,
            "participants": e.participants, "location_id": e.location_id, "consequences": e.consequences,
        } for e in events],
        "links": [{"cause": l.cause_event_id, "effect": l.effect_event_id, "description": l.description, "weight": l.weight} for l in visible_links],
        "narration": [{"tick": n.tick, "text": n.text, "role": n.role or "narrator"} for n in narration],
        "plot_threads": [{
            "id": t.id, "title": t.title, "summary": t.summary, "status": t.status,
            "opened_tick": t.opened_tick, "closed_tick": t.closed_tick,
            "resolution": t.resolution or "",
            "related_entity_ids": t.related_entity_ids or [],
        } for t in threads],
    }


@router.post("/worlds/{world_id}/step")
def step_world(world_id: str, payload: StepRequest, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    if world.max_tick and world.current_tick >= world.max_tick:
        raise HTTPException(400, f"已达推演上限 tick={world.max_tick}（请在右侧调整目标或解锁）")
    provider = get_provider(payload.provider) if payload.provider else None
    try:
        if payload.steps and payload.steps > 1:
            steps = payload.steps
            if world.max_tick:
                steps = min(steps, max(0, world.max_tick - world.current_tick))
                if steps <= 0:
                    raise HTTPException(400, f"已达推演上限 tick={world.max_tick}")
            results = run_auto(db, world, steps=steps, user_directive=payload.directive, provider=provider)
            return {"ok": True, "results": results, "tick": world.current_tick, "max_tick": world.max_tick}
        result = run_step(db, world, user_directive=payload.directive, provider=provider)
        result["max_tick"] = world.max_tick
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"simulation failed: {e}")


class MultiAgentStepRequest(BaseModel):
    character_ids: list[str] | None = None  # None = auto-pick
    directive: str | None = None
    provider: str | None = None


@router.post("/worlds/{world_id}/step_multi_agent")
def step_world_multi_agent(world_id: str, payload: MultiAgentStepRequest, db: Session = Depends(get_db)):
    """Sub-agent driven step: each focal character produces intents from
    their own POV, then a director pass resolves them into world events."""
    from ..engine.multi_agent import run_multi_agent_step
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    if world.max_tick and world.current_tick >= world.max_tick:
        raise HTTPException(400, f"已达推演上限 tick={world.max_tick}")
    provider = get_provider(payload.provider) if payload.provider else None
    try:
        result = run_multi_agent_step(
            db, world,
            character_ids=payload.character_ids,
            user_directive=payload.directive,
            provider=provider,
        )
        result["max_tick"] = world.max_tick
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"multi-agent step failed: {e}")


@router.post("/worlds/{world_id}/step_async")
def step_async(world_id: str, payload: StepRequest, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    job = create_job(world_id, "step")
    job.status = "running"
    provider_key = payload.provider
    directive = payload.directive
    steps = max(1, payload.steps or 1)

    def runner():
        local_db = SessionLocal()
        try:
            local_world = local_db.query(World).filter_by(id=world_id).first()
            if not local_world:
                job.error = "world not found"
                job.status = "error"
                return
            try:
                pre_label = (directive[:40] + ("…" if directive and len(directive) > 40 else "")) if directive else "auto"
                snap = capture_branch_snapshot(local_db, local_world, label=f"步骤前 · {pre_label}")
                local_db.commit()
                job.progress_message = f"已建快照 {snap.id[:12]}"
            except Exception:
                log.exception("pre-step snapshot failed")
                local_db.rollback()
            provider = get_provider(provider_key) if provider_key else None

            def progress(info):
                if "tool_calls" in info:
                    job.tool_calls = list(info["tool_calls"])
                if "narration" in info:
                    job.narration = info["narration"]
                phase = info.get("phase", "")
                if phase == "step_start":
                    job.progress_message = f"第 {info['step']}/{info['total']} 步开始"
                elif phase == "thinking":
                    job.progress_message = f"AI 思考中（hop {info.get('hop', 0)+1}）"
                elif phase == "executing":
                    job.progress_message = f"已执行 {len(job.tool_calls)} 个工具"

            results = run_auto(
                local_db, local_world, steps=steps,
                user_directive=directive, provider=provider,
                cancel_check=job.is_cancelled, on_progress=progress,
            )
            job.result = {"results": results, "tick": local_world.current_tick}
            job.status = "cancelled" if job.is_cancelled() else "completed"
        except CancelledError:
            job.status = "cancelled"
        except Exception as e:
            log.exception("async step failed")
            job.error = f"{type(e).__name__}: {e}"
            job.status = "error"
        finally:
            import time as _t
            job.finished_at = _t.time()
            local_db.close()

    threading.Thread(target=runner, daemon=True).start()
    return {"job_id": job.id}


@router.get("/jobs/{job_id}")
def get_job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job.to_dict()


@router.post("/jobs/{job_id}/cancel")
def cancel_job_route(job_id: str):
    ok = cancel_job(job_id)
    if not ok:
        raise HTTPException(404, "job not found")
    return {"ok": True}


EXPORT_VERSION = 1


@router.get("/worlds/{world_id}/export")
def export_world(world_id: str, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    branches = db.query(Branch).filter_by(world_id=world_id).all()
    branch_ids = [b.id for b in branches]
    entities = db.query(Entity).filter(Entity.branch_id.in_(branch_ids)).all() if branch_ids else []
    events = db.query(Event).filter(Event.branch_id.in_(branch_ids)).all() if branch_ids else []
    links = db.query(CausalLink).filter(CausalLink.branch_id.in_(branch_ids)).all() if branch_ids else []
    narration = db.query(NarrativeLog).filter(NarrativeLog.branch_id.in_(branch_ids)).all() if branch_ids else []
    return {
        "schema_version": EXPORT_VERSION,
        "exported_at": __import__("time").time(),
        "world": {
            "id": world.id,
            "name": world.name,
            "description": world.description,
            "current_tick": world.current_tick,
            "active_branch_id": world.active_branch_id,
            "rules": world.rules or {},
        },
        "branches": [{
            "id": b.id, "name": b.name, "description": b.description,
            "parent_branch_id": b.parent_branch_id, "diverged_at_tick": b.diverged_at_tick,
        } for b in branches],
        "entities": [{
            "id": e.id, "branch_id": e.branch_id, "type": e.type, "name": e.name,
            "summary": e.summary, "attributes": e.attributes or {}, "state": e.state or {},
            "location_id": e.location_id, "created_at_tick": e.created_at_tick, "alive": e.alive,
            "map_x": e.map_x, "map_y": e.map_y,
            "target_x": e.target_x, "target_y": e.target_y,
            "move_speed": e.move_speed, "sim_state": e.sim_state or {},
        } for e in entities],
        "events": [{
            "id": e.id, "branch_id": e.branch_id, "tick": e.tick, "title": e.title,
            "description": e.description, "location_id": e.location_id,
            "participants": e.participants or [], "consequences": e.consequences or [],
            "metadata": e.metadata_ or {}, "deleted": e.deleted,
        } for e in events],
        "causal_links": [{
            "id": l.id, "branch_id": l.branch_id,
            "cause_event_id": l.cause_event_id, "effect_event_id": l.effect_event_id,
            "description": l.description, "weight": l.weight,
        } for l in links],
        "narration": [{
            "id": n.id, "branch_id": n.branch_id, "tick": n.tick,
            "role": n.role, "text": n.text,
        } for n in narration],
    }


# -------- novelize / export-novel --------

class NovelizeRequest(BaseModel):
    branch_id: str | None = None  # default: world.active_branch_id
    strategy: str = "by_count"     # manual | by_tick | by_count | single
    chapter_size: int = 6
    tick_lo: int | None = None
    tick_hi: int | None = None
    provider: str | None = None


@router.get("/worlds/{world_id}/novelize/chapters")
def novelize_list_chapters(
    world_id: str,
    branch_id: str | None = None,
    strategy: str = "by_count",
    chapter_size: int = 6,
    tick_lo: int | None = None,
    tick_hi: int | None = None,
    db: Session = Depends(get_db),
):
    """Preview chapter slices without invoking the LLM."""
    from ..engine.novelize import list_chapters
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    bid = branch_id or world.active_branch_id
    try:
        slices = list_chapters(db, world, bid,
                               strategy=strategy, chapter_size=chapter_size,
                               tick_lo=tick_lo, tick_hi=tick_hi)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "branch_id": bid,
        "strategy": strategy,
        "chapters": [
            {"index": s.index, "title": s.title,
             "tick_lo": s.tick_lo, "tick_hi": s.tick_hi,
             "event_count": len(s.event_ids)}
            for s in slices
        ],
    }


@router.post("/worlds/{world_id}/novelize")
def novelize_sync(world_id: str, payload: NovelizeRequest, db: Session = Depends(get_db)):
    """Render novel-style markdown synchronously. Suitable for short branches.
    For long branches use /novelize_async + job polling."""
    from ..engine.novelize import novelize_branch
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    bid = payload.branch_id or world.active_branch_id
    provider = get_provider(payload.provider) if payload.provider else None
    try:
        return novelize_branch(
            db, world, bid,
            strategy=payload.strategy,
            chapter_size=payload.chapter_size,
            tick_lo=payload.tick_lo,
            tick_hi=payload.tick_hi,
            provider=provider,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"novelize failed: {e}")


@router.post("/worlds/{world_id}/novelize_async")
def novelize_async(world_id: str, payload: NovelizeRequest, db: Session = Depends(get_db)):
    """Background novelize: returns job_id, poll /jobs/{id} for progress and result."""
    from ..engine.novelize import novelize_branch
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    bid = payload.branch_id or world.active_branch_id

    job = create_job(world_id, "novelize")
    job.status = "running"
    job.progress_message = "准备中…"
    p_strategy = payload.strategy
    p_size = payload.chapter_size
    p_lo, p_hi = payload.tick_lo, payload.tick_hi
    provider_key = payload.provider

    def runner():
        local_db = SessionLocal()
        try:
            local_world = local_db.query(World).filter_by(id=world_id).first()
            if not local_world:
                job.error = "world not found"; job.status = "error"; return
            provider = get_provider(provider_key) if provider_key else None

            def progress(info):
                phase = info.get("phase", "")
                if phase == "start":
                    job.progress_message = f"共 {info.get('chapter_total', '?')} 章，开始润色"
                elif phase == "chapter_start":
                    job.progress_message = f"写第 {info['index']}/{info['chapter_total']} 章：{info.get('title','')}"
                elif phase == "chapter_done":
                    job.progress_message = f"第 {info['index']}/{info['chapter_total']} 章完成（{info.get('chars',0)} 字）"
                elif phase == "done":
                    job.progress_message = f"全部完成，共 {info.get('chars',0)} 字"

            res = novelize_branch(
                local_db, local_world, bid,
                strategy=p_strategy, chapter_size=p_size,
                tick_lo=p_lo, tick_hi=p_hi,
                provider=provider,
                on_progress=progress,
            )
            job.result = res
            job.status = "completed"
        except Exception as e:
            log.exception("async novelize failed")
            job.error = f"{type(e).__name__}: {e}"
            job.status = "error"
        finally:
            import time as _t
            job.finished_at = _t.time()
            local_db.close()

    threading.Thread(target=runner, daemon=True).start()
    return {"job_id": job.id}


class WorldImport(BaseModel):
    payload: dict[str, Any]
    new_name: str | None = None


@router.post("/worlds/import")
def import_world(payload: WorldImport, db: Session = Depends(get_db)):
    p = payload.payload or {}
    if p.get("schema_version") != EXPORT_VERSION:
        raise HTTPException(400, f"unsupported schema_version: {p.get('schema_version')}")
    if "world" not in p or "branches" not in p:
        raise HTTPException(400, "invalid export payload")

    id_map: dict[str, str] = {}

    def remap(old_id: str | None) -> str | None:
        if not old_id:
            return None
        if old_id not in id_map:
            id_map[old_id] = _new_id(_id_prefix_for(old_id))
        return id_map[old_id]

    new_world_id = _new_id("world")
    id_map[p["world"]["id"]] = new_world_id

    new_world = World(
        id=new_world_id,
        name=payload.new_name or (p["world"]["name"] + " (导入)"),
        description=p["world"].get("description", ""),
        current_tick=p["world"].get("current_tick", 0),
        rules=p["world"].get("rules") or {},
    )
    db.add(new_world)
    db.flush()

    main_branch_id = None
    for b in p["branches"]:
        new_bid = remap(b["id"])
        parent_bid = remap(b.get("parent_branch_id")) if b.get("parent_branch_id") else None
        nb = Branch(
            id=new_bid, world_id=new_world_id, name=b["name"],
            description=b.get("description", ""),
            parent_branch_id=parent_bid, diverged_at_tick=b.get("diverged_at_tick", 0),
        )
        db.add(nb)
        if parent_bid is None and main_branch_id is None:
            main_branch_id = new_bid
    db.flush()

    new_world.active_branch_id = remap(p["world"].get("active_branch_id")) or main_branch_id
    db.flush()

    for e in p.get("entities", []):
        db.add(Entity(
            id=remap(e["id"]), branch_id=remap(e["branch_id"]),
            type=e["type"], name=e["name"], summary=e.get("summary", ""),
            attributes=e.get("attributes") or {}, state=e.get("state") or {},
            location_id=remap(e.get("location_id")) if e.get("location_id") else None,
            created_at_tick=e.get("created_at_tick", 0), alive=e.get("alive", 1),
        ))
    for ev in p.get("events", []):
        db.add(Event(
            id=remap(ev["id"]), branch_id=remap(ev["branch_id"]),
            tick=ev["tick"], title=ev["title"], description=ev.get("description", ""),
            location_id=remap(ev.get("location_id")) if ev.get("location_id") else None,
            participants=[remap(pid) for pid in (ev.get("participants") or [])],
            consequences=ev.get("consequences") or [],
            metadata_=ev.get("metadata") or {}, deleted=ev.get("deleted", 0),
        ))
    for l in p.get("causal_links", []):
        db.add(CausalLink(
            id=remap(l["id"]), branch_id=remap(l["branch_id"]),
            cause_event_id=remap(l["cause_event_id"]),
            effect_event_id=remap(l["effect_event_id"]),
            description=l.get("description", ""), weight=l.get("weight", 1.0),
        ))
    for n in p.get("narration", []):
        db.add(NarrativeLog(
            id=remap(n["id"]), branch_id=remap(n["branch_id"]),
            tick=n["tick"], role=n.get("role", "narrator"), text=n.get("text", ""),
        ))
    db.commit()
    return {"ok": True, "world_id": new_world_id}


class ChatTurn(BaseModel):
    role: str
    content: str


class CharacterChatRequest(BaseModel):
    message: str
    history: list[ChatTurn] = Field(default_factory=list)
    view_tick: int | None = None
    provider: str | None = None


@router.post("/entities/{entity_id}/chat")
def character_chat(entity_id: str, payload: CharacterChatRequest, db: Session = Depends(get_db)):
    entity = db.query(Entity).filter_by(id=entity_id).first()
    if not entity:
        raise HTTPException(404, "entity not found")
    if entity.type != "character":
        raise HTTPException(400, "only characters can be chatted with")

    branch = db.query(Branch).filter_by(id=entity.branch_id).first()
    world = db.query(World).filter_by(id=branch.world_id).first() if branch else None
    if not world:
        raise HTTPException(404, "world not found")

    view_tick = payload.view_tick if payload.view_tick is not None else world.current_tick

    all_events = db.query(Event).filter_by(branch_id=entity.branch_id).filter(Event.deleted == 0).all()
    visible_events = sorted(
        [e for e in all_events if e.tick <= view_tick and entity.id in (e.participants or [])],
        key=lambda e: e.tick,
    )
    recent = visible_events[-8:]

    co_ids: set[str] = set()
    for ev in visible_events:
        for pid in (ev.participants or []):
            if pid != entity.id:
                co_ids.add(pid)
    co_entities = db.query(Entity).filter(Entity.id.in_(list(co_ids))).all() if co_ids else []

    location = None
    loc_id = (entity.state or {}).get("location_id") or entity.location_id
    if loc_id:
        location = db.query(Entity).filter_by(id=loc_id).first()

    attrs = entity.attributes or {}
    state = entity.state or {}
    public_state = {k: v for k, v in state.items() if k != "location_id"}

    def fmt_kv(d: dict) -> str:
        if not d:
            return "（无）"
        return "\n".join(f"  - {k}: {v}" for k, v in d.items())

    events_text = "\n".join(
        f"  - 第 {ev.tick} 时刻 · 《{ev.title}》：{ev.description}"
        for ev in recent
    ) or "  （这个时点之前你还没有可叙述的经历）"

    coactors_text = "\n".join(
        f"  - {ce.name}（{ce.type}）：{ce.summary or '无简介'}"
        for ce in co_entities
    ) or "  （还未与他人有交集）"

    sys_prompt = f"""你正在扮演一个虚构世界中的角色。你必须始终以这个角色的第一人称、口吻、知识范围回答用户。

# 你的身份
- 名字：{entity.name}
- 简介：{entity.summary or '（未设定）'}
- 你所在的世界：{world.name} — {world.description or ''}

# 你的属性（这些塑造了你）
{fmt_kv(attrs)}

# 你当前的状态
{fmt_kv(public_state) if public_state else '  （平稳）'}
- 你目前在：{location.name if location else '未知'}{('（' + (location.summary or '') + '）') if location and location.summary else ''}
- 当前时刻：第 {view_tick} 时
- 世界主时钟：第 {world.current_tick} 时{('（你正在以更早视角回忆，回答时只能基于第 ' + str(view_tick) + ' 时之前的认知）') if view_tick < world.current_tick else ''}

# 你经历过的事（按时间顺序，最近 {len(recent)} 件）
{events_text}

# 你认识/同台过的人
{coactors_text}

# 行为准则（极其重要）
1. 必须始终用第一人称（"我"）说话，从不跳出角色
2. 你只知道第 {view_tick} 时之前的事；如果用户问之后的事，回答"我不知道"或合理推测
3. 你的语气、用词、关注点必须符合上面的属性设定
4. 不要编造与已知事件矛盾的经历
5. 用户可能问你过去/动机/感受/对他人看法/对未来打算 — 都基于你的属性和经历回答
6. 不要解释你是 AI、不要谈论"叙事系统"或"沙盒"等元概念
7. 回答控制在 80-200 字，自然口语化，避免书面化的"首先、其次、综上"
8. 用与世界设定匹配的语言风格回答
"""

    rules_block = render_world_rules(world.rules)
    if rules_block:
        sys_prompt += "\n\n# 这个世界的规则（你必须遵守）\n" + rules_block

    history_msgs: list[Message] = []
    for turn in payload.history[-20:]:
        role = "user" if turn.role == "user" else "assistant"
        history_msgs.append(Message(role=role, content=turn.content))
    history_msgs.append(Message(role="user", content=payload.message))

    provider = get_provider(payload.provider) if payload.provider else get_provider()
    try:
        resp = provider.chat(
            system=sys_prompt,
            messages=history_msgs,
            tools=[],
            max_tokens=600,
            temperature=0.85,
        )
    except Exception as e:
        log.exception("character chat failed")
        raise HTTPException(500, f"chat failed: {e}")

    return {
        "reply": resp.text or "（沉默）",
        "view_tick": view_tick,
        "world_tick": world.current_tick,
        "context": {
            "events_visible": len(visible_events),
            "events_used": len(recent),
            "coactors": len(co_entities),
        },
    }


@router.get("/worlds/{world_id}/history")
def world_history(world_id: str, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    branch_id = world.active_branch_id
    snaps = db.query(Snapshot).filter_by(branch_id=branch_id).order_by(Snapshot.created_at.desc()).limit(80).all()
    return {
        "branch_id": branch_id,
        "current_tick": world.current_tick,
        "snapshots": [{
            "id": s.id,
            "tick": s.tick,
            "label": s.label or "",
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "counts": (s.payload or {}).get("counts", {}),
            "is_current": s.tick == world.current_tick,
        } for s in snaps],
    }


@router.post("/worlds/{world_id}/restore/{snapshot_id}")
def restore_snapshot(world_id: str, snapshot_id: str, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    snap = db.query(Snapshot).filter_by(id=snapshot_id).first()
    if not snap:
        raise HTTPException(404, "snapshot not found")
    if snap.branch_id != world.active_branch_id:
        raise HTTPException(400, "snapshot belongs to a different branch — switch branch first")
    try:
        capture_branch_snapshot(db, world, label=f"回滚前 · t{world.current_tick}")
        counts = restore_branch_snapshot(db, world, snap)
        db.commit()
        return {"ok": True, "restored_tick": world.current_tick, "counts": counts}
    except Exception as e:
        db.rollback()
        log.exception("restore failed")
        raise HTTPException(500, f"restore failed: {e}")


@router.delete("/snapshots/{snapshot_id}")
def delete_snapshot(snapshot_id: str, db: Session = Depends(get_db)):
    snap = db.query(Snapshot).filter_by(id=snapshot_id).first()
    if not snap:
        raise HTTPException(404, "snapshot not found")
    db.delete(snap)
    db.commit()
    return {"ok": True}


class WorldUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    outline: str | None = None
    rules: dict[str, Any] | None = None


@router.patch("/worlds/{world_id}")
def update_world(world_id: str, payload: WorldUpdate, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    if payload.name is not None:
        world.name = payload.name.strip() or world.name
    if payload.description is not None:
        world.description = payload.description
    if payload.outline is not None:
        world.outline = payload.outline
    if payload.rules is not None:
        world.rules = payload.rules
    db.commit()
    return {
        "ok": True,
        "id": world.id, "name": world.name,
        "description": world.description, "outline": world.outline or "",
        "rules": world.rules or {},
    }


def _fork_branch(db: Session, world: World, parent_branch_id: str, name: str, description: str = "") -> Branch:
    new_branch = Branch(
        id=_new_id("br"), world_id=world.id, name=name,
        description=description, parent_branch_id=parent_branch_id,
        diverged_at_tick=world.current_tick,
    )
    db.add(new_branch)
    db.flush()
    old_to_new: dict[str, str] = {}
    for entity in db.query(Entity).filter_by(branch_id=parent_branch_id).all():
        new_id = _new_id("ent")
        old_to_new[entity.id] = new_id
        db.add(Entity(
            id=new_id, branch_id=new_branch.id, type=entity.type, name=entity.name,
            summary=entity.summary, attributes=dict(entity.attributes or {}),
            state=dict(entity.state or {}), location_id=None,
            created_at_tick=entity.created_at_tick, alive=entity.alive,
        ))
    db.flush()
    for entity in db.query(Entity).filter_by(branch_id=parent_branch_id).all():
        if entity.location_id:
            new_id = old_to_new.get(entity.id)
            new_loc = old_to_new.get(entity.location_id, entity.location_id)
            db.query(Entity).filter_by(id=new_id).update({"location_id": new_loc})
    ev_old_to_new: dict[str, str] = {}
    for ev in db.query(Event).filter_by(branch_id=parent_branch_id).all():
        new_id = _new_id("evt")
        ev_old_to_new[ev.id] = new_id
        db.add(Event(
            id=new_id, branch_id=new_branch.id, tick=ev.tick, title=ev.title,
            description=ev.description,
            location_id=old_to_new.get(ev.location_id) if ev.location_id else None,
            participants=[old_to_new.get(p, p) for p in (ev.participants or [])],
            consequences=list(ev.consequences or []),
            metadata_=dict(ev.metadata_ or {}), deleted=ev.deleted,
        ))
    for l in db.query(CausalLink).filter_by(branch_id=parent_branch_id).all():
        db.add(CausalLink(
            id=_new_id("cau"), branch_id=new_branch.id,
            cause_event_id=ev_old_to_new.get(l.cause_event_id, l.cause_event_id),
            effect_event_id=ev_old_to_new.get(l.effect_event_id, l.effect_event_id),
            description=l.description, weight=l.weight,
        ))
    for n in db.query(NarrativeLog).filter_by(branch_id=parent_branch_id).all():
        db.add(NarrativeLog(
            id=_new_id("nar"), branch_id=new_branch.id,
            tick=n.tick, role=n.role, text=n.text,
        ))
    db.flush()
    return new_branch


class ExploreVariant(BaseModel):
    label: str
    directive: str


class ExploreRequest(BaseModel):
    variants: list[ExploreVariant]
    steps: int = 1
    provider: str | None = None


@router.post("/worlds/{world_id}/explore")
def parallel_explore(world_id: str, payload: ExploreRequest, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    if not payload.variants or len(payload.variants) < 2:
        raise HTTPException(400, "need at least 2 variants")
    if len(payload.variants) > 5:
        raise HTTPException(400, "max 5 variants per explore run")

    parent_branch_id = world.active_branch_id
    parent_branch = db.query(Branch).filter_by(id=parent_branch_id).first()
    parent_name = parent_branch.name if parent_branch else "main"

    forked = []
    for v in payload.variants:
        label = (v.label or "").strip() or "what-if"
        new_branch = _fork_branch(
            db, world, parent_branch_id,
            name=f"{parent_name}/{label}",
            description=f"并发探索：{v.directive[:80]}",
        )
        forked.append((new_branch.id, new_branch.name, v.directive))
    db.commit()

    out = []
    steps = max(1, min(payload.steps, 5))
    for branch_id, branch_name, directive in forked:
        job = create_job(world_id, "explore")
        job.status = "running"
        job.progress_message = f"分支 {branch_name} 准备中"

        def runner(bid=branch_id, bname=branch_name, drct=directive, j=job):
            local_db = SessionLocal()
            try:
                local_world = local_db.query(World).filter_by(id=world_id).first()
                if not local_world:
                    j.error = "world not found"; j.status = "error"; return
                local_world._override_branch_id = bid
                try:
                    capture_branch_snapshot(local_db, local_world, label=f"探索前 · {drct[:30]}")
                    local_db.commit()
                except Exception:
                    log.exception("explore pre-snapshot failed")
                    local_db.rollback()

                provider = get_provider(payload.provider) if payload.provider else None

                def progress(info):
                    if "tool_calls" in info:
                        j.tool_calls = list(info["tool_calls"])
                    if "narration" in info:
                        j.narration = info["narration"]
                    phase = info.get("phase", "")
                    if phase == "step_start":
                        j.progress_message = f"[{bname}] 第 {info['step']}/{info['total']} 步"
                    elif phase == "thinking":
                        j.progress_message = f"[{bname}] AI 思考中"
                    elif phase == "executing":
                        j.progress_message = f"[{bname}] 已执行 {len(j.tool_calls)} 个工具"

                results = run_auto(
                    local_db, local_world, steps=steps,
                    user_directive=drct, provider=provider,
                    cancel_check=j.is_cancelled, on_progress=progress,
                )
                j.result = {
                    "branch_id": bid, "branch_name": bname,
                    "directive": drct, "results": results,
                    "tick": local_world.current_tick,
                }
                j.status = "cancelled" if j.is_cancelled() else "completed"
            except CancelledError:
                j.status = "cancelled"
            except Exception as e:
                log.exception("explore job failed")
                j.error = f"{type(e).__name__}: {e}"
                j.status = "error"
            finally:
                import time as _t
                j.finished_at = _t.time()
                local_db.close()

        threading.Thread(target=runner, daemon=True).start()
        out.append({
            "job_id": job.id, "branch_id": branch_id,
            "branch_name": branch_name, "directive": directive,
        })

    return {"variants": out, "parent_branch_id": parent_branch_id}


class EvaluateVariantsRequest(BaseModel):
    variant_branch_ids: list[str]
    parent_branch_id: str
    parent_tick: int
    provider: str | None = None


@router.post("/worlds/{world_id}/evaluate_variants")
def evaluate_variants(world_id: str, payload: EvaluateVariantsRequest, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")

    parent_events = (
        db.query(Event)
        .filter_by(branch_id=payload.parent_branch_id, deleted=0)
        .filter(Event.tick <= payload.parent_tick)
        .order_by(Event.tick.desc())
        .limit(8).all()
    )
    parent_summary = "\n".join(f"- t{e.tick} {e.title}：{e.description[:100]}" for e in reversed(parent_events)) or "（无前情）"

    variants_text_parts = []
    variant_meta = []
    for bid in payload.variant_branch_ids:
        branch = db.query(Branch).filter_by(id=bid).first()
        if not branch:
            continue
        new_events = (
            db.query(Event)
            .filter_by(branch_id=bid, deleted=0)
            .filter(Event.tick > payload.parent_tick)
            .order_by(Event.tick).all()
        )
        new_narration = (
            db.query(NarrativeLog).filter_by(branch_id=bid)
            .filter(NarrativeLog.tick > payload.parent_tick)
            .order_by(NarrativeLog.tick).all()
        )
        ev_text = "\n".join(f"  - t{e.tick} {e.title}：{e.description[:140]}" for e in new_events) or "  （未产生事件）"
        nar_text = "\n".join(f"  > {n.text[:160]}" for n in new_narration[:4]) or ""
        variants_text_parts.append(
            f"### 变体 {branch.name.split('/')[-1]} (id={bid})\n指令：{branch.description or '无'}\n新增事件：\n{ev_text}" + (f"\n叙事片段：\n{nar_text}" if nar_text else "")
        )
        variant_meta.append({"branch_id": bid, "label": branch.name.split('/')[-1]})

    if not variants_text_parts:
        raise HTTPException(400, "no valid variants found")

    rules_block = render_world_rules(world.rules)

    sys_prompt = f"""你是一位资深叙事编辑，擅长在多个故事走向中评估优劣。

世界设定：{world.name} — {world.description or ''}
{rules_block}

# 评估前的局面（分叉点之前最近 8 件事）
{parent_summary}

# 候选变体（从同一节点分别推演而成）
{chr(10).join(variants_text_parts)}

# 你的任务
对每个变体打 4 项分（1-10 整数）：
- tension：戏剧张力（冲突/悬念/转折是否抓人）
- consistency：角色一致性（角色行为是否符合此前的属性与处境）
- rules：世界规则吻合度（是否违反硬规则或基调；无规则时按设定合理性打）
- originality：新意（是否陈词滥调）

并给出 verdict：一句话点评每个变体的核心亮点或硬伤（不超过 50 字）。
最后给 recommended：你最推荐采纳的 branch_id（只能选一个）。

严格输出 JSON，禁止任何额外说明：
{{
  "evaluations": [
    {{"branch_id": "br_xxx", "scores": {{"tension": 8, "consistency": 7, "rules": 9, "originality": 6}}, "verdict": "..."}},
    ...
  ],
  "recommended": "br_xxx",
  "reasoning": "为什么推荐这个（不超过 80 字）"
}}
"""

    provider = get_provider(payload.provider) if payload.provider else get_provider()
    try:
        resp = provider.chat(
            system=sys_prompt,
            messages=[Message(role="user", content="请评估上述变体并按规定 JSON 输出。")],
            tools=[],
            max_tokens=1200,
            temperature=0.3,
        )
    except Exception as e:
        log.exception("evaluate failed")
        raise HTTPException(500, f"evaluate failed: {e}")

    raw = resp.text or ""
    parsed: dict[str, Any] = {}
    try:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            parsed = json.loads(raw[start:end+1])
    except Exception:
        log.warning("evaluate JSON parse failed: %s", raw[:200])
        parsed = {}

    evals = parsed.get("evaluations") or []
    recommended = parsed.get("recommended") or ""
    reasoning = parsed.get("reasoning") or ""
    by_id = {e.get("branch_id"): e for e in evals if isinstance(e, dict)}

    enriched = []
    for v in variant_meta:
        e = by_id.get(v["branch_id"]) or {}
        scores = e.get("scores") or {}
        total = sum(int(scores.get(k, 0) or 0) for k in ("tension", "consistency", "rules", "originality"))
        enriched.append({
            "branch_id": v["branch_id"],
            "label": v["label"],
            "scores": {
                "tension": int(scores.get("tension", 0) or 0),
                "consistency": int(scores.get("consistency", 0) or 0),
                "rules": int(scores.get("rules", 0) or 0),
                "originality": int(scores.get("originality", 0) or 0),
            },
            "total": total,
            "verdict": str(e.get("verdict") or ""),
        })

    return {
        "evaluations": enriched,
        "recommended": recommended,
        "reasoning": reasoning,
        "raw_ok": bool(parsed),
    }


@router.get("/worlds/{world_id}/relationships")
def world_relationships(world_id: str, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    branch_id = world.active_branch_id
    entities = db.query(Entity).filter_by(branch_id=branch_id).all()
    events = db.query(Event).filter_by(branch_id=branch_id, deleted=0).order_by(Event.tick).all()
    by_id = {e.id: e for e in entities}

    edges_map: dict[tuple[str, str], dict] = {}
    for ev in events:
        parts = [p for p in (ev.participants or []) if p in by_id]
        if len(parts) < 2:
            continue
        unique = sorted(set(parts))
        for i in range(len(unique)):
            for j in range(i + 1, len(unique)):
                key = (unique[i], unique[j])
                d = edges_map.setdefault(key, {"weight": 0, "events": []})
                d["weight"] += 1
                if len(d["events"]) < 6:
                    d["events"].append({"id": ev.id, "tick": ev.tick, "title": ev.title})

    cached = {}
    for e in entities:
        if e.type != "character":
            continue
        rels = (e.attributes or {}).get("_relations") or {}
        if isinstance(rels, dict):
            for other_id, label in rels.items():
                key = tuple(sorted([e.id, other_id]))
                cached[key] = label

    edges = []
    for (a, b), d in edges_map.items():
        label = cached.get((a, b)) or ""
        edges.append({
            "id": f"rel_{a}_{b}",
            "source": a, "target": b,
            "weight": d["weight"],
            "label": label,
            "events": d["events"],
        })

    nodes = [{
        "id": e.id, "name": e.name, "type": e.type,
        "alive": e.alive, "summary": e.summary or "",
        "location_id": e.location_id,
    } for e in entities]

    return {"nodes": nodes, "edges": edges}


class InferRelationshipsRequest(BaseModel):
    provider: str | None = None


@router.post("/worlds/{world_id}/relationships/infer")
def infer_relationships(world_id: str, payload: InferRelationshipsRequest, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    branch_id = world.active_branch_id
    entities = db.query(Entity).filter_by(branch_id=branch_id, type="character").all()
    if len(entities) < 2:
        return {"updated": 0, "pairs": []}

    by_id = {e.id: e for e in entities}
    events = db.query(Event).filter_by(branch_id=branch_id, deleted=0).order_by(Event.tick).all()

    pair_events: dict[tuple[str, str], list] = {}
    for ev in events:
        parts = [p for p in (ev.participants or []) if p in by_id]
        if len(parts) < 2:
            continue
        unique = sorted(set(parts))
        for i in range(len(unique)):
            for j in range(i + 1, len(unique)):
                pair_events.setdefault((unique[i], unique[j]), []).append(ev)

    if not pair_events:
        return {"updated": 0, "pairs": []}

    pair_lines = []
    for (a, b), evs in pair_events.items():
        a_name = by_id[a].name
        b_name = by_id[b].name
        snippet = "；".join(f"t{e.tick} {e.title}" for e in evs[-5:])
        pair_lines.append(f"- {a}|{b}|{a_name}↔{b_name}：{snippet}")

    sys_prompt = f"""你是叙事分析师。基于角色之间的共同事件，给出他们当前的关系标签。

世界：{world.name}
{render_world_rules(world.rules)}

角色清单：
{chr(10).join(f'- {e.id}: {e.name}（{(e.summary or "")[:50]}）' for e in entities)}

每对角色及他们共同参与的事件：
{chr(10).join(pair_lines)}

为每对给出简短关系标签（2-6 字，例：青梅竹马 / 死敌 / 上下级 / 暗恋 / 父女 / 战友→反目）。
若关系暧昧或多重，用斜杠：恋人/同事。

严格输出 JSON：
{{
  "relations": [
    {{"a": "ent_xxx", "b": "ent_yyy", "label": "..."}},
    ...
  ]
}}
"""
    provider = get_provider(payload.provider) if payload.provider else get_provider()
    try:
        resp = provider.chat(
            system=sys_prompt,
            messages=[Message(role="user", content="请给出 JSON 标签。")],
            tools=[],
            max_tokens=1500,
            temperature=0.4,
        )
    except Exception as e:
        log.exception("infer relationships failed")
        raise HTTPException(500, f"infer failed: {e}")

    raw = resp.text or ""
    parsed: dict[str, Any] = {}
    try:
        s = raw.find("{"); e = raw.rfind("}")
        if s >= 0 and e > s:
            parsed = json.loads(raw[s:e+1])
    except Exception:
        log.warning("infer JSON parse failed: %s", raw[:200])

    rels = parsed.get("relations") or []
    updated = 0
    for r in rels:
        if not isinstance(r, dict):
            continue
        a = r.get("a"); b = r.get("b"); label = (r.get("label") or "").strip()
        if not (a in by_id and b in by_id and label):
            continue
        for ent_id, other in [(a, b), (b, a)]:
            ent = by_id[ent_id]
            attrs = dict(ent.attributes or {})
            relmap = dict(attrs.get("_relations") or {})
            relmap[other] = label
            attrs["_relations"] = relmap
            ent.attributes = attrs
        updated += 1
    db.commit()
    return {"updated": updated, "raw_ok": bool(parsed)}


class SetRelationRequest(BaseModel):
    a_id: str
    b_id: str
    label: str = ""


@router.post("/worlds/{world_id}/relationships/set")
def set_relationship(world_id: str, payload: SetRelationRequest, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    branch_id = world.active_branch_id
    a = db.query(Entity).filter_by(id=payload.a_id, branch_id=branch_id).first()
    b = db.query(Entity).filter_by(id=payload.b_id, branch_id=branch_id).first()
    if not (a and b):
        raise HTTPException(404, "entity not found")
    label = (payload.label or "").strip()
    for ent, other_id in [(a, b.id), (b, a.id)]:
        attrs = dict(ent.attributes or {})
        relmap = dict(attrs.get("_relations") or {})
        if label:
            relmap[other_id] = label
        else:
            relmap.pop(other_id, None)
        attrs["_relations"] = relmap
        ent.attributes = attrs
    db.commit()
    return {"ok": True, "a_id": a.id, "b_id": b.id, "label": label}


# ============== chapter markers ==============

@router.get("/worlds/{world_id}/chapters")
def list_chapters(world_id: str, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    rows = (
        db.query(ChapterMarker)
        .filter_by(branch_id=world.active_branch_id)
        .order_by(ChapterMarker.tick).all()
    )
    return {"chapters": [{
        "id": r.id, "tick": r.tick, "title": r.title or "", "note": r.note or ""
    } for r in rows]}


class ChapterCreateRequest(BaseModel):
    tick: int
    title: str = ""
    note: str = ""
    branch_id: str | None = None  # default: world.active_branch_id


@router.post("/worlds/{world_id}/chapters")
def create_chapter(world_id: str, payload: ChapterCreateRequest, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    bid = payload.branch_id or world.active_branch_id
    # ensure branch belongs to this world
    if not db.query(Branch).filter_by(id=bid, world_id=world_id).first():
        raise HTTPException(400, "branch not in this world")
    existing = db.query(ChapterMarker).filter_by(
        branch_id=bid, tick=payload.tick
    ).first()
    if existing:
        existing.title = payload.title or existing.title
        existing.note = payload.note or existing.note
        db.commit()
        return {"id": existing.id, "branch_id": existing.branch_id, "tick": existing.tick,
                "title": existing.title, "note": existing.note}
    cm = ChapterMarker(
        id=f"ch_{uuid.uuid4().hex[:10]}",
        branch_id=bid,
        tick=payload.tick,
        title=payload.title.strip(),
        note=payload.note.strip(),
    )
    db.add(cm); db.commit()
    return {"id": cm.id, "branch_id": cm.branch_id, "tick": cm.tick, "title": cm.title, "note": cm.note}


class ChapterPatchRequest(BaseModel):
    title: str | None = None
    note: str | None = None
    tick: int | None = None


@router.patch("/chapters/{chapter_id}")
def patch_chapter(chapter_id: str, payload: ChapterPatchRequest, db: Session = Depends(get_db)):
    cm = db.query(ChapterMarker).filter_by(id=chapter_id).first()
    if not cm:
        raise HTTPException(404, "chapter not found")
    if payload.title is not None: cm.title = payload.title.strip()
    if payload.note  is not None: cm.note  = payload.note.strip()
    if payload.tick  is not None: cm.tick  = payload.tick
    db.commit()
    return {"id": cm.id, "branch_id": cm.branch_id, "tick": cm.tick, "title": cm.title, "note": cm.note}


@router.delete("/chapters/{chapter_id}")
def delete_chapter_global(chapter_id: str, db: Session = Depends(get_db)):
    cm = db.query(ChapterMarker).filter_by(id=chapter_id).first()
    if not cm:
        raise HTTPException(404, "chapter not found")
    db.delete(cm); db.commit()
    return {"ok": True}



@router.delete("/worlds/{world_id}/chapters/{chapter_id}")
def delete_chapter(world_id: str, chapter_id: str, db: Session = Depends(get_db)):
    cm = db.query(ChapterMarker).filter_by(id=chapter_id).first()
    if not cm:
        raise HTTPException(404, "chapter not found")
    db.delete(cm); db.commit()
    return {"ok": True}


class AutoChapterRequest(BaseModel):
    target_count: int = 5
    provider: str | None = None


@router.post("/worlds/{world_id}/chapters/auto")
def auto_chapter(world_id: str, payload: AutoChapterRequest, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    branch_id = world.active_branch_id
    events = db.query(Event).filter_by(branch_id=branch_id, deleted=0).order_by(Event.tick).all()
    if len(events) < 2:
        return {"chapters": [], "reason": "事件太少，无需分章"}

    target = max(2, min(payload.target_count, 12))
    by_id = {e.id: e for e in db.query(Entity).filter_by(branch_id=branch_id).all()}
    ev_lines = []
    for ev in events:
        parts = "、".join(by_id[p].name for p in (ev.participants or []) if p in by_id) or "—"
        ev_lines.append(f"t{ev.tick}|《{ev.title}》|参与:{parts}|{ev.description[:80]}")

    sys_prompt = f"""你是一位资深小说编辑，要给以下故事划分**约 {target} 个**章节。

世界：{world.name}
{render_world_rules(world.rules)}

事件序列（按时间）：
{chr(10).join(ev_lines)}

# 你的任务
找出**自然的章节断点**——通常是：场景切换、时间跳跃、视角转换、剧情节奏转折。
每个断点选一个 tick 作为"章末"。
给每章起一个 4-12 字的题眼（不含"第X章"字样）。

严格输出 JSON：
{{
  "chapters": [
    {{"end_tick": 7, "title": "鲁山雪夜"}},
    {{"end_tick": 15, "title": "刀光初现"}},
    ...
  ]
}}
不要输出任何额外说明。
"""
    provider = get_provider(payload.provider) if payload.provider else get_provider()
    try:
        resp = provider.chat(
            system=sys_prompt,
            messages=[Message(role="user", content="开始分章。")],
            tools=[],
            max_tokens=1200,
            temperature=0.5,
        )
    except Exception as e:
        log.exception("auto chapter failed")
        raise HTTPException(500, f"auto chapter failed: {e}")

    raw = resp.text or ""
    parsed: dict[str, Any] = {}
    try:
        s = raw.find("{"); e = raw.rfind("}")
        if s >= 0 and e > s:
            parsed = json.loads(raw[s:e+1])
    except Exception:
        log.warning("auto chapter JSON parse failed")

    chs = parsed.get("chapters") or []
    db.query(ChapterMarker).filter_by(branch_id=branch_id).delete()
    out = []
    for ch in chs:
        if not isinstance(ch, dict):
            continue
        try:
            t = int(ch.get("end_tick", -1))
        except Exception:
            continue
        title = (ch.get("title") or "").strip()
        if t < 0 or not title:
            continue
        cm = ChapterMarker(
            id=f"ch_{uuid.uuid4().hex[:10]}",
            branch_id=branch_id, tick=t, title=title,
        )
        db.add(cm)
        out.append({"id": cm.id, "tick": t, "title": title})
    db.commit()
    return {"chapters": out, "raw_ok": bool(parsed)}


class SuggestDirectivesRequest(BaseModel):
    n: int = 4
    style: str = ""
    provider: str | None = None


@router.post("/worlds/{world_id}/suggest_directives")
def suggest_directives(world_id: str, payload: SuggestDirectivesRequest, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")

    snapshot = build_state_snapshot(db, world, max_events=20, max_entities=40)
    state_text = state_as_prompt(snapshot)
    rules_block = render_world_rules(world.rules)
    n = max(2, min(payload.n, 6))
    style_hint = (payload.style or "").strip()

    sys_prompt = f"""你是叙事教练，看到当前世界状态后，要给作者推荐 {n} 个**截然不同**的下一步推演方向。

世界：{world.name}
{rules_block}

# 当前状态
{state_text}

# 你的任务
基于现有人物、未解决的伏笔、关系张力，提出 {n} 条可执行的"下一步指令"。要求：
- 每条都是**具体动作**，不是抽象描述（错：让矛盾升级；对：让张三在酒馆撞见李四的妻子）
- 各条之间**走向迥异**（一条悲剧路线、一条温情路线、一条意外转折…）
- 充分利用当前已埋下的钩子和角色关系
- 每条带 kind 标签：'continue' 顺势 / 'twist' 反转 / 'tragic' 悲剧 / 'tender' 温情 / 'reveal' 揭秘 / 'conflict' 冲突
{f'- 风格倾向：{style_hint}' if style_hint else ''}

严格输出 JSON：
{{
  "suggestions": [
    {{"kind": "twist", "directive": "...", "rationale": "为什么这条有戏（不超过 40 字）"}},
    ...
  ]
}}
"""
    provider = get_provider(payload.provider) if payload.provider else get_provider()
    try:
        resp = provider.chat(
            system=sys_prompt,
            messages=[Message(role="user", content="请按 JSON 给出建议。")],
            tools=[],
            max_tokens=1200,
            temperature=0.85,
        )
    except Exception as e:
        log.exception("suggest failed")
        raise HTTPException(500, f"suggest failed: {e}")

    raw = resp.text or ""
    parsed: dict[str, Any] = {}
    try:
        s = raw.find("{"); e = raw.rfind("}")
        if s >= 0 and e > s:
            parsed = json.loads(raw[s:e+1])
    except Exception:
        log.warning("suggest JSON parse failed: %s", raw[:200])

    sugg = parsed.get("suggestions") or []
    out = []
    for x in sugg[:n]:
        if not isinstance(x, dict):
            continue
        d = (x.get("directive") or "").strip()
        if not d:
            continue
        out.append({
            "kind": (x.get("kind") or "continue").strip(),
            "directive": d,
            "rationale": (x.get("rationale") or "").strip(),
        })
    return {"suggestions": out, "raw_ok": bool(parsed)}


class ExportRequest(BaseModel):
    mode: str = "raw"
    tick_from: int | None = None
    tick_to: int | None = None
    chapter_size: int = 5
    use_chapter_markers: bool = True
    include_critique: bool = False
    include_events: bool = True
    include_narration: bool = True
    include_entities: bool = False
    provider: str | None = None


@router.post("/worlds/{world_id}/export")
def export_world(world_id: str, payload: ExportRequest, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    branch_id = world.active_branch_id
    branch = db.query(Branch).filter_by(id=branch_id).first()

    tick_lo = 0 if payload.tick_from is None else max(0, payload.tick_from)
    tick_hi = world.current_tick if payload.tick_to is None else payload.tick_to

    events = (
        db.query(Event).filter_by(branch_id=branch_id, deleted=0)
        .filter(Event.tick >= tick_lo, Event.tick <= tick_hi)
        .order_by(Event.tick).all()
    )
    narration = (
        db.query(NarrativeLog).filter_by(branch_id=branch_id)
        .filter(NarrativeLog.tick >= tick_lo, NarrativeLog.tick <= tick_hi)
        .order_by(NarrativeLog.tick).all()
    )
    entities = db.query(Entity).filter_by(branch_id=branch_id).all()
    by_id = {e.id: e for e in entities}

    if payload.mode == "json":
        return {
            "format": "json",
            "filename": f"{world.name}_{branch.name if branch else 'main'}_{tick_lo}-{tick_hi}.json",
            "content": json.dumps({
                "world": {"name": world.name, "description": world.description, "rules": world.rules or {}},
                "branch": branch.name if branch else "main",
                "tick_range": [tick_lo, tick_hi],
                "entities": [{"id": e.id, "type": e.type, "name": e.name, "summary": e.summary,
                              "attributes": e.attributes or {}, "state": e.state or {}, "alive": e.alive,
                              "location_id": e.location_id, "created_at_tick": e.created_at_tick} for e in entities],
                "events": [{"id": ev.id, "tick": ev.tick, "title": ev.title, "description": ev.description,
                            "participants": ev.participants or [], "consequences": ev.consequences or [],
                            "location_id": ev.location_id} for ev in events],
                "narration": [{"tick": n.tick, "role": n.role, "text": n.text} for n in narration],
            }, ensure_ascii=False, indent=2),
        }

    if payload.mode == "raw":
        lines = [f"# {world.name}", ""]
        if world.description:
            lines += [world.description, ""]
        lines += [f"*分支：{branch.name if branch else 'main'} · tick {tick_lo}–{tick_hi}*", ""]

        if payload.include_entities:
            chars = [e for e in entities if e.type == "character"]
            if chars:
                lines += ["## 主要人物", ""]
                for e in chars:
                    state = "" if e.alive else "（已逝）"
                    lines.append(f"- **{e.name}**{state} — {e.summary or ''}")
                lines.append("")

        ticks = sorted(set([ev.tick for ev in events] + [n.tick for n in narration]))
        if ticks:
            lines += ["## 故事正文", ""]
            ev_by_tick: dict[int, list[Event]] = {}
            for ev in events:
                ev_by_tick.setdefault(ev.tick, []).append(ev)
            nar_by_tick: dict[int, list[NarrativeLog]] = {}
            for n in narration:
                nar_by_tick.setdefault(n.tick, []).append(n)

            for t in ticks:
                lines.append(f"### t{t}")
                if payload.include_narration:
                    for n in nar_by_tick.get(t, []):
                        lines.append(n.text)
                        lines.append("")
                if payload.include_events:
                    for ev in ev_by_tick.get(t, []):
                        parts = "、".join(by_id[p].name for p in (ev.participants or []) if p in by_id)
                        loc = by_id.get(ev.location_id).name if ev.location_id and ev.location_id in by_id else ""
                        meta_bits = " ".join(f"[{x}]" for x in [parts, loc] if x)
                        lines.append(f"- **{ev.title}** {meta_bits}")
                        if ev.description:
                            lines.append(f"  > {ev.description}")
                lines.append("")

        return {
            "format": "markdown",
            "filename": f"{world.name}_{tick_lo}-{tick_hi}.md",
            "content": "\n".join(lines),
        }

    if payload.mode == "novelize":
        if not events and not narration:
            raise HTTPException(400, "no events or narration in range to novelize")

        markers = []
        if payload.use_chapter_markers:
            markers = (
                db.query(ChapterMarker).filter_by(branch_id=branch_id)
                .filter(ChapterMarker.tick >= tick_lo, ChapterMarker.tick <= tick_hi)
                .order_by(ChapterMarker.tick).all()
            )

        chunks: list[tuple[int, int, list[Event], list[NarrativeLog], str]] = []
        if markers:
            cursor = tick_lo
            for m in markers:
                cs, ce_t = cursor, m.tick
                ce_events = [ev for ev in events if cs <= ev.tick <= ce_t]
                ce_narr = [n for n in narration if cs <= n.tick <= ce_t]
                if ce_events or ce_narr:
                    chunks.append((cs, ce_t, ce_events, ce_narr, m.title or ""))
                cursor = m.tick + 1
            if cursor <= tick_hi:
                ce_events = [ev for ev in events if cursor <= ev.tick <= tick_hi]
                ce_narr = [n for n in narration if cursor <= n.tick <= tick_hi]
                if ce_events or ce_narr:
                    chunks.append((cursor, tick_hi, ce_events, ce_narr, ""))
        else:
            chunk_size = max(1, min(payload.chapter_size, 20))
            for chunk_start in range(tick_lo, tick_hi + 1, chunk_size):
                chunk_end = min(chunk_start + chunk_size - 1, tick_hi)
                chunk_events = [ev for ev in events if chunk_start <= ev.tick <= chunk_end]
                chunk_narr = [n for n in narration if chunk_start <= n.tick <= chunk_end]
                if chunk_events or chunk_narr:
                    chunks.append((chunk_start, chunk_end, chunk_events, chunk_narr, ""))

        rules_block = render_world_rules(world.rules)
        char_list = "\n".join(
            f"- {e.name}（{e.type}）: {e.summary or ''}" for e in entities if e.type == "character"
        ) or "（无角色）"
        provider = get_provider(payload.provider) if payload.provider else get_provider()

        chapters_md: list[str] = [f"# {world.name}"]
        if world.description:
            chapters_md += ["", world.description]
        chunk_source = "章节标记" if markers else f"每 {payload.chapter_size} ticks"
        chapters_md += [f"\n*分支 {branch.name if branch else 'main'} · 共 {len(chunks)} 章 · 切分方式：{chunk_source}*", ""]

        for idx, (cs, ce, ce_events, ce_narr, hint_title) in enumerate(chunks, start=1):
            ev_text = "\n".join(
                f"- t{ev.tick} 《{ev.title}》参与：{'、'.join(by_id[p].name for p in (ev.participants or []) if p in by_id) or '—'}\n  详情：{ev.description}"
                for ev in ce_events
            ) or "（无事件）"
            narr_text = "\n".join(f"- t{n.tick}: {n.text}" for n in ce_narr) or "（无既有叙事）"
            title_hint = f"\n章节标题已由编辑预设为：{hint_title}（请直接使用）" if hint_title else ""

            sys_prompt = f"""你是一位优秀的小说家，正在把一段世界推演的结构化日志改写成连贯的小说章节。

世界：{world.name} — {world.description or ''}
{rules_block}

主要人物：
{char_list}

# 第 {idx} 章原始材料（t{cs}–t{ce}）
## 事件
{ev_text}

## 已有叙事片段（可借鉴或忽略）
{narr_text}

# 你的任务
把以上事件改写成一段 600-1200 字的连贯小说章节散文。要求：
- 不要列举事件，要叙述
- 用对话和细节让人物活起来
- 保留事件的因果与时序
- 尊重世界规则与基调
- 章节开头给一个吸引人的标题（不带"第X章"字样，只一个 4-12 字的题眼）{title_hint}

输出格式：
## {{章节标题}}

{{正文段落，多段}}

不要输出额外说明、不要写元注释。
"""
            chap_text = ""
            try:
                resp = provider.chat(
                    system=sys_prompt,
                    messages=[Message(role="user", content="开始写作。")],
                    tools=[],
                    max_tokens=2400,
                    temperature=0.85,
                )
                chap_text = (resp.text or "").strip()
                if not chap_text.startswith("##"):
                    chap_text = f"## {hint_title or f'第 {idx} 章'}\n\n{chap_text}"
                chapters_md.append(chap_text)
            except Exception as e:
                log.exception("novelize chapter failed")
                chapters_md.append(f"## 第 {idx} 章\n\n*[小说化失败：{e}]*\n\n原始事件：\n{ev_text}")

            if payload.include_critique and chap_text:
                critique_prompt = f"""你是写作教练。下方是一章新写出的小说，给作者一段 80-160 字的简短点评。

世界基调：{(world.rules or {}).get('tone','')}
本章原始事件清单（看是否被妥善表达）：
{ev_text}

本章正文：
{chap_text[:3000]}

要求点评聚焦：
- 伏笔/钩子：本章埋了或回收了哪些
- 角色弧：哪些角色的状态、关系、动机有推进
- 节奏：是否拖沓或过快
- 一个**具体可执行**的修改建议

格式：纯文本，不要标题，2-3 段。"""
                try:
                    cr = provider.chat(
                        system=critique_prompt,
                        messages=[Message(role="user", content="给出点评。")],
                        tools=[], max_tokens=600, temperature=0.5,
                    )
                    crit = (cr.text or "").strip()
                    if crit:
                        chapters_md.append("")
                        chapters_md.append(f"> 📝 **编辑笔记**\n>\n> " + crit.replace("\n", "\n> "))
                except Exception as e:
                    log.warning("critique failed: %s", e)
            chapters_md.append("")

        return {
            "format": "markdown",
            "filename": f"{world.name}_小说_{tick_lo}-{tick_hi}.md",
            "content": "\n".join(chapters_md),
            "chapters": len(chunks),
            "chunked_by": "markers" if markers else "size",
        }

    raise HTTPException(400, f"unknown mode: {payload.mode}")


@router.get("/entities/{entity_id}/arc")
def entity_arc(entity_id: str, db: Session = Depends(get_db)):
    ent = db.query(Entity).filter_by(id=entity_id).first()
    if not ent:
        raise HTTPException(404, "entity not found")
    branch_id = ent.branch_id

    events = (
        db.query(Event).filter_by(branch_id=branch_id, deleted=0)
        .order_by(Event.tick).all()
    )
    relevant = [ev for ev in events if entity_id in (ev.participants or [])]

    nar = (
        db.query(NarrativeLog).filter_by(branch_id=branch_id)
        .order_by(NarrativeLog.tick).all()
    )
    nar_by_tick: dict[int, list[str]] = {}
    for n in nar:
        nar_by_tick.setdefault(n.tick, []).append(n.text)

    by_id = {e.id: e for e in db.query(Entity).filter_by(branch_id=branch_id).all()}

    arc = []
    for ev in relevant:
        co_parts = [by_id[p].name for p in (ev.participants or []) if p != entity_id and p in by_id]
        loc = by_id.get(ev.location_id).name if ev.location_id and ev.location_id in by_id else ""
        narration_snippets = []
        for txt in nar_by_tick.get(ev.tick, []):
            if ent.name and ent.name in txt:
                snip = txt[:240] + ("…" if len(txt) > 240 else "")
                narration_snippets.append(snip)
        arc.append({
            "event_id": ev.id, "tick": ev.tick, "title": ev.title,
            "description": ev.description, "location": loc,
            "co_participants": co_parts,
            "narration": narration_snippets,
            "metadata": ev.metadata_ or {},
        })

    relations_now = (ent.attributes or {}).get("_relations") or {}
    rel_map = []
    if isinstance(relations_now, dict):
        for other_id, label in relations_now.items():
            other = by_id.get(other_id)
            if other:
                rel_map.append({"other_id": other_id, "other_name": other.name, "label": label})

    return {
        "entity": {
            "id": ent.id, "name": ent.name, "type": ent.type,
            "summary": ent.summary or "", "alive": ent.alive,
            "attributes": ent.attributes or {}, "state": ent.state or {},
            "created_at_tick": ent.created_at_tick,
            "current_location": (by_id.get(ent.location_id).name if ent.location_id and ent.location_id in by_id else None),
        },
        "arc": arc,
        "current_relations": rel_map,
        "total_events": len(relevant),
    }


class EmotionInferRequest(BaseModel):
    provider: str | None = None


@router.post("/entities/{entity_id}/emotion_curve")
def infer_emotion_curve(entity_id: str, payload: EmotionInferRequest, db: Session = Depends(get_db)):
    ent = db.query(Entity).filter_by(id=entity_id).first()
    if not ent or ent.type != "character":
        raise HTTPException(404, "character not found")
    branch_id = ent.branch_id
    events = (
        db.query(Event).filter_by(branch_id=branch_id, deleted=0)
        .order_by(Event.tick).all()
    )
    relevant = [ev for ev in events if entity_id in (ev.participants or [])]
    if not relevant:
        return {"curve": [], "reason": "no events"}

    nar = (
        db.query(NarrativeLog).filter_by(branch_id=branch_id)
        .order_by(NarrativeLog.tick).all()
    )
    nar_by_tick: dict[int, list[str]] = {}
    for n in nar:
        nar_by_tick.setdefault(n.tick, []).append(n.text)

    by_id = {e.id: e for e in db.query(Entity).filter_by(branch_id=branch_id).all()}
    beats_text = []
    for ev in relevant:
        co = "、".join(by_id[p].name for p in (ev.participants or []) if p != entity_id and p in by_id)
        snippets = []
        for txt in nar_by_tick.get(ev.tick, []):
            if ent.name and ent.name in txt:
                snippets.append(txt[:200])
        snip = "；".join(snippets) if snippets else ""
        beats_text.append(f"t{ev.tick}|《{ev.title}》|同台:{co}|{ev.description[:120]}" + (f"|叙事:{snip}" if snip else ""))

    sys_prompt = f"""你是叙事情感分析师。给定角色 **{ent.name}** 的所有重要节点，估计他/她在每个节点的情感状态。

角色简介：{ent.summary or '无'}

节点序列：
{chr(10).join(beats_text)}

# 你的任务
为**每个 tick** 给出：
- valence：情感正负向，-1.0（极痛苦/绝望）到 +1.0（极喜悦/满足），允许小数
- arousal：情感强度，0.0（麻木平静）到 1.0（剧烈激动）
- emotion：1-3 字的主导情绪标签（例：愤怒/喜悦/迷茫/坚毅/悲恸/羞愧/释然）
- note：8-20 字解读，说明这个情绪从何而来

严格输出 JSON：
{{
  "curve": [
    {{"tick": 0, "valence": -0.3, "arousal": 0.5, "emotion": "迷茫", "note": "刚到陌生地，不知所措"}},
    ...
  ]
}}
不要额外说明。
"""
    provider = get_provider(payload.provider) if payload.provider else get_provider()
    try:
        resp = provider.chat(
            system=sys_prompt,
            messages=[Message(role="user", content="开始分析。")],
            tools=[], max_tokens=1800, temperature=0.4,
        )
    except Exception as e:
        log.exception("emotion failed")
        raise HTTPException(500, f"emotion infer failed: {e}")

    raw = resp.text or ""
    parsed: dict[str, Any] = {}
    try:
        s = raw.find("{"); e = raw.rfind("}")
        if s >= 0 and e > s:
            parsed = json.loads(raw[s:e+1])
    except Exception:
        log.warning("emotion parse failed: %s", raw[:200])

    curve = []
    valid_ticks = {ev.tick for ev in relevant}
    for x in (parsed.get("curve") or []):
        if not isinstance(x, dict):
            continue
        try:
            t = int(x.get("tick", -1))
        except Exception:
            continue
        if t not in valid_ticks:
            continue
        try:
            v = max(-1.0, min(1.0, float(x.get("valence", 0))))
            a = max(0.0, min(1.0, float(x.get("arousal", 0))))
        except Exception:
            v, a = 0.0, 0.5
        curve.append({
            "tick": t, "valence": round(v, 2), "arousal": round(a, 2),
            "emotion": (x.get("emotion") or "")[:6],
            "note": (x.get("note") or "")[:60],
        })
    curve.sort(key=lambda x: x["tick"])

    attrs = dict(ent.attributes or {})
    attrs["_emotion_curve"] = curve
    ent.attributes = attrs
    db.commit()
    return {"curve": curve, "raw_ok": bool(parsed)}


class PersonaExtractRequest(BaseModel):
    branch_id: str | None = None
    provider: str | None = None


@router.post("/entities/{entity_id}/extract_persona")
def extract_persona_route(entity_id: str, payload: PersonaExtractRequest, db: Session = Depends(get_db)):
    """Reverse-engineer a character's persona from their event history.

    Returns a *suggestion* — does not write to DB. Frontend shows it side-by-side
    with the current persona and lets the user decide what to keep.
    """
    from ..engine.persona_extract import extract_persona
    ent = db.query(Entity).filter_by(id=entity_id).first()
    if not ent:
        raise HTTPException(404, "entity not found")
    if ent.type != "character":
        raise HTTPException(400, "only characters have persona")
    provider = get_provider(payload.provider) if payload.provider else None
    try:
        return extract_persona(db, entity_id,
                               branch_id=payload.branch_id, provider=provider)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        log.exception("persona extract failed")
        raise HTTPException(500, f"extract failed: {e}")


# ============== world templates ==============

class TemplateIn(BaseModel):
    name: str
    category: str = ""
    description: str = ""
    long_description: str = ""
    cover_emoji: str = "📖"
    rules: dict = Field(default_factory=dict)
    seed_directive: str = ""
    suggested_steps: list[str] = Field(default_factory=list)
    seed_entities: list[dict] = Field(default_factory=list)
    canonical_outline: list[dict] = Field(default_factory=list)
    series: str = ""
    series_order: int = 0
    max_steps_hint: int = 30
    tags: list[str] = Field(default_factory=list)
    author: str = "user"
    is_official: bool = False


def _template_to_dict(t: WorldTemplate) -> dict:
    return {
        "id": t.id, "name": t.name, "category": t.category or "",
        "description": t.description or "", "long_description": t.long_description or "",
        "cover_emoji": t.cover_emoji or "📖",
        "rules": t.rules or {}, "seed_directive": t.seed_directive or "",
        "suggested_steps": t.suggested_steps or [], "seed_entities": t.seed_entities or [],
        "canonical_outline": t.canonical_outline or [],
        "series": t.series or "", "series_order": t.series_order or 0,
        "max_steps_hint": t.max_steps_hint or 30,
        "tags": t.tags or [], "author": t.author or "user",
        "is_official": bool(t.is_official), "use_count": t.use_count or 0,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


@router.get("/templates")
def list_templates(category: str | None = None, db: Session = Depends(get_db)):
    q = db.query(WorldTemplate)
    if category:
        q = q.filter(WorldTemplate.category == category)
    rows = q.order_by(WorldTemplate.is_official.desc(), WorldTemplate.use_count.desc(), WorldTemplate.name).all()
    cats = sorted({(r.category or "").strip() for r in db.query(WorldTemplate).all() if (r.category or "").strip()})
    return {
        "templates": [_template_to_dict(r) for r in rows],
        "categories": cats,
        "total": len(rows),
    }


@router.get("/templates/{template_id}")
def get_template(template_id: str, db: Session = Depends(get_db)):
    t = db.query(WorldTemplate).filter_by(id=template_id).first()
    if not t:
        raise HTTPException(404, "template not found")
    return _template_to_dict(t)


@router.post("/templates")
def create_template(payload: TemplateIn, db: Session = Depends(get_db)):
    t = WorldTemplate(
        id=f"tpl_{uuid.uuid4().hex[:10]}",
        name=payload.name.strip() or "未命名模板",
        category=payload.category.strip(),
        description=payload.description.strip(),
        long_description=payload.long_description,
        cover_emoji=(payload.cover_emoji or "📖")[:8],
        rules=payload.rules or {},
        seed_directive=payload.seed_directive,
        suggested_steps=payload.suggested_steps or [],
        seed_entities=payload.seed_entities or [],
        canonical_outline=payload.canonical_outline or [],
        series=payload.series.strip(),
        series_order=int(payload.series_order or 0),
        max_steps_hint=max(1, min(200, int(payload.max_steps_hint or 30))),
        tags=payload.tags or [],
        author=payload.author or "user",
        is_official=1 if payload.is_official else 0,
    )
    db.add(t); db.commit()
    return _template_to_dict(t)


@router.put("/templates/{template_id}")
def update_template(template_id: str, payload: TemplateIn, db: Session = Depends(get_db)):
    t = db.query(WorldTemplate).filter_by(id=template_id).first()
    if not t:
        raise HTTPException(404, "template not found")
    t.name = payload.name.strip() or t.name
    t.category = payload.category.strip()
    t.description = payload.description.strip()
    t.long_description = payload.long_description
    t.cover_emoji = (payload.cover_emoji or t.cover_emoji or "📖")[:8]
    t.rules = payload.rules or {}
    t.seed_directive = payload.seed_directive
    t.suggested_steps = payload.suggested_steps or []
    t.seed_entities = payload.seed_entities or []
    t.canonical_outline = payload.canonical_outline or []
    t.series = payload.series.strip()
    t.series_order = int(payload.series_order or 0)
    t.max_steps_hint = max(1, min(200, int(payload.max_steps_hint or 30)))
    t.tags = payload.tags or []
    t.is_official = 1 if payload.is_official else 0
    t.updated_at = datetime.utcnow()
    db.commit()
    return _template_to_dict(t)


@router.delete("/templates/{template_id}")
def delete_template(template_id: str, db: Session = Depends(get_db)):
    t = db.query(WorldTemplate).filter_by(id=template_id).first()
    if not t:
        raise HTTPException(404, "template not found")
    db.delete(t); db.commit()
    return {"ok": True}


class InstantiateRequest(BaseModel):
    name_override: str | None = None
    auto_step: bool = True


@router.post("/templates/{template_id}/instantiate")
def instantiate_template(template_id: str, payload: InstantiateRequest, db: Session = Depends(get_db)):
    t = db.query(WorldTemplate).filter_by(id=template_id).first()
    if not t:
        raise HTTPException(404, "template not found")

    world_name = (payload.name_override or t.name).strip() or "新世界"
    world = World(
        id=_new_id("w"), name=world_name,
        description=t.description or "",
        outline=(t.long_description or "").strip(),
        rules=t.rules or {}, current_tick=0,
        template_id=t.id,
        outline_progress={"current_index": 0, "completed": []},
        max_tick=int(t.max_steps_hint or 30),
    )
    db.add(world); db.flush()
    main = Branch(id=_new_id("b"), world_id=world.id, name="main", description="主分支", diverged_at_tick=0)
    db.add(main); db.flush()
    world.active_branch_id = main.id

    for raw in (t.seed_entities or []):
        if not isinstance(raw, dict):
            continue
        ent = Entity(
            id=_new_id("ent"), branch_id=main.id,
            type=(raw.get("type") or "character").strip(),
            name=(raw.get("name") or "").strip() or "未命名",
            summary=raw.get("summary") or "",
            attributes=raw.get("attributes") or {},
            state=raw.get("state") or {},
            created_at_tick=0, alive=1,
        )
        db.add(ent)

    t.use_count = (t.use_count or 0) + 1
    db.commit()
    return {
        "world_id": world.id, "branch_id": main.id,
        "seed_directive": t.seed_directive or "",
        "suggested_steps": t.suggested_steps or [],
    }


class SaveAsTemplateRequest(BaseModel):
    name: str
    category: str = ""
    description: str = ""
    cover_emoji: str = "📖"
    tags: list[str] = Field(default_factory=list)
    include_entities: bool = True


@router.post("/worlds/{world_id}/save_as_template")
def save_as_template(world_id: str, payload: SaveAsTemplateRequest, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    branch_id = world.active_branch_id
    seed_entities = []
    if payload.include_entities:
        ents = db.query(Entity).filter_by(branch_id=branch_id).all()
        for e in ents:
            attrs = dict(e.attributes or {})
            attrs.pop("_relations", None)
            attrs.pop("_emotion_curve", None)
            seed_entities.append({
                "type": e.type, "name": e.name, "summary": e.summary or "",
                "attributes": attrs, "state": e.state or {},
            })
    t = WorldTemplate(
        id=f"tpl_{uuid.uuid4().hex[:10]}",
        name=payload.name.strip() or world.name,
        category=payload.category.strip(),
        description=payload.description.strip() or world.description or "",
        long_description="",
        cover_emoji=(payload.cover_emoji or "📖")[:8],
        rules=world.rules or {},
        seed_directive="",
        suggested_steps=[],
        seed_entities=seed_entities,
        tags=payload.tags or [],
        author="user",
        is_official=0,
    )
    db.add(t); db.commit()
    return _template_to_dict(t)


# ============== outline progress + series upgrade ==============

class OutlineProgressUpdate(BaseModel):
    current_index: int | None = None
    completed: list[int] | None = None


@router.get("/worlds/{world_id}/outline")
def get_outline(world_id: str, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    outline: list[dict] = []
    if world.template_id:
        t = db.query(WorldTemplate).filter_by(id=world.template_id).first()
        if t:
            outline = list(t.canonical_outline or [])
    progress = world.outline_progress or {}
    return {
        "outline": outline,
        "current_index": int(progress.get("current_index", 0)),
        "completed": list(progress.get("completed", [])),
        "max_tick": world.max_tick or 0,
        "current_tick": world.current_tick,
        "template_id": world.template_id,
    }


@router.post("/worlds/{world_id}/outline_progress")
def update_outline_progress(world_id: str, payload: OutlineProgressUpdate, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    progress = dict(world.outline_progress or {})
    if payload.current_index is not None:
        progress["current_index"] = max(0, payload.current_index)
    if payload.completed is not None:
        progress["completed"] = sorted({int(i) for i in payload.completed if isinstance(i, (int, float))})
    world.outline_progress = progress
    db.commit()
    return progress


class MaxTickUpdate(BaseModel):
    max_tick: int


@router.post("/worlds/{world_id}/max_tick")
def update_max_tick(world_id: str, payload: MaxTickUpdate, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    world.max_tick = max(0, int(payload.max_tick))
    db.commit()
    return {"max_tick": world.max_tick, "current_tick": world.current_tick}


class UpgradeRequest(BaseModel):
    target_template_id: str
    keep_entities: bool = True
    add_max_steps: int | None = None


@router.post("/worlds/{world_id}/upgrade_to_template")
def upgrade_to_template(world_id: str, payload: UpgradeRequest, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    target = db.query(WorldTemplate).filter_by(id=payload.target_template_id).first()
    if not target:
        raise HTTPException(404, "target template not found")

    extra_steps = int(payload.add_max_steps) if payload.add_max_steps is not None else int(target.max_steps_hint or 30)
    world.template_id = target.id
    world.rules = target.rules or {}
    world.outline_progress = {"current_index": 0, "completed": []}
    world.max_tick = world.current_tick + max(1, extra_steps)
    if target.description and not world.description:
        world.description = target.description

    if payload.keep_entities:
        existing_names = {
            e.name for e in db.query(Entity).filter_by(branch_id=world.active_branch_id).all()
        }
        for raw in (target.seed_entities or []):
            if not isinstance(raw, dict):
                continue
            nm = (raw.get("name") or "").strip()
            if not nm or nm in existing_names:
                continue
            ent = Entity(
                id=_new_id("ent"), branch_id=world.active_branch_id,
                type=(raw.get("type") or "character").strip(),
                name=nm, summary=raw.get("summary") or "",
                attributes=raw.get("attributes") or {},
                state=raw.get("state") or {},
                created_at_tick=world.current_tick, alive=1,
            )
            db.add(ent)

    transition_text = f"【进入新篇章：{target.name}】{target.seed_directive}".strip()
    nl = NarrativeLog(
        id=_new_id("nl"), branch_id=world.active_branch_id,
        tick=world.current_tick, text=transition_text,
    )
    db.add(nl)
    target.use_count = (target.use_count or 0) + 1
    db.commit()
    return {
        "ok": True, "world_id": world.id,
        "template_id": target.id, "template_name": target.name,
        "current_tick": world.current_tick, "max_tick": world.max_tick,
        "seed_directive": target.seed_directive,
        "suggested_steps": target.suggested_steps or [],
    }


@router.get("/series/{series}")
def get_series(series: str, db: Session = Depends(get_db)):
    rows = (
        db.query(WorldTemplate).filter_by(series=series)
        .order_by(WorldTemplate.series_order).all()
    )
    return {"series": series, "templates": [_template_to_dict(r) for r in rows]}


def _id_prefix_for(old_id: str) -> str:
    if "_" in old_id:
        return old_id.split("_", 1)[0]
    return "ent"


class EntityIn(BaseModel):
    type: str
    name: str
    summary: str = ""
    attributes: dict[str, Any] = Field(default_factory=dict)
    location_id: str | None = None
    persona: dict[str, Any] | None = None
    memories: list[dict[str, Any]] | None = None


@router.post("/worlds/{world_id}/entities")
def add_entity(world_id: str, payload: EntityIn, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    e = Entity(
        id=_new_id("ent"), branch_id=world.active_branch_id, type=payload.type, name=payload.name,
        summary=payload.summary, attributes=payload.attributes, state={}, location_id=payload.location_id,
        persona=payload.persona or {}, memories=payload.memories or [],
        created_at_tick=world.current_tick, alive=1,
    )
    db.add(e); db.commit()
    return {"id": e.id}


class EntityPatch(BaseModel):
    name: str | None = None
    summary: str | None = None
    attributes: dict[str, Any] | None = None
    state: dict[str, Any] | None = None
    persona: dict[str, Any] | None = None
    memories: list[dict[str, Any]] | None = None
    alive: int | None = None


@router.patch("/entities/{entity_id}")
def patch_entity(entity_id: str, payload: EntityPatch, db: Session = Depends(get_db)):
    e = db.query(Entity).filter_by(id=entity_id).first()
    if not e:
        raise HTTPException(404, "entity not found")
    if payload.name is not None: e.name = payload.name
    if payload.summary is not None: e.summary = payload.summary
    if payload.attributes is not None: e.attributes = payload.attributes
    if payload.state is not None: e.state = payload.state
    if payload.persona is not None: e.persona = payload.persona
    if payload.memories is not None: e.memories = payload.memories
    if payload.alive is not None: e.alive = int(payload.alive)
    db.commit()
    return {"ok": True, "id": e.id}


@router.get("/worlds/{world_id}/characters/{character_id}/view")
def character_view(world_id: str, character_id: str, sight: int = 8, max_events: int = 25, db: Session = Depends(get_db)):
    """Return the world as `character_id` perceives it."""
    from ..engine.character_view import build_character_view, view_as_prompt
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    try:
        view = build_character_view(db, world, character_id, sight_radius=sight, max_events=max_events)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {**view, "prompt": view_as_prompt(view)}


class EventIn(BaseModel):
    title: str
    description: str = ""
    tick: int | None = None
    participants: list[str] = Field(default_factory=list)
    location_id: str | None = None


@router.post("/worlds/{world_id}/events")
def add_event(world_id: str, payload: EventIn, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    e = Event(
        id=_new_id("evt"), branch_id=world.active_branch_id,
        tick=payload.tick if payload.tick is not None else world.current_tick,
        title=payload.title, description=payload.description,
        participants=payload.participants, location_id=payload.location_id, consequences=[], metadata_={},
        deleted=0,
    )
    db.add(e); db.flush()
    from ..engine.executor import _append_event_to_participant_memories
    _append_event_to_participant_memories(db, world.active_branch_id, e)
    db.commit()
    return {"id": e.id, "tick": e.tick}


class EventPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    tick: int | None = None
    participants: list[str] | None = None
    location_id: str | None = None
    consequences: list[str] | None = None


@router.patch("/events/{event_id}")
def patch_event(event_id: str, payload: EventPatch, db: Session = Depends(get_db)):
    e = db.query(Event).filter_by(id=event_id).first()
    if not e:
        raise HTTPException(404, "event not found")
    if payload.title is not None: e.title = payload.title
    if payload.description is not None: e.description = payload.description
    if payload.tick is not None: e.tick = int(payload.tick)
    if payload.participants is not None: e.participants = payload.participants
    if payload.location_id is not None: e.location_id = payload.location_id
    if payload.consequences is not None: e.consequences = payload.consequences
    meta = dict(e.metadata_ or {})
    meta["user_edited"] = True
    e.metadata_ = meta
    db.commit()
    return {"ok": True}


@router.delete("/events/{event_id}")
def delete_event(event_id: str, db: Session = Depends(get_db)):
    e = db.query(Event).filter_by(id=event_id).first()
    if not e:
        raise HTTPException(404, "event not found")
    e.deleted = 1
    meta = dict(e.metadata_ or {})
    meta["user_deleted"] = True
    e.metadata_ = meta
    db.commit()
    return {"ok": True, "soft_deleted": True}


@router.post("/events/{event_id}/restore")
def restore_event(event_id: str, db: Session = Depends(get_db)):
    e = db.query(Event).filter_by(id=event_id).first()
    if not e:
        raise HTTPException(404, "event not found")
    e.deleted = 0
    db.commit()
    return {"ok": True}


class CausalityIn(BaseModel):
    cause_event_id: str
    effect_event_id: str
    description: str = ""
    weight: float = 1.0


@router.post("/worlds/{world_id}/causality")
def add_causality(world_id: str, payload: CausalityIn, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    bid = world.active_branch_id
    cause = db.query(Event).filter_by(id=payload.cause_event_id, branch_id=bid).first()
    effect = db.query(Event).filter_by(id=payload.effect_event_id, branch_id=bid).first()
    if not cause or not effect:
        raise HTTPException(400, "cause/effect event not found in active branch")
    if cause.id == effect.id:
        raise HTTPException(400, "cannot link an event to itself")
    existing = db.query(CausalLink).filter_by(
        branch_id=bid, cause_event_id=cause.id, effect_event_id=effect.id
    ).first()
    if existing:
        if payload.description: existing.description = payload.description
        existing.weight = payload.weight
        db.commit()
        return {"ok": True, "id": existing.id, "updated": True}
    link = CausalLink(
        id=_new_id("cau"), branch_id=bid,
        cause_event_id=cause.id, effect_event_id=effect.id,
        description=payload.description, weight=payload.weight,
    )
    db.add(link); db.commit()
    return {"ok": True, "id": link.id}


class CausalityPatch(BaseModel):
    description: str | None = None
    weight: float | None = None


@router.patch("/causality")
def patch_causality(cause: str, effect: str, payload: CausalityPatch, db: Session = Depends(get_db)):
    link = db.query(CausalLink).filter_by(cause_event_id=cause, effect_event_id=effect).first()
    if not link:
        raise HTTPException(404, "link not found")
    if payload.description is not None: link.description = payload.description
    if payload.weight is not None: link.weight = payload.weight
    db.commit()
    return {"ok": True}


@router.delete("/causality")
def delete_causality(cause: str, effect: str, db: Session = Depends(get_db)):
    n = db.query(CausalLink).filter_by(cause_event_id=cause, effect_event_id=effect).delete()
    db.commit()
    return {"ok": True, "deleted": n}


class ReconcileRequest(BaseModel):
    user_changes: list[str] = Field(default_factory=list, description="人话描述用户的改动")
    seed_event_ids: list[str] = Field(default_factory=list, description="被直接改动的事件 id（用于 BFS 找下游）")
    branch: bool = True
    branch_name: str | None = None
    provider: str | None = None


@router.post("/worlds/{world_id}/reconcile")
def reconcile(world_id: str, payload: ReconcileRequest, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")

    new_branch_id: str | None = None
    if payload.branch:
        parent_id = world.active_branch_id
        new_branch = Branch(
            id=_new_id("br"),
            world_id=world.id,
            name=payload.branch_name or f"reconcile@t{world.current_tick}",
            description="AI 调和分支",
            parent_branch_id=parent_id,
            diverged_at_tick=world.current_tick,
        )
        db.add(new_branch); db.flush()
        for entity in db.query(Entity).filter_by(branch_id=parent_id).all():
            db.add(Entity(
                id=_new_id("ent"), branch_id=new_branch.id, type=entity.type, name=entity.name,
                summary=entity.summary, attributes=dict(entity.attributes or {}),
                state=dict(entity.state or {}), location_id=entity.location_id,
                created_at_tick=entity.created_at_tick, alive=entity.alive,
            ))
        old_to_new: dict[str, str] = {}
        for ev in db.query(Event).filter_by(branch_id=parent_id).all():
            new_id = _new_id("evt")
            old_to_new[ev.id] = new_id
            db.add(Event(
                id=new_id, branch_id=new_branch.id, tick=ev.tick, title=ev.title,
                description=ev.description, location_id=ev.location_id,
                participants=list(ev.participants or []), consequences=list(ev.consequences or []),
                metadata_=dict(ev.metadata_ or {}), deleted=ev.deleted,
            ))
        for l in db.query(CausalLink).filter_by(branch_id=parent_id).all():
            db.add(CausalLink(
                id=_new_id("cau"), branch_id=new_branch.id,
                cause_event_id=old_to_new.get(l.cause_event_id, l.cause_event_id),
                effect_event_id=old_to_new.get(l.effect_event_id, l.effect_event_id),
                description=l.description, weight=l.weight,
            ))
        for n in db.query(NarrativeLog).filter_by(branch_id=parent_id).all():
            db.add(NarrativeLog(
                id=_new_id("nar"), branch_id=new_branch.id, tick=n.tick, role=n.role, text=n.text,
            ))
        world.active_branch_id = new_branch.id
        new_branch_id = new_branch.id
        seed_event_ids = [old_to_new.get(eid, eid) for eid in payload.seed_event_ids]
        db.commit()
    else:
        seed_event_ids = list(payload.seed_event_ids)

    provider = get_provider(payload.provider) if payload.provider else None
    try:
        result = run_reconcile(db, world, payload.user_changes, seed_event_ids, provider=provider)
    except Exception as e:
        raise HTTPException(500, f"reconcile failed: {e}")

    result["branch_id"] = world.active_branch_id
    result["new_branch_created"] = new_branch_id is not None
    return result


PROVIDER_META = {
    "claude": {
        "label": "Claude (Anthropic)",
        "needs_api_key": True,
        "default_models": ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
        "homepage": "https://console.anthropic.com",
    },
    "openai": {
        "label": "OpenAI",
        "needs_api_key": True,
        "default_models": ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo"],
        "homepage": "https://platform.openai.com",
    },
    "deepseek": {
        "label": "DeepSeek",
        "needs_api_key": True,
        "default_models": ["deepseek-chat", "deepseek-reasoner"],
        "homepage": "https://platform.deepseek.com",
    },
    "ollama": {
        "label": "Ollama (本地)",
        "needs_api_key": False,
        "default_models": ["llama3.1", "qwen2.5", "mistral", "deepseek-r1"],
        "homepage": "https://ollama.com",
    },
}


@router.get("/llm_config")
def get_llm_config():
    cfg = load_config()
    return {"config": mask(cfg), "meta": PROVIDER_META}


class LLMConfigUpdate(BaseModel):
    active: str | None = None
    providers: dict[str, dict[str, Any]] | None = None


@router.post("/llm_config")
def update_llm_config(payload: LLMConfigUpdate):
    updates = {}
    if payload.active:
        if payload.active not in PROVIDER_CLASSES:
            raise HTTPException(400, f"unknown provider: {payload.active}")
        updates["active"] = payload.active
    if payload.providers:
        updates["providers"] = payload.providers
    cfg = save_config(updates)
    return {"ok": True, "config": mask(cfg)}


class LLMTestRequest(BaseModel):
    provider: str


@router.post("/llm_config/test")
def test_llm_config(payload: LLMTestRequest):
    if payload.provider not in PROVIDER_CLASSES:
        raise HTTPException(400, f"unknown provider: {payload.provider}")
    import time
    t0 = time.time()
    try:
        provider = get_provider(payload.provider)
        cfg = load_config()["providers"].get(payload.provider, {})
        if payload.provider != "ollama" and not cfg.get("api_key"):
            return {"ok": False, "error": "未配置 API Key（请先粘贴 Key 再点测试）", "elapsed": 0}
        resp = provider.chat(
            system="You are a connectivity test endpoint. Reply with exactly: OK",
            messages=[Message(role="user", content="ping")],
            tools=[],
            max_tokens=16,
            temperature=0.0,
            timeout=60.0,
        )
        return {
            "ok": True,
            "reply": (resp.text or "(空回复)").strip()[:200],
            "usage": resp.usage,
            "elapsed": round(time.time() - t0, 2),
            "model": getattr(provider, "model", ""),
            "base_url": getattr(provider, "base_url", ""),
        }
    except httpx.ConnectTimeout:
        return {"ok": False, "error": f"连接超时（无法在 60 秒内建立到 API 的连接，可能被网络阻断）", "elapsed": round(time.time() - t0, 2)}
    except httpx.ReadTimeout:
        return {"ok": False, "error": f"读取超时（已建立连接但 60 秒内未收到响应，API 可能拥堵）", "elapsed": round(time.time() - t0, 2)}
    except httpx.HTTPStatusError as e:
        body = ""
        try:
            body = e.response.text[:300]
        except Exception:
            pass
        return {"ok": False, "error": f"HTTP {e.response.status_code}: {body}", "elapsed": round(time.time() - t0, 2)}
    except httpx.ConnectError as e:
        return {"ok": False, "error": f"连接失败: {e}（DNS 解析失败或网络不通）", "elapsed": round(time.time() - t0, 2)}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}", "elapsed": round(time.time() - t0, 2)}


@router.get("/providers")
def list_providers():
    cfg = load_config()
    return {
        "current": cfg["active"],
        "available": list(PROVIDER_CLASSES.keys()),
        "models": {k: v.get("model") for k, v in cfg["providers"].items()},
    }


# ===================== 一致性扫描 =====================
from ..engine.consistency import run_scan as _run_scan, CATEGORY_LABELS as _CAT_LABELS


def _issue_dict(i: ConsistencyIssue) -> dict:
    return {
        "id": i.id, "world_id": i.world_id, "branch_id": i.branch_id,
        "category": i.category, "category_label": _CAT_LABELS.get(i.category, "其它"),
        "severity": i.severity, "title": i.title,
        "description": i.description, "suggestion": i.suggestion,
        "entity_ids": i.entity_ids or [],
        "tick_start": i.tick_start, "tick_end": i.tick_end,
        "status": i.status, "scan_id": i.scan_id,
        "created_at": i.created_at.isoformat() if i.created_at else None,
        "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
    }


def _scan_dict(s: ScanRun) -> dict:
    return {
        "id": s.id, "world_id": s.world_id, "scope": s.scope,
        "tick_from": s.tick_from, "tick_to": s.tick_to,
        "issue_count": s.issue_count, "status": s.status, "error": s.error,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


class ScanRequest(BaseModel):
    scope: str = "recent"
    tick_from: Optional[int] = None
    tick_to: Optional[int] = None
    provider: Optional[str] = None


@router.post("/worlds/{world_id}/scan_consistency")
def scan_consistency(world_id: str, payload: ScanRequest, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    run = _run_scan(
        db, world,
        scope=payload.scope or "recent",
        tick_from=payload.tick_from, tick_to=payload.tick_to,
        provider_key=payload.provider,
    )
    issues = (
        db.query(ConsistencyIssue)
        .filter_by(scan_id=run.id)
        .order_by(ConsistencyIssue.created_at.desc())
        .all()
    )
    return {"scan": _scan_dict(run), "issues": [_issue_dict(i) for i in issues]}


@router.get("/worlds/{world_id}/issues")
def list_issues(
    world_id: str,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(ConsistencyIssue).filter_by(world_id=world_id)
    if status:
        q = q.filter(ConsistencyIssue.status == status)
    issues = q.order_by(ConsistencyIssue.created_at.desc()).limit(200).all()
    runs = (
        db.query(ScanRun).filter_by(world_id=world_id)
        .order_by(ScanRun.created_at.desc()).limit(20).all()
    )
    counts = {
        "open": db.query(ConsistencyIssue).filter_by(world_id=world_id, status="open").count(),
        "ignored": db.query(ConsistencyIssue).filter_by(world_id=world_id, status="ignored").count(),
        "resolved": db.query(ConsistencyIssue).filter_by(world_id=world_id, status="resolved").count(),
    }
    return {
        "issues": [_issue_dict(i) for i in issues],
        "scans": [_scan_dict(s) for s in runs],
        "counts": counts,
    }


class IssueUpdate(BaseModel):
    status: str


@router.patch("/issues/{issue_id}")
def update_issue(issue_id: str, payload: IssueUpdate, db: Session = Depends(get_db)):
    issue = db.query(ConsistencyIssue).filter_by(id=issue_id).first()
    if not issue:
        raise HTTPException(404, "issue not found")
    if payload.status not in ("open", "ignored", "resolved"):
        raise HTTPException(400, "invalid status")
    issue.status = payload.status
    if payload.status in ("ignored", "resolved"):
        issue.resolved_at = datetime.utcnow()
    else:
        issue.resolved_at = None
    db.commit()
    return _issue_dict(issue)


@router.delete("/issues/{issue_id}")
def delete_issue(issue_id: str, db: Session = Depends(get_db)):
    issue = db.query(ConsistencyIssue).filter_by(id=issue_id).first()
    if not issue:
        raise HTTPException(404, "issue not found")
    db.delete(issue)
    db.commit()
    return {"ok": True}


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
