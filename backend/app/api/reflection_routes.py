from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..models import get_db, World, ReflectionMemory


router = APIRouter()

_VALID_AGENT_TYPES = {"director", "author", "critic"}


class ReflectionCreateRequest(BaseModel):
    agent_type: str
    title: str
    content: str = ""
    enabled: bool = True
    source_tick: int | None = None
    source_event: str | None = None


class ReflectionPatchRequest(BaseModel):
    agent_type: str | None = None
    title: str | None = None
    content: str | None = None
    enabled: bool | None = None
    source_tick: int | None = None
    source_event: str | None = None


def _serialize(r: ReflectionMemory) -> dict:
    return {
        "id": r.id,
        "world_id": r.world_id,
        "agent_type": r.agent_type,
        "title": r.title,
        "content": r.content or "",
        "enabled": bool(r.enabled),
        "source_tick": r.source_tick,
        "source_event": r.source_event,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


@router.get("/worlds/{world_id}/reflections")
def list_reflections(
    world_id: str,
    agent_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    q = db.query(ReflectionMemory).filter_by(world_id=world_id)
    if agent_type and agent_type in _VALID_AGENT_TYPES:
        q = q.filter_by(agent_type=agent_type)
    rows = q.order_by(ReflectionMemory.created_at.desc()).all()
    return {"reflections": [_serialize(r) for r in rows]}


@router.post("/worlds/{world_id}/reflections")
def create_reflection(world_id: str, payload: ReflectionCreateRequest, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    if payload.agent_type not in _VALID_AGENT_TYPES:
        raise HTTPException(400, f"agent_type must be one of {_VALID_AGENT_TYPES}")
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(400, "title required")
    row = ReflectionMemory(
        id=f"refl_{uuid.uuid4().hex[:10]}",
        world_id=world_id,
        agent_type=payload.agent_type,
        title=title[:200],
        content=(payload.content or "")[:4000],
        enabled=1 if payload.enabled else 0,
        source_tick=payload.source_tick,
        source_event=payload.source_event,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize(row)


@router.patch("/reflections/{reflection_id}")
def patch_reflection(reflection_id: str, payload: ReflectionPatchRequest, db: Session = Depends(get_db)):
    row = db.query(ReflectionMemory).filter_by(id=reflection_id).first()
    if not row:
        raise HTTPException(404, "reflection not found")
    if payload.agent_type is not None:
        if payload.agent_type not in _VALID_AGENT_TYPES:
            raise HTTPException(400, f"agent_type must be one of {_VALID_AGENT_TYPES}")
        row.agent_type = payload.agent_type
    if payload.title is not None:
        t = payload.title.strip()
        if not t:
            raise HTTPException(400, "title required")
        row.title = t[:200]
    if payload.content is not None:
        row.content = payload.content[:4000]
    if payload.enabled is not None:
        row.enabled = 1 if payload.enabled else 0
    if payload.source_tick is not None:
        row.source_tick = payload.source_tick
    if payload.source_event is not None:
        row.source_event = payload.source_event
    db.commit()
    return {"ok": True}


@router.delete("/reflections/{reflection_id}")
def delete_reflection(reflection_id: str, db: Session = Depends(get_db)):
    row = db.query(ReflectionMemory).filter_by(id=reflection_id).first()
    if not row:
        raise HTTPException(404, "reflection not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


# ---------- 预置种子 ----------

_SEEDS: list[dict] = [
    # Director
    {
        "agent_type": "director",
        "title": "人物必须有内反应",
        "content": "事件A到事件B之间，角色必须判断/期待/忍耐/误读。不能只有动作序列，要有态度。",
    },
    {
        "agent_type": "director",
        "title": "感官描写要有压强",
        "content": "不要描述感觉的属性（极轻的呼吸声），要描述什么在制造这个感觉（气流倒灌/庞然大物贴在巷底沉睡）。读者要感受到规模和逼近感。",
    },
    {
        "agent_type": "director",
        "title": "动词要带态度",
        "content": "用'剜'不用'看'，用'倒灌'不用'传来'。动词本身就是人物对世界的判断。",
    },
    {
        "agent_type": "director",
        "title": "一句话同时建构两个角色",
        "content": "例：'现在转头去问，他敢肯定霞什么也不会说'——一句话同时展示了他的判断力和霞的性格。追求这种信息密度。",
    },
    {
        "agent_type": "director",
        "title": "新角色不要强行关联",
        "content": "新引入的角色让他在自己的叙事线上自然发展，不要第一时间就和主角产生直接联系。",
    },
    # Author
    {
        "agent_type": "author",
        "title": "对白需要节奏填充",
        "content": "不能问→答。要：期待→交付→反应。中间可以夹无意义的动作、犹豫、重复。",
    },
    {
        "agent_type": "author",
        "title": "信息通过身体感知传递",
        "content": "用'潮湿的目光汇聚在后颈'代替'她在看他后颈的疤'。让读者通过角色的身体感受信息，而不是叙述者解释。",
    },
    {
        "agent_type": "author",
        "title": "禁止连续短句碎片化",
        "content": "AI 喜欢把一个完整动作拆成3-5个短句制造'节奏感'。这是假节奏。一个动词能说清的事不要用三个句子。",
    },
    {
        "agent_type": "author",
        "title": "修辞密度要不均匀",
        "content": "连续3-5个白描短句之后来一个有质感的句子。大部分句子应该朴素。不要每句都有修辞。",
    },
    # Critic
    {
        "agent_type": "critic",
        "title": "检查AI腔指纹",
        "content": "重点关注：'不是X。是Y。'句式、'那一瞬间'、'隐隐'、'像有什么东西在……'、'也是……也是……'、'感觉整个X都被Y了'。出现即扣分。",
    },
    {
        "agent_type": "critic",
        "title": "检查内反应缺失",
        "content": "如果事件之间角色只有动作没有判断/情绪/误读，说明缺少内反应层。这是最常见的AI叙事缺陷。",
    },
    {
        "agent_type": "critic",
        "title": "检查段落结构公式化",
        "content": "如果每段都是'叙述→对白→反应'或'起因→经过→总结'的重复结构，判定为不通过。段落形态必须有变化。",
    },
]


@router.post("/worlds/{world_id}/reflections/seed")
def seed_reflections(world_id: str, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    existing = db.query(ReflectionMemory).filter_by(world_id=world_id).count()
    if existing > 0:
        return {"seeded": 0, "message": "already has reflections"}
    created = 0
    for s in _SEEDS:
        row = ReflectionMemory(
            id=f"refl_{uuid.uuid4().hex[:10]}",
            world_id=world_id,
            agent_type=s["agent_type"],
            title=s["title"],
            content=s["content"],
            enabled=1,
        )
        db.add(row)
        created += 1
    db.commit()
    return {"seeded": created}


# ---------- 全局反思记忆 ----------

@router.get("/reflections/global")
def list_global_reflections(
    agent_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(ReflectionMemory).filter(ReflectionMemory.world_id.is_(None))
    if agent_type and agent_type in _VALID_AGENT_TYPES:
        q = q.filter_by(agent_type=agent_type)
    rows = q.order_by(ReflectionMemory.created_at.desc()).all()
    return {"reflections": [_serialize(r) for r in rows]}


@router.post("/reflections/global")
def create_global_reflection(payload: ReflectionCreateRequest, db: Session = Depends(get_db)):
    if payload.agent_type not in _VALID_AGENT_TYPES:
        raise HTTPException(400, f"agent_type must be one of {_VALID_AGENT_TYPES}")
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(400, "title required")
    row = ReflectionMemory(
        id=f"refl_{uuid.uuid4().hex[:10]}",
        world_id=None,
        agent_type=payload.agent_type,
        title=title[:200],
        content=(payload.content or "")[:4000],
        enabled=1 if payload.enabled else 0,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize(row)


@router.post("/reflections/global/seed")
def seed_global_reflections(db: Session = Depends(get_db)):
    existing = db.query(ReflectionMemory).filter(ReflectionMemory.world_id.is_(None)).count()
    if existing > 0:
        return {"seeded": 0, "message": "already has global reflections"}
    created = 0
    for s in _SEEDS:
        row = ReflectionMemory(
            id=f"refl_{uuid.uuid4().hex[:10]}",
            world_id=None,
            agent_type=s["agent_type"],
            title=s["title"],
            content=s["content"],
            enabled=1,
        )
        db.add(row)
        created += 1
    db.commit()
    return {"seeded": created}

