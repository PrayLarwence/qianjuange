"""C3/C4: 故事板辅助路由。

包含：
- POST /worlds/{id}/storyboard/transitions/evaluate (C3)
- GET  /worlds/{id}/threads/aging (C4)

E1: 从 routes.py 中抽离的子路由模块。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..models import get_db, World


router = APIRouter()


class TransitionEvalRequest(BaseModel):
    from_index: int
    to_index: int
    branch_id: Optional[str] = None
    provider_key: Optional[str] = None


@router.post("/worlds/{world_id}/storyboard/transitions/evaluate")
def evaluate_storyboard_transition(
    world_id: str, payload: TransitionEvalRequest, db: Session = Depends(get_db),
):
    from ..engine.transitions import evaluate_transition
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    try:
        return evaluate_transition(
            db, world,
            from_index=payload.from_index,
            to_index=payload.to_index,
            branch_id=payload.branch_id,
            provider_key=payload.provider_key,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"evaluate failed: {e}")


@router.get("/worlds/{world_id}/threads/aging")
def get_thread_aging(
    world_id: str,
    branch_id: Optional[str] = None,
    stale_after: int = 10,
    warn_after: int = 5,
    db: Session = Depends(get_db),
):
    from ..engine.thread_aging import aging_threads
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    return aging_threads(
        db, world, branch_id=branch_id,
        stale_after=max(1, stale_after),
        warn_after=max(0, min(warn_after, max(1, stale_after))),
    )
