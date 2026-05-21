"""WorldLore CRUD + 缺口扫描 路由。

E1: 从 routes.py 中抽离的子路由模块。
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..models import get_db, World, WorldLore


router = APIRouter()


class LoreCreateRequest(BaseModel):
    title: str
    content: str = ""
    category: str = "setting"
    priority: int = 0
    pinned: bool = False


class LorePatchRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    category: str | None = None
    priority: int | None = None
    pinned: bool | None = None


class LoreScanGapsRequest(BaseModel):
    branch_id: Optional[str] = None
    provider_key: Optional[str] = None
    max_gaps: int = 8


def _serialize_lore(r: WorldLore) -> dict:
    return {
        "id": r.id, "world_id": r.world_id,
        "category": r.category, "title": r.title, "content": r.content or "",
        "priority": r.priority or 0, "pinned": bool(r.pinned),
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


@router.get("/worlds/{world_id}/lore")
def list_world_lore(world_id: str, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    rows = (
        db.query(WorldLore).filter_by(world_id=world_id)
        .order_by(WorldLore.pinned.desc(), WorldLore.priority.desc(), WorldLore.created_at.asc())
        .all()
    )
    return {"lore": [_serialize_lore(r) for r in rows]}


@router.post("/worlds/{world_id}/lore")
def create_world_lore(world_id: str, payload: LoreCreateRequest, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(400, "title required")
    row = WorldLore(
        id=f"lore_{uuid.uuid4().hex[:10]}",
        world_id=world_id,
        category=(payload.category or "setting").strip() or "setting",
        title=title[:200],
        content=(payload.content or "")[:8000],
        priority=int(payload.priority or 0),
        pinned=1 if payload.pinned else 0,
    )
    db.add(row); db.commit()
    return _serialize_lore(row)


@router.patch("/lore/{lore_id}")
def patch_world_lore(lore_id: str, payload: LorePatchRequest, db: Session = Depends(get_db)):
    row = db.query(WorldLore).filter_by(id=lore_id).first()
    if not row:
        raise HTTPException(404, "lore not found")
    if payload.title is not None:
        t = payload.title.strip()
        if not t:
            raise HTTPException(400, "title cannot be empty")
        row.title = t[:200]
    if payload.content is not None:
        row.content = payload.content[:8000]
    if payload.category is not None:
        row.category = payload.category.strip() or "setting"
    if payload.priority is not None:
        row.priority = int(payload.priority)
    if payload.pinned is not None:
        row.pinned = 1 if payload.pinned else 0
    db.commit()
    return _serialize_lore(row)


@router.delete("/lore/{lore_id}")
def delete_world_lore(lore_id: str, db: Session = Depends(get_db)):
    row = db.query(WorldLore).filter_by(id=lore_id).first()
    if not row:
        raise HTTPException(404, "lore not found")
    db.delete(row); db.commit()
    return {"ok": True}


@router.post("/worlds/{world_id}/lore/scan_gaps")
def scan_world_lore_gaps(world_id: str, payload: LoreScanGapsRequest, db: Session = Depends(get_db)):
    from ..engine.lore_gaps import scan_lore_gaps
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    try:
        result = scan_lore_gaps(
            db, world,
            branch_id=payload.branch_id,
            provider_key=payload.provider_key,
            max_gaps=payload.max_gaps,
        )
    except Exception as e:
        raise HTTPException(500, f"scan failed: {e}")
    return result
