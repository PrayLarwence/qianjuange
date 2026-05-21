"""小说化（novelize）相关 API。

3 端点：
- GET  /worlds/{id}/novelize/chapters
- POST /worlds/{id}/novelize
- POST /worlds/{id}/novelize_async
"""
from __future__ import annotations
import logging
import threading
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..models import get_db, SessionLocal, World
from ..engine import create_job
from ..providers import get_provider

log = logging.getLogger(__name__)
router = APIRouter()


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
