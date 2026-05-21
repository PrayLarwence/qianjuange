"""世界设置（PATCH /worlds/{id}）API。

1 端点：
- PATCH /worlds/{id}
"""
from __future__ import annotations
import logging
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..models import get_db, World, StyleProfile

log = logging.getLogger(__name__)
router = APIRouter()


class WorldUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    outline: str | None = None
    rules: dict[str, Any] | None = None
    # A4: 写作风格绑定。空字符串 / null 表示解绑（Author 不介入）。
    # 前端要解绑时传空字符串；不传字段表示不修改。
    style_profile_id: str | None = None


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
    # 语义：None=不修改；""=解绑；非空字符串=绑定到该 id（要校验存在）
    if payload.style_profile_id is not None:
        sid = payload.style_profile_id.strip()
        if sid:
            sp = db.query(StyleProfile).filter_by(id=sid).first()
            if not sp:
                raise HTTPException(400, f"style_profile not found: {sid}")
            world.style_profile_id = sid
        else:
            world.style_profile_id = None
    db.commit()
    return {
        "ok": True,
        "id": world.id, "name": world.name,
        "description": world.description, "outline": world.outline or "",
        "rules": world.rules or {},
        "style_profile_id": world.style_profile_id,
    }



