"""手稿（V1 + V2）相关 API。

包含 6 个端点：
- POST /worlds/from_manuscript             V1：上传手稿建世界（同步，小文本用）
- POST /worlds/from_manuscript_async       V1：上传手稿建世界（异步 job，长篇用）
- GET  /worlds/{id}/manuscript/state       返回章节列表 + draft 事件
- POST /worlds/{id}/manuscript/extract_events_async  V2：异步抽事件 + 因果
- POST /worlds/{id}/manuscript/commit_events         审阅后落库
- DEL  /worlds/{id}/manuscript/draft       丢弃草稿
"""
from __future__ import annotations
import logging
import threading
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..models import (
    get_db, SessionLocal, World, Branch, Entity, Event, CausalLink, ManuscriptChunk,
)
from ..engine import create_job
from ._common import _new_id

log = logging.getLogger(__name__)
router = APIRouter()


# ─── chunk 表读写 helper ─────────────────────────────────────

def _load_chunks(db: Session, world_id: str) -> list[dict]:
    rows = (
        db.query(ManuscriptChunk)
        .filter_by(world_id=world_id)
        .order_by(ManuscriptChunk.chapter_index)
        .all()
    )
    if rows:
        return [{"title": r.title, "text": r.text} for r in rows]
    # fallback: 从旧 JSON 字段迁移
    world = db.query(World).filter_by(id=world_id).first()
    legacy = (world.manuscript_chunks or []) if world else []
    if legacy:
        _save_chunks(db, world_id, legacy)
    return legacy


def _save_chunks(db: Session, world_id: str, chunks: list[dict]):
    db.query(ManuscriptChunk).filter_by(world_id=world_id).delete()
    for i, c in enumerate(chunks):
        db.add(ManuscriptChunk(
            world_id=world_id,
            chapter_index=i + 1,
            title=str(c.get("title") or "")[:500],
            text=str(c.get("text") or ""),
        ))
    db.flush()


# ─── V1：从手稿建世界 ────────────────────────────────────────────

class ManuscriptIngest(BaseModel):
    name: str
    text: str
    description: str = ""


@router.post("/worlds/from_manuscript")
def create_world_from_manuscript(payload: ManuscriptIngest, db: Session = Depends(get_db)):
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    text = payload.text or ""
    if len(text) < 50:
        raise HTTPException(400, "manuscript text too short (min 50 chars)")

    from ..engine.manuscript_ingest import ingest_manuscript, render_outline_text

    result = ingest_manuscript(world_name=name, text=text)
    if not result.chunks:
        raise HTTPException(400, "; ".join(result.warnings) or "无法解析手稿")

    world = World(
        id=_new_id("w"),
        name=name,
        description=payload.description or result.setting,
        outline=render_outline_text(result.outline),
        rules={},
        current_tick=0,
        manuscript_draft_events=[],
    )
    db.add(world)
    db.flush()
    _save_chunks(db, world.id, [{"title": c.title, "text": c.text} for c in result.chunks])

    main = Branch(
        id=_new_id("br"), world_id=world.id, name="main",
        description="主世界线（从手稿导入）", parent_branch_id=None, diverged_at_tick=0,
    )
    db.add(main)
    db.flush()
    world.active_branch_id = main.id

    cast_count = 0
    for c in result.cast:
        aliases = [a for a in (c.get("aliases") or []) if a and a != c["name"]]
        db.add(Entity(
            id=_new_id("ent"), branch_id=main.id, type="character",
            name=c["name"], summary=c.get("summary", ""),
            attributes={},
            aliases=aliases,
            state={},
            tags=c.get("tags") or [],
            pinned=1 if cast_count < 5 else 0,
            persona={}, memories=[],
            created_at_tick=0, alive=1,
        ))
        cast_count += 1

    for loc in result.locations:
        db.add(Entity(
            id=_new_id("ent"), branch_id=main.id, type="location",
            name=loc["name"], summary=loc.get("summary", ""),
            attributes={}, state={}, tags=[], persona={}, memories=[],
            created_at_tick=0, alive=1,
        ))
    for fac in result.factions:
        db.add(Entity(
            id=_new_id("ent"), branch_id=main.id, type="faction",
            name=fac["name"], summary=fac.get("summary", ""),
            attributes={}, state={}, tags=[], persona={}, memories=[],
            created_at_tick=0, alive=1,
        ))

    db.commit()
    return {
        "ok": True,
        "world_id": world.id,
        "active_branch_id": main.id,
        "stats": {
            "chunks": len(result.chunks),
            "outline": len(result.outline),
            "cast": len(result.cast),
            "locations": len(result.locations),
            "factions": len(result.factions),
        },
        "warnings": result.warnings,
    }


# ─── V1：异步从手稿建世界 ──────────────────────────────────────

@router.post("/worlds/from_manuscript_async")
def create_world_from_manuscript_async(payload: ManuscriptIngest, db: Session = Depends(get_db)):
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    text = payload.text or ""
    if len(text) < 50:
        raise HTTPException(400, "manuscript text too short (min 50 chars)")

    job = create_job("", "manuscript_ingest")
    job.status = "running"
    job.progress_message = "正在切分章节…"

    def runner():
        local_db = SessionLocal()
        try:
            from ..engine.manuscript_ingest import ingest_manuscript, render_outline_text

            def progress(msg: str, done: int, total: int):
                job.progress_message = f"{msg}（{done}/{total}）"

            result = ingest_manuscript(
                world_name=name, text=text,
                on_progress=progress,
            )

            if job.is_cancelled():
                job.status = "cancelled"
                job.progress_message = "已取消"
                return

            if not result.chunks:
                job.status = "error"
                job.progress_message = "; ".join(result.warnings) or "无法解析手稿"
                return

            world = World(
                id=_new_id("w"),
                name=name,
                description=(payload.description or "") or result.setting,
                outline=render_outline_text(result.outline),
                rules={},
                current_tick=0,
                manuscript_draft_events=[],
            )
            local_db.add(world)
            local_db.flush()
            _save_chunks(local_db, world.id, [{"title": c.title, "text": c.text} for c in result.chunks])
            main = Branch(
                id=_new_id("br"), world_id=world.id, name="main",
                description="主世界线（从手稿导入）", parent_branch_id=None, diverged_at_tick=0,
            )
            local_db.add(main)
            local_db.flush()
            world.active_branch_id = main.id

            job.progress_message = "正在写入角色…"
            cast_count = 0
            for c in result.cast:
                aliases = [a for a in (c.get("aliases") or []) if a and a != c["name"]]
                local_db.add(Entity(
                    id=_new_id("ent"), branch_id=main.id, type="character",
                    name=c["name"], summary=c.get("summary", ""),
                    attributes={},
                    aliases=aliases,
                    state={},
                    tags=c.get("tags") or [],
                    pinned=1 if cast_count < 5 else 0,
                    persona={}, memories=[],
                    created_at_tick=0, alive=1,
                ))
                cast_count += 1

            for loc in result.locations:
                local_db.add(Entity(
                    id=_new_id("ent"), branch_id=main.id, type="location",
                    name=loc["name"], summary=loc.get("summary", ""),
                    attributes={}, state={}, tags=[], persona={}, memories=[],
                    created_at_tick=0, alive=1,
                ))
            for fac in result.factions:
                local_db.add(Entity(
                    id=_new_id("ent"), branch_id=main.id, type="faction",
                    name=fac["name"], summary=fac.get("summary", ""),
                    attributes={}, state={}, tags=[], persona={}, memories=[],
                    created_at_tick=0, alive=1,
                ))

            local_db.commit()

            job.status = "completed"
            job.progress_message = "世界构建完成"
            job.result = {
                "world_id": world.id,
                "active_branch_id": main.id,
                "stats": {
                    "chunks": len(result.chunks),
                    "outline": len(result.outline),
                    "cast": len(result.cast),
                    "locations": len(result.locations),
                    "factions": len(result.factions),
                },
                "warnings": result.warnings,
            }
        except Exception as e:
            log.exception("V1 async ingest failed")
            job.status = "error"
            job.progress_message = str(e)[:500]
        finally:
            local_db.close()

    threading.Thread(target=runner, daemon=True).start()

    return {
        "job_id": job.id,
        "message": "V1 手稿导入已启动，请轮询 /jobs/{job_id} 查看进度",
    }


# ─── V2：状态查询 ────────────────────────────────────────────────

@router.get("/worlds/{world_id}/manuscript/state")
def get_manuscript_state(world_id: str, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    chunks = _load_chunks(db, world_id)
    draft = world.manuscript_draft_events or []
    chapter_summaries = [
        {"index": i + 1, "title": str(c.get("title") or "")[:120], "char_count": len(str(c.get("text") or ""))}
        for i, c in enumerate(chunks)
    ]
    return {
        "has_manuscript": len(chunks) > 0,
        "chapter_count": len(chunks),
        "chapters": chapter_summaries,
        "draft_event_count": len(draft),
        "draft_events": draft,
    }


# ─── V2：异步抽事件 + 因果 ──────────────────────────────────────

class ManuscriptExtractRequest(BaseModel):
    chapter_indices: list[int] | None = None
    fact_check: bool = False  # V2: extract 后逐章对照原文核查; 失败的事件 needs_review=True


@router.post("/worlds/{world_id}/manuscript/extract_events_async")
def extract_manuscript_events_async(
    world_id: str,
    payload: ManuscriptExtractRequest | None = None,
    db: Session = Depends(get_db),
):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    chunks = _load_chunks(db, world_id)
    if not chunks:
        raise HTTPException(400, "该世界没有手稿数据，无法抽取事件")

    selected_indices = (payload.chapter_indices if payload else None)
    if selected_indices is not None:
        selected_indices = sorted({i for i in selected_indices if 1 <= i <= len(chunks)})
        if not selected_indices:
            raise HTTPException(400, "章节范围为空或越界")

    existing_draft = list(world.manuscript_draft_events or [])

    branch_id = world.active_branch_id
    name_to_id: dict[str, str] = {}
    loc_to_id: dict[str, str] = {}
    if branch_id:
        for e in db.query(Entity).filter_by(branch_id=branch_id).all():
            if e.type == "location":
                loc_to_id[e.name] = e.id
            else:
                name_to_id[e.name] = e.id
                for a in (e.aliases or []):
                    if isinstance(a, str) and a.strip() and a not in name_to_id:
                        name_to_id[a.strip()] = e.id

    job = create_job(world_id, "manuscript_events")
    job.status = "running"
    chunks_snapshot = list(chunks)
    selected_set: set[int] | None = set(selected_indices) if selected_indices else None

    def runner():
        local_db = SessionLocal()
        try:
            from ..engine.manuscript_events import extract_events, extract_causal_links, DraftEvent
            def progress(msg: str, done: int, total: int):
                job.progress_message = f"{msg}（{done}/{total}）"

            if selected_set is None:
                kept: list[dict] = []
            else:
                kept = [
                    d for d in existing_draft
                    if int(d.get("chapter_index") or 0) not in selected_set
                ]
            accumulated: list[dict] = list(kept)

            def on_batch(events):
                for ev in events:
                    accumulated.append(ev.to_dict())
                local_world = local_db.query(World).filter_by(id=world_id).first()
                if local_world:
                    local_world.manuscript_draft_events = list(accumulated)
                    local_db.commit()

            result = extract_events(
                chunks=chunks_snapshot,
                name_to_entity_id=name_to_id,
                location_name_to_id=loc_to_id,
                on_progress=progress,
                cancel_check=job.is_cancelled,
                chapter_indices=selected_indices,
                on_batch_complete=on_batch,
                fact_check=bool(payload and payload.fact_check),
            )

            if accumulated and not job.is_cancelled():
                draft_events_for_causal = [
                    DraftEvent(
                        chapter_index=int(d.get("chapter_index") or 0),
                        chapter_title=str(d.get("chapter_title") or ""),
                        title=str(d.get("title") or ""),
                        description=str(d.get("description") or ""),
                        participant_names=list(d.get("participant_names") or []),
                        participant_ids=list(d.get("participant_ids") or []),
                        unresolved_names=list(d.get("unresolved_names") or []),
                        location_name=str(d.get("location_name") or ""),
                        location_id=d.get("location_id"),
                        tick=int(d.get("tick") or 0),
                        needs_review=bool(d.get("needs_review") or False),
                        review_reason=str(d.get("review_reason") or ""),
                    )
                    for d in accumulated
                ]
                links, causal_warnings = extract_causal_links(
                    events=draft_events_for_causal,
                    on_progress=progress,
                    cancel_check=job.is_cancelled,
                )
                result.warnings.extend(causal_warnings)

                cause_map: dict[int, list[int]] = {}
                for c, ef, _why in links:
                    cause_map.setdefault(ef, []).append(c)
                for d in accumulated:
                    t = int(d.get("tick") or 0)
                    d["causes"] = cause_map.get(t, [])

                local_world = local_db.query(World).filter_by(id=world_id).first()
                if local_world:
                    local_world.manuscript_draft_events = list(accumulated)
                    local_db.commit()
                causal_count = len(links)
            else:
                causal_count = 0

            local_world = local_db.query(World).filter_by(id=world_id).first()
            if local_world:
                local_world.manuscript_draft_events = list(accumulated)
                local_db.commit()
            job.result = {
                "draft_event_count": len(accumulated),
                "causal_link_count": causal_count,
                "warnings": result.warnings,
                "chapter_indices": selected_indices,
            }
            job.status = "cancelled" if job.is_cancelled() else "completed"
        except Exception as e:
            log.exception("manuscript event extraction failed")
            job.error = f"{type(e).__name__}: {e}"
            job.status = "error"
        finally:
            import time as _t
            job.finished_at = _t.time()
            local_db.close()

    threading.Thread(target=runner, daemon=True).start()
    return {"job_id": job.id}


# ─── V2：commit + discard ───────────────────────────────────────

class ManuscriptCommitEvent(BaseModel):
    title: str
    description: str = ""
    tick: int
    chapter_index: int = 0
    participant_ids: list[str] = []
    location_id: str | None = None
    causes: list[int] = []


class ManuscriptCommitRequest(BaseModel):
    events: list[ManuscriptCommitEvent]
    clear_draft: bool = True


@router.post("/worlds/{world_id}/manuscript/commit_events")
def commit_manuscript_events(
    world_id: str, payload: ManuscriptCommitRequest, db: Session = Depends(get_db),
):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    branch_id = world.active_branch_id
    if not branch_id:
        raise HTTPException(400, "world has no active branch")

    accepted = list(payload.events or [])
    if not accepted:
        raise HTTPException(400, "no events to commit")

    accepted.sort(key=lambda e: (e.tick, e.chapter_index))
    base_tick = max(world.current_tick or 0, 0)
    written = 0
    max_tick = base_tick
    draft_tick_to_event_id: dict[int, str] = {}
    for i, ev in enumerate(accepted):
        title = (ev.title or "").strip()[:200]
        if not title:
            continue
        tick = base_tick + i + 1
        max_tick = max(max_tick, tick)
        event_id = _new_id("ev")
        draft_tick_to_event_id[int(ev.tick)] = event_id
        db.add(Event(
            id=event_id,
            branch_id=branch_id,
            tick=tick,
            title=title,
            description=(ev.description or "").strip()[:2000],
            location_id=ev.location_id,
            participants=list(ev.participant_ids or []),
            consequences=[],
            metadata_={"source": "manuscript", "chapter_index": ev.chapter_index},
            deleted=0,
        ))
        written += 1

    causal_written = 0
    seen_pairs: set[tuple[str, str]] = set()
    for ev in accepted:
        effect_id = draft_tick_to_event_id.get(int(ev.tick))
        if not effect_id:
            continue
        for c in ev.causes or []:
            cause_id = draft_tick_to_event_id.get(int(c))
            if not cause_id or cause_id == effect_id:
                continue
            pair = (cause_id, effect_id)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            db.add(CausalLink(
                id=_new_id("cl"),
                branch_id=branch_id,
                cause_event_id=cause_id,
                effect_event_id=effect_id,
                description="",
                weight=1.0,
            ))
            causal_written += 1

    world.current_tick = max(world.current_tick or 0, max_tick)
    if (world.max_tick or 0) < max_tick:
        world.max_tick = max_tick
    if payload.clear_draft:
        world.manuscript_draft_events = []
    db.commit()
    return {
        "ok": True, "written": written,
        "causal_links_written": causal_written,
        "current_tick": world.current_tick,
    }


@router.delete("/worlds/{world_id}/manuscript/draft")
def discard_manuscript_draft(world_id: str, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    world.manuscript_draft_events = []
    db.commit()
    return {"ok": True}
