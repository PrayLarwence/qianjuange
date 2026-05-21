"""Agent pipeline 配置 + 编排执行 + trace 增量拉取 API。

端点：
- GET    /worlds/{id}/agent_pipeline           读世界配置（None 时返回全局 default + inherited=true）
- PUT    /worlds/{id}/agent_pipeline           写世界配置（body 为 PipelineConfig 形状；置 null 重置为继承）
- GET    /agent_pipeline/default               读全局 default
- PUT    /agent_pipeline/default               写全局 default
- GET    /agent_pipeline/limits                上限常量（前端校验用）
- POST   /worlds/{id}/step_orchestrated        异步 job：multi-agent 编排推演
- GET    /jobs/{id}/agent_traces?after_seq=N   增量拉本 job 已写入的 traces
"""
from __future__ import annotations
import logging
import threading
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..models import get_db, SessionLocal, World, AgentTrace
from ..engine.agent_pipeline import (
    PipelineConfig, load_global_default, save_global_default, resolve_for_world, LIMITS,
)
from ..engine.orchestrator import run_orchestrated_step, BudgetExhausted
from ..engine import create_job, get_job, capture_branch_snapshot, CancelledError

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/worlds/{world_id}/agent_pipeline")
def get_world_pipeline(world_id: str, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    if not world.agent_pipeline:
        cfg = load_global_default()
        return {"inherited": True, "config": cfg.model_dump()}
    cfg = resolve_for_world(world.agent_pipeline)
    return {"inherited": False, "config": cfg.model_dump()}


class PipelineUpdateRequest(BaseModel):
    config: Optional[dict] = None  # None = 重置为继承全局
    save_as_default: bool = False  # 同时保存为全局 default


@router.put("/worlds/{world_id}/agent_pipeline")
def update_world_pipeline(world_id: str, payload: PipelineUpdateRequest, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    if payload.config is None:
        world.agent_pipeline = None
        db.commit()
        cfg = load_global_default()
        return {"ok": True, "inherited": True, "config": cfg.model_dump()}
    try:
        cfg = PipelineConfig.model_validate(payload.config)
    except Exception as e:
        raise HTTPException(400, f"invalid config: {e}")
    world.agent_pipeline = cfg.model_dump()
    db.commit()
    if payload.save_as_default:
        try:
            save_global_default(cfg)
        except Exception as e:
            log.exception("save_as_default failed")
            return {"ok": True, "inherited": False, "config": cfg.model_dump(), "default_save_error": str(e)}
    return {"ok": True, "inherited": False, "config": cfg.model_dump()}


@router.get("/agent_pipeline/default")
def get_default_pipeline():
    cfg = load_global_default()
    return {"config": cfg.model_dump()}


class DefaultUpdateRequest(BaseModel):
    config: dict


@router.put("/agent_pipeline/default")
def update_default_pipeline(payload: DefaultUpdateRequest):
    try:
        cfg = PipelineConfig.model_validate(payload.config)
    except Exception as e:
        raise HTTPException(400, f"invalid config: {e}")
    save_global_default(cfg)
    return {"ok": True, "config": cfg.model_dump()}


@router.get("/agent_pipeline/limits")
def get_pipeline_limits():
    return LIMITS


class OrchestratedStepRequest(BaseModel):
    directive: Optional[str] = None
    config_override: Optional[dict] = None  # 临时覆盖（不写库），优先级 > world > global


@router.post("/worlds/{world_id}/step_orchestrated")
def step_orchestrated(world_id: str, payload: OrchestratedStepRequest, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    if world.max_tick and world.current_tick >= world.max_tick:
        raise HTTPException(400, f"已达推演上限 tick={world.max_tick}")

    if payload.config_override is not None:
        try:
            cfg = PipelineConfig.model_validate(payload.config_override)
        except Exception as e:
            raise HTTPException(400, f"invalid config_override: {e}")
    else:
        cfg = resolve_for_world(world.agent_pipeline)

    job = create_job(world_id, "step_orchestrated")
    job.status = "running"
    directive = payload.directive

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

            try:
                result = run_orchestrated_step(
                    local_db, local_world,
                    user_directive=directive,
                    job_id=job.id,
                    cfg=cfg,
                    cancel_check=job.is_cancelled,
                    on_progress=progress,
                )
                job.result = result
                job.narration = result.get("narration", "")
                job.status = "cancelled" if job.is_cancelled() else "completed"
            except BudgetExhausted as e:
                job.error = f"budget exhausted: {e.kind} (limit={e.limit}, used={e.used})"
                job.status = "error"
            except CancelledError:
                job.status = "cancelled"
        except Exception as e:
            log.exception("orchestrated step failed")
            job.error = f"{type(e).__name__}: {e}"
            job.status = "error"
        finally:
            import time as _t
            job.finished_at = _t.time()
            local_db.close()

    threading.Thread(target=runner, daemon=True).start()
    return {"job_id": job.id}


@router.get("/jobs/{job_id}/agent_traces")
def get_agent_traces(job_id: str, after_seq: int = 0, db: Session = Depends(get_db)):
    """增量拉取本 job 的 agent traces。前端按 1.5s 轮询，after_seq=最后看到的 seq。"""
    rows = (
        db.query(AgentTrace)
        .filter(AgentTrace.job_id == job_id, AgentTrace.seq > after_seq)
        .order_by(AgentTrace.seq.asc())
        .all()
    )
    return {
        "traces": [
            {
                "id": r.id,
                "seq": r.seq,
                "role": r.role,
                "agent_name": r.agent_name,
                "iteration": r.iteration,
                "model": r.model,
                "status": r.status,
                "verdict": r.verdict,
                "input_summary": r.input_summary,
                "output_summary": r.output_summary,
                "extra": r.extra,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "ended_at": r.ended_at.isoformat() if r.ended_at else None,
            }
            for r in rows
        ],
    }


@router.get("/jobs/{job_id}/agent_traces/{trace_id}/full")
def get_agent_trace_full(job_id: str, trace_id: str, db: Session = Depends(get_db)):
    """单独拉某条 trace 的完整 prompt + response（前端按需展开时调用）。"""
    row = db.query(AgentTrace).filter_by(id=trace_id, job_id=job_id).first()
    if not row:
        raise HTTPException(404, "trace not found")
    return {
        "id": row.id,
        "full_prompt": row.full_prompt,
        "full_response": row.full_response,
    }


@router.get("/worlds/{world_id}/pipeline_metrics")
def get_pipeline_metrics(world_id: str, hours: int = 168, db: Session = Depends(get_db)):
    """聚合该世界过去 N 小时（默认 7 天）的 orchestrated step 指标。

    用于 DashboardView 的 Pipeline 卡片：critic 通过率、forced_accept 比例、各 critic 表现。
    """
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    from ..engine.agents.orchestrator import query_pipeline_metrics
    return query_pipeline_metrics(db, world_id, hours=hours)
