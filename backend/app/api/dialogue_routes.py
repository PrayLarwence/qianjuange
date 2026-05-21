"""P2: 双角色对话演练 路由。

E1: 从 routes.py 中抽离的子路由模块。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..models import get_db, World


router = APIRouter()


class DialogueRehearseRequest(BaseModel):
    actor_a_id: str
    actor_b_id: str
    scene: str = ""
    goal: str = ""
    turns: int = 12
    provider: Optional[str] = None


@router.post("/worlds/{world_id}/dialogue/rehearse")
def dialogue_rehearse(world_id: str, payload: DialogueRehearseRequest, db: Session = Depends(get_db)):
    from ..engine.dialogue_rehearsal import rehearse_dialogue
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    try:
        return rehearse_dialogue(
            db, world,
            actor_a_id=payload.actor_a_id,
            actor_b_id=payload.actor_b_id,
            scene=payload.scene, goal=payload.goal, turns=payload.turns,
            provider_key=payload.provider,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


class DialogueSaveRequest(BaseModel):
    actors: list[dict] = Field(default_factory=list)
    title: str = ""
    summary: str = ""
    turns: list[dict] = Field(default_factory=list)


@router.post("/worlds/{world_id}/dialogue/save")
def dialogue_save(world_id: str, payload: DialogueSaveRequest, db: Session = Depends(get_db)):
    from ..engine.dialogue_rehearsal import save_dialogue_as_narration
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    try:
        log_row = save_dialogue_as_narration(
            db, world,
            {"actors": payload.actors, "title": payload.title,
             "summary": payload.summary, "turns": payload.turns},
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"narration_id": log_row.id, "tick": log_row.tick}
