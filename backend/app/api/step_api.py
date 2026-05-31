"""推演 (step) 与异步 job 控制 API。

5 端点：
- POST /worlds/{id}/step
- POST /worlds/{id}/step_multi_agent
- POST /worlds/{id}/step_async
- GET  /jobs/{id}
- POST /jobs/{id}/cancel
"""
from __future__ import annotations
import logging
import threading
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..models import get_db, SessionLocal, World
from ..engine import (
    run_step, run_auto, create_job, get_job, cancel_job,
    CancelledError, capture_branch_snapshot,
)
from ..providers import get_provider

log = logging.getLogger(__name__)
router = APIRouter()


class StepRequest(BaseModel):
    directive: str | None = None
    provider: str | None = None
    steps: int = 1
    force_legacy: bool = False  # 显式要求跳过 orchestrator



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
    force_legacy = payload.force_legacy

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

            # Auto-upgrade to orchestrator if pipeline config exists
            use_orchestrator = False
            cfg = None
            if not force_legacy:
                try:
                    from ..engine.agents.agent_pipeline import resolve_for_world
                    cfg = resolve_for_world(local_world.agent_pipeline)
                    use_orchestrator = True
                except Exception:
                    pass

            if use_orchestrator and cfg:
                from ..engine.orchestrator import run_orchestrated_step
                from ..engine.orchestrator import BudgetExhausted

                def progress(info):
                    phase = info.get("phase", "")
                    if phase == "orchestrator_start":
                        job.progress_message = "编排开始"
                    elif phase == "step_start":
                        job.progress_message = "Director 开始推演"
                    elif phase == "thinking":
                        job.progress_message = f"Director 思考中（hop {info.get('hop', 0)+1}）"
                    elif phase == "executing":
                        job.progress_message = "Director 执行工具"
                    elif phase == "step_done":
                        job.progress_message = "Director 完成，进入 Author 阶段"
                    elif phase == "orchestrator_done":
                        job.progress_message = f"完成：{info.get('verdict')}（{info.get('rounds')} 轮 critic）"
                    if "tool_calls" in info:
                        job.tool_calls = list(info["tool_calls"])
                    if "narration" in info:
                        job.narration = info["narration"]

                results = []
                try:
                    for i in range(steps):
                        if job.is_cancelled():
                            break
                        result = run_orchestrated_step(
                            local_db, local_world,
                            user_directive=directive,
                            job_id=job.id,
                            cfg=cfg,
                            cancel_check=job.is_cancelled,
                            on_progress=progress,
                            provider=provider,
                        )
                        results.append(result)
                    job.result = {"results": results, "tick": local_world.current_tick}
                    job.status = "cancelled" if job.is_cancelled() else "completed"
                except BudgetExhausted as e:
                    job.error = f"budget exhausted: {e.kind} (limit={e.limit}, used={e.used})"
                    job.status = "error"
            else:
                # Legacy path
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

