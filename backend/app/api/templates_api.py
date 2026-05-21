"""模板 / outline / 系列相关 API。

13 端点：
- GET    /templates
- GET    /templates/{id}
- POST   /templates
- PUT    /templates/{id}
- DELETE /templates/{id}
- POST   /templates/seed_official
- POST   /templates/{id}/instantiate
- POST   /worlds/{id}/save_as_template
- GET    /worlds/{id}/outline
- POST   /worlds/{id}/outline_progress
- POST   /worlds/{id}/max_tick
- POST   /worlds/{id}/upgrade_to_template
- GET    /series/{series}
"""
from __future__ import annotations
import logging
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..models import (
    get_db, World, Branch, Entity, Event, NarrativeLog, ChapterMarker, WorldTemplate,
)
from ._common import _new_id

log = logging.getLogger(__name__)
router = APIRouter()


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


@router.post("/templates/seed_official")
def seed_official(force: bool = False, db: Session = Depends(get_db)):
    from ..seeds import seed_official_templates
    return seed_official_templates(db, force=force)


# 注：双角色对话演练已抽至 app/api/dialogue_routes.py

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
