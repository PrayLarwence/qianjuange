"""实体 / 角色 / 关系图谱相关 API。

10 个端点：
- POST /entities/{id}/chat
- GET  /entities/{id}/arc
- POST /entities/{id}/emotion_curve
- POST /entities/{id}/extract_persona
- POST /worlds/{id}/entities
- PATCH /entities/{id}
- GET  /worlds/{id}/characters/{cid}/view
- GET  /worlds/{id}/relationships
- POST /worlds/{id}/relationships/infer
- POST /worlds/{id}/relationships/set
"""
from __future__ import annotations
import json
import logging
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..models import (
    get_db, World, Branch, Entity, Event, CausalLink, NarrativeLog, PlotThread,
    ConsistencyIssue,
)
from ..engine.tools import render_world_rules
from ..providers import get_provider, Message
from ._common import _new_id

log = logging.getLogger(__name__)
router = APIRouter()


class ChatTurn(BaseModel):
    role: str
    content: str


class CharacterChatRequest(BaseModel):
    message: str
    history: list[ChatTurn] = Field(default_factory=list)
    view_tick: int | None = None
    provider: str | None = None


@router.post("/entities/{entity_id}/chat")
def character_chat(entity_id: str, payload: CharacterChatRequest, db: Session = Depends(get_db)):
    entity = db.query(Entity).filter_by(id=entity_id).first()
    if not entity:
        raise HTTPException(404, "entity not found")
    if entity.type != "character":
        raise HTTPException(400, "only characters can be chatted with")

    branch = db.query(Branch).filter_by(id=entity.branch_id).first()
    world = db.query(World).filter_by(id=branch.world_id).first() if branch else None
    if not world:
        raise HTTPException(404, "world not found")

    view_tick = payload.view_tick if payload.view_tick is not None else world.current_tick

    all_events = db.query(Event).filter_by(branch_id=entity.branch_id).filter(Event.deleted == 0).all()
    visible_events = sorted(
        [e for e in all_events if e.tick <= view_tick and entity.id in (e.participants or [])],
        key=lambda e: e.tick,
    )
    recent = visible_events[-8:]

    co_ids: set[str] = set()
    for ev in visible_events:
        for pid in (ev.participants or []):
            if pid != entity.id:
                co_ids.add(pid)
    co_entities = db.query(Entity).filter(Entity.id.in_(list(co_ids))).all() if co_ids else []

    location = None
    loc_id = (entity.state or {}).get("location_id") or entity.location_id
    if loc_id:
        location = db.query(Entity).filter_by(id=loc_id).first()

    attrs = entity.attributes or {}
    state = entity.state or {}
    public_state = {k: v for k, v in state.items() if k != "location_id"}

    def fmt_kv(d: dict) -> str:
        if not d:
            return "（无）"
        return "\n".join(f"  - {k}: {v}" for k, v in d.items())

    events_text = "\n".join(
        f"  - 第 {ev.tick} 时刻 · 《{ev.title}》：{ev.description}"
        for ev in recent
    ) or "  （这个时点之前你还没有可叙述的经历）"

    coactors_text = "\n".join(
        f"  - {ce.name}（{ce.type}）：{ce.summary or '无简介'}"
        for ce in co_entities
    ) or "  （还未与他人有交集）"

    sys_prompt = f"""你正在扮演一个虚构世界中的角色。你必须始终以这个角色的第一人称、口吻、知识范围回答用户。

# 你的身份
- 名字：{entity.name}
- 简介：{entity.summary or '（未设定）'}
- 你所在的世界：{world.name} — {world.description or ''}

# 你的属性（这些塑造了你）
{fmt_kv(attrs)}

# 你当前的状态
{fmt_kv(public_state) if public_state else '  （平稳）'}
- 你目前在：{location.name if location else '未知'}{('（' + (location.summary or '') + '）') if location and location.summary else ''}
- 当前时刻：第 {view_tick} 时
- 世界主时钟：第 {world.current_tick} 时{('（你正在以更早视角回忆，回答时只能基于第 ' + str(view_tick) + ' 时之前的认知）') if view_tick < world.current_tick else ''}

# 你经历过的事（按时间顺序，最近 {len(recent)} 件）
{events_text}

# 你认识/同台过的人
{coactors_text}

# 行为准则（极其重要）
1. 必须始终用第一人称（"我"）说话，从不跳出角色
2. 你只知道第 {view_tick} 时之前的事；如果用户问之后的事，回答"我不知道"或合理推测
3. 你的语气、用词、关注点必须符合上面的属性设定
4. 不要编造与已知事件矛盾的经历
5. 用户可能问你过去/动机/感受/对他人看法/对未来打算 — 都基于你的属性和经历回答
6. 不要解释你是 AI、不要谈论"叙事系统"或"沙盒"等元概念
7. 回答控制在 80-200 字，自然口语化，避免书面化的"首先、其次、综上"
8. 用与世界设定匹配的语言风格回答
"""

    rules_block = render_world_rules(world.rules)
    if rules_block:
        sys_prompt += "\n\n# 这个世界的规则（你必须遵守）\n" + rules_block
    from ..engine.tools import build_world_lore_block
    lore_block = build_world_lore_block(db, world)
    if lore_block:
        sys_prompt += "\n\n" + lore_block

    history_msgs: list[Message] = []
    for turn in payload.history[-20:]:
        role = "user" if turn.role == "user" else "assistant"
        history_msgs.append(Message(role=role, content=turn.content))
    history_msgs.append(Message(role="user", content=payload.message))

    provider = get_provider(payload.provider) if payload.provider else get_provider()
    try:
        resp = provider.chat(
            system=sys_prompt,
            messages=history_msgs,
            tools=[],
            max_tokens=600,
            temperature=0.85,
        )
    except Exception as e:
        log.exception("character chat failed")
        raise HTTPException(500, f"chat failed: {e}")

    return {
        "reply": resp.text or "（沉默）",
        "view_tick": view_tick,
        "world_tick": world.current_tick,
        "context": {
            "events_visible": len(visible_events),
            "events_used": len(recent),
            "coactors": len(co_entities),
        },
    }

@router.get("/worlds/{world_id}/relationships")
def world_relationships(world_id: str, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    branch_id = world.active_branch_id
    entities = db.query(Entity).filter_by(branch_id=branch_id).all()
    events = db.query(Event).filter_by(branch_id=branch_id, deleted=0).order_by(Event.tick).all()
    by_id = {e.id: e for e in entities}

    edges_map: dict[tuple[str, str], dict] = {}
    for ev in events:
        parts = [p for p in (ev.participants or []) if p in by_id]
        if len(parts) < 2:
            continue
        unique = sorted(set(parts))
        for i in range(len(unique)):
            for j in range(i + 1, len(unique)):
                key = (unique[i], unique[j])
                d = edges_map.setdefault(key, {"weight": 0, "events": []})
                d["weight"] += 1
                if len(d["events"]) < 6:
                    d["events"].append({"id": ev.id, "tick": ev.tick, "title": ev.title})

    cached = {}
    for e in entities:
        if e.type != "character":
            continue
        rels = (e.attributes or {}).get("_relations") or {}
        if isinstance(rels, dict):
            for other_id, label in rels.items():
                key = tuple(sorted([e.id, other_id]))
                cached[key] = label

    edges = []
    for (a, b), d in edges_map.items():
        label = cached.get((a, b)) or ""
        edges.append({
            "id": f"rel_{a}_{b}",
            "source": a, "target": b,
            "weight": d["weight"],
            "label": label,
            "events": d["events"],
        })

    nodes = [{
        "id": e.id, "name": e.name, "type": e.type,
        "alive": e.alive, "summary": e.summary or "",
        "location_id": e.location_id,
    } for e in entities]

    return {"nodes": nodes, "edges": edges}


class InferRelationshipsRequest(BaseModel):
    provider: str | None = None


@router.post("/worlds/{world_id}/relationships/infer")
def infer_relationships(world_id: str, payload: InferRelationshipsRequest, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    branch_id = world.active_branch_id
    entities = db.query(Entity).filter_by(branch_id=branch_id, type="character").all()
    if len(entities) < 2:
        return {"updated": 0, "pairs": []}

    by_id = {e.id: e for e in entities}
    events = db.query(Event).filter_by(branch_id=branch_id, deleted=0).order_by(Event.tick).all()

    pair_events: dict[tuple[str, str], list] = {}
    for ev in events:
        parts = [p for p in (ev.participants or []) if p in by_id]
        if len(parts) < 2:
            continue
        unique = sorted(set(parts))
        for i in range(len(unique)):
            for j in range(i + 1, len(unique)):
                pair_events.setdefault((unique[i], unique[j]), []).append(ev)

    if not pair_events:
        return {"updated": 0, "pairs": []}

    pair_lines = []
    for (a, b), evs in pair_events.items():
        a_name = by_id[a].name
        b_name = by_id[b].name
        snippet = "；".join(f"t{e.tick} {e.title}" for e in evs[-5:])
        pair_lines.append(f"- {a}|{b}|{a_name}↔{b_name}：{snippet}")

    sys_prompt = f"""你是叙事分析师。基于角色之间的共同事件，给出他们当前的关系标签。

世界：{world.name}
{render_world_rules(world.rules)}

角色清单：
{chr(10).join(f'- {e.id}: {e.name}（{(e.summary or "")[:50]}）' for e in entities)}

每对角色及他们共同参与的事件：
{chr(10).join(pair_lines)}

为每对给出简短关系标签（2-6 字，例：青梅竹马 / 死敌 / 上下级 / 暗恋 / 父女 / 战友→反目）。
若关系暧昧或多重，用斜杠：恋人/同事。

严格输出 JSON：
{{
  "relations": [
    {{"a": "ent_xxx", "b": "ent_yyy", "label": "..."}},
    ...
  ]
}}
"""
    provider = get_provider(payload.provider) if payload.provider else get_provider()
    try:
        resp = provider.chat(
            system=sys_prompt,
            messages=[Message(role="user", content="请给出 JSON 标签。")],
            tools=[],
            max_tokens=1500,
            temperature=0.4,
        )
    except Exception as e:
        log.exception("infer relationships failed")
        raise HTTPException(500, f"infer failed: {e}")

    raw = resp.text or ""
    parsed: dict[str, Any] = {}
    try:
        s = raw.find("{"); e = raw.rfind("}")
        if s >= 0 and e > s:
            parsed = json.loads(raw[s:e+1])
    except Exception:
        log.warning("infer JSON parse failed: %s", raw[:200])

    rels = parsed.get("relations") or []
    updated = 0
    for r in rels:
        if not isinstance(r, dict):
            continue
        a = r.get("a"); b = r.get("b"); label = (r.get("label") or "").strip()
        if not (a in by_id and b in by_id and label):
            continue
        for ent_id, other in [(a, b), (b, a)]:
            ent = by_id[ent_id]
            attrs = dict(ent.attributes or {})
            relmap = dict(attrs.get("_relations") or {})
            relmap[other] = label
            attrs["_relations"] = relmap
            ent.attributes = attrs
        updated += 1
    db.commit()
    return {"updated": updated, "raw_ok": bool(parsed)}


class SetRelationRequest(BaseModel):
    a_id: str
    b_id: str
    label: str = ""


@router.post("/worlds/{world_id}/relationships/set")
def set_relationship(world_id: str, payload: SetRelationRequest, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    branch_id = world.active_branch_id
    a = db.query(Entity).filter_by(id=payload.a_id, branch_id=branch_id).first()
    b = db.query(Entity).filter_by(id=payload.b_id, branch_id=branch_id).first()
    if not (a and b):
        raise HTTPException(404, "entity not found")
    label = (payload.label or "").strip()
    for ent, other_id in [(a, b.id), (b, a.id)]:
        attrs = dict(ent.attributes or {})
        relmap = dict(attrs.get("_relations") or {})
        if label:
            relmap[other_id] = label
        else:
            relmap.pop(other_id, None)
        attrs["_relations"] = relmap
        ent.attributes = attrs
    db.commit()
    return {"ok": True, "a_id": a.id, "b_id": b.id, "label": label}

@router.get("/entities/{entity_id}/arc")
def entity_arc(entity_id: str, db: Session = Depends(get_db)):
    ent = db.query(Entity).filter_by(id=entity_id).first()
    if not ent:
        raise HTTPException(404, "entity not found")
    branch_id = ent.branch_id

    events = (
        db.query(Event).filter_by(branch_id=branch_id, deleted=0)
        .order_by(Event.tick).all()
    )
    relevant = [ev for ev in events if entity_id in (ev.participants or [])]
    relevant_ids = {ev.id for ev in relevant}

    nar = (
        db.query(NarrativeLog).filter_by(branch_id=branch_id)
        .order_by(NarrativeLog.tick).all()
    )
    nar_by_tick: dict[int, list[str]] = {}
    for n in nar:
        nar_by_tick.setdefault(n.tick, []).append(n.text)

    by_id = {e.id: e for e in db.query(Entity).filter_by(branch_id=branch_id).all()}
    ev_by_id = {ev.id: ev for ev in events}

    # B2: 因果链——只取本角色相关事件作为 cause 或 effect 的链
    links = (
        db.query(CausalLink)
        .filter(CausalLink.branch_id == branch_id)
        .filter((CausalLink.cause_event_id.in_(relevant_ids)) |
                (CausalLink.effect_event_id.in_(relevant_ids)))
        .all()
    ) if relevant_ids else []
    incoming: dict[str, list[dict]] = {}  # effect_event_id -> [{cause_id, cause_title, cause_tick, weight}]
    outgoing: dict[str, list[dict]] = {}  # cause_event_id  -> [{effect_id, effect_title, effect_tick, weight}]
    for lk in links:
        ce = ev_by_id.get(lk.cause_event_id)
        ef = ev_by_id.get(lk.effect_event_id)
        if not ce or not ef:
            continue
        if lk.effect_event_id in relevant_ids:
            incoming.setdefault(lk.effect_event_id, []).append({
                "event_id": ce.id, "title": ce.title, "tick": ce.tick,
                "weight": lk.weight or 1.0,
            })
        if lk.cause_event_id in relevant_ids:
            outgoing.setdefault(lk.cause_event_id, []).append({
                "event_id": ef.id, "title": ef.title, "tick": ef.tick,
                "weight": lk.weight or 1.0,
            })

    arc = []
    for ev in relevant:
        co_parts = [by_id[p].name for p in (ev.participants or []) if p != entity_id and p in by_id]
        loc = by_id.get(ev.location_id).name if ev.location_id and ev.location_id in by_id else ""
        narration_snippets = []
        for txt in nar_by_tick.get(ev.tick, []):
            if ent.name and ent.name in txt:
                snip = txt[:240] + ("…" if len(txt) > 240 else "")
                narration_snippets.append(snip)
        arc.append({
            "event_id": ev.id, "tick": ev.tick, "title": ev.title,
            "description": ev.description, "location": loc,
            "co_participants": co_parts,
            "narration": narration_snippets,
            "metadata": ev.metadata_ or {},
            "incoming_links": incoming.get(ev.id, []),
            "outgoing_links": outgoing.get(ev.id, []),
        })

    relations_now = (ent.attributes or {}).get("_relations") or {}
    rel_map = []
    if isinstance(relations_now, dict):
        for other_id, label in relations_now.items():
            other = by_id.get(other_id)
            if other:
                rel_map.append({"other_id": other_id, "other_name": other.name, "label": label})

    # B2: 涉及本角色的 open ConsistencyIssue
    issues = (
        db.query(ConsistencyIssue)
        .filter_by(branch_id=branch_id, status="open")
        .order_by(ConsistencyIssue.tick_end.desc(), ConsistencyIssue.created_at.desc())
        .all()
    )
    open_issues = []
    for iss in issues:
        eids = iss.entity_ids or []
        if entity_id not in eids:
            continue
        open_issues.append({
            "id": iss.id,
            "category": iss.category, "severity": iss.severity,
            "title": iss.title, "description": iss.description,
            "suggestion": iss.suggestion or "",
            "tick_start": iss.tick_start, "tick_end": iss.tick_end,
        })

    # B5: 涉及本角色的未收尾伏笔
    threads = (
        db.query(PlotThread)
        .filter_by(branch_id=branch_id, status="open")
        .order_by(PlotThread.opened_tick.desc())
        .all()
    )
    open_threads = []
    for th in threads:
        if entity_id not in (th.related_entity_ids or []):
            continue
        open_threads.append({
            "id": th.id,
            "title": th.title, "summary": th.summary or "",
            "opened_tick": th.opened_tick,
        })

    ticks = [b["tick"] for b in arc]
    stats = {
        "first_tick": min(ticks) if ticks else None,
        "last_tick": max(ticks) if ticks else None,
        "event_count": len(arc),
        "open_issue_count": len(open_issues),
        "open_thread_count": len(open_threads),
        "causal_link_count": sum(len(v) for v in incoming.values()) + sum(len(v) for v in outgoing.values()),
    }

    return {
        "entity": {
            "id": ent.id, "name": ent.name, "type": ent.type,
            "summary": ent.summary or "", "alive": ent.alive,
            "attributes": ent.attributes or {}, "state": ent.state or {},
            "created_at_tick": ent.created_at_tick,
            "current_location": (by_id.get(ent.location_id).name if ent.location_id and ent.location_id in by_id else None),
        },
        "arc": arc,
        "current_relations": rel_map,
        "open_issues": open_issues,
        "open_threads": open_threads,
        "stats": stats,
        "total_events": len(relevant),
    }

class EmotionInferRequest(BaseModel):
    provider: str | None = None


@router.post("/entities/{entity_id}/emotion_curve")
def infer_emotion_curve(entity_id: str, payload: EmotionInferRequest, db: Session = Depends(get_db)):
    ent = db.query(Entity).filter_by(id=entity_id).first()
    if not ent or ent.type != "character":
        raise HTTPException(404, "character not found")
    branch_id = ent.branch_id
    events = (
        db.query(Event).filter_by(branch_id=branch_id, deleted=0)
        .order_by(Event.tick).all()
    )
    relevant = [ev for ev in events if entity_id in (ev.participants or [])]
    if not relevant:
        return {"curve": [], "reason": "no events"}

    nar = (
        db.query(NarrativeLog).filter_by(branch_id=branch_id)
        .order_by(NarrativeLog.tick).all()
    )
    nar_by_tick: dict[int, list[str]] = {}
    for n in nar:
        nar_by_tick.setdefault(n.tick, []).append(n.text)

    by_id = {e.id: e for e in db.query(Entity).filter_by(branch_id=branch_id).all()}
    beats_text = []
    for ev in relevant:
        co = "、".join(by_id[p].name for p in (ev.participants or []) if p != entity_id and p in by_id)
        snippets = []
        for txt in nar_by_tick.get(ev.tick, []):
            if ent.name and ent.name in txt:
                snippets.append(txt[:200])
        snip = "；".join(snippets) if snippets else ""
        beats_text.append(f"t{ev.tick}|《{ev.title}》|同台:{co}|{ev.description[:120]}" + (f"|叙事:{snip}" if snip else ""))

    sys_prompt = f"""你是叙事情感分析师。给定角色 **{ent.name}** 的所有重要节点，估计他/她在每个节点的情感状态。

角色简介：{ent.summary or '无'}

节点序列：
{chr(10).join(beats_text)}

# 你的任务
为**每个 tick** 给出：
- valence：情感正负向，-1.0（极痛苦/绝望）到 +1.0（极喜悦/满足），允许小数
- arousal：情感强度，0.0（麻木平静）到 1.0（剧烈激动）
- emotion：1-3 字的主导情绪标签（例：愤怒/喜悦/迷茫/坚毅/悲恸/羞愧/释然）
- note：8-20 字解读，说明这个情绪从何而来

严格输出 JSON：
{{
  "curve": [
    {{"tick": 0, "valence": -0.3, "arousal": 0.5, "emotion": "迷茫", "note": "刚到陌生地，不知所措"}},
    ...
  ]
}}
不要额外说明。
"""
    provider = get_provider(payload.provider) if payload.provider else get_provider()
    try:
        resp = provider.chat(
            system=sys_prompt,
            messages=[Message(role="user", content="开始分析。")],
            tools=[], max_tokens=1800, temperature=0.4,
        )
    except Exception as e:
        log.exception("emotion failed")
        raise HTTPException(500, f"emotion infer failed: {e}")

    raw = resp.text or ""
    parsed: dict[str, Any] = {}
    try:
        s = raw.find("{"); e = raw.rfind("}")
        if s >= 0 and e > s:
            parsed = json.loads(raw[s:e+1])
    except Exception:
        log.warning("emotion parse failed: %s", raw[:200])

    curve = []
    valid_ticks = {ev.tick for ev in relevant}
    for x in (parsed.get("curve") or []):
        if not isinstance(x, dict):
            continue
        try:
            t = int(x.get("tick", -1))
        except Exception:
            continue
        if t not in valid_ticks:
            continue
        try:
            v = max(-1.0, min(1.0, float(x.get("valence", 0))))
            a = max(0.0, min(1.0, float(x.get("arousal", 0))))
        except Exception:
            v, a = 0.0, 0.5
        curve.append({
            "tick": t, "valence": round(v, 2), "arousal": round(a, 2),
            "emotion": (x.get("emotion") or "")[:6],
            "note": (x.get("note") or "")[:60],
        })
    curve.sort(key=lambda x: x["tick"])

    attrs = dict(ent.attributes or {})
    attrs["_emotion_curve"] = curve
    ent.attributes = attrs
    db.commit()
    return {"curve": curve, "raw_ok": bool(parsed)}

class PersonaExtractRequest(BaseModel):
    branch_id: str | None = None
    provider: str | None = None


@router.post("/entities/{entity_id}/extract_persona")
def extract_persona_route(entity_id: str, payload: PersonaExtractRequest, db: Session = Depends(get_db)):
    """Reverse-engineer a character's persona from their event history.

    Returns a *suggestion* — does not write to DB. Frontend shows it side-by-side
    with the current persona and lets the user decide what to keep.
    """
    from ..engine.persona_extract import extract_persona
    ent = db.query(Entity).filter_by(id=entity_id).first()
    if not ent:
        raise HTTPException(404, "entity not found")
    if ent.type != "character":
        raise HTTPException(400, "only characters have persona")
    provider = get_provider(payload.provider) if payload.provider else None
    try:
        return extract_persona(db, entity_id,
                               branch_id=payload.branch_id, provider=provider)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        log.exception("persona extract failed")
        raise HTTPException(500, f"extract failed: {e}")


class EntityIn(BaseModel):
    type: str
    name: str
    summary: str = ""
    attributes: dict[str, Any] = Field(default_factory=dict)
    location_id: str | None = None
    persona: dict[str, Any] | None = None
    memories: list[dict[str, Any]] | None = None


@router.post("/worlds/{world_id}/entities")
def add_entity(world_id: str, payload: EntityIn, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    e = Entity(
        id=_new_id("ent"), branch_id=world.active_branch_id, type=payload.type, name=payload.name,
        summary=payload.summary, attributes=payload.attributes, state={}, location_id=payload.location_id,
        persona=payload.persona or {}, memories=payload.memories or [],
        created_at_tick=world.current_tick, alive=1,
    )
    db.add(e); db.commit()
    return {"id": e.id}


class EntityPatch(BaseModel):
    name: str | None = None
    summary: str | None = None
    attributes: dict[str, Any] | None = None
    state: dict[str, Any] | None = None
    persona: dict[str, Any] | None = None
    memories: list[dict[str, Any]] | None = None
    tags: list[str] | None = None
    pinned: int | None = None
    alive: int | None = None


@router.patch("/entities/{entity_id}")
def patch_entity(entity_id: str, payload: EntityPatch, db: Session = Depends(get_db)):
    e = db.query(Entity).filter_by(id=entity_id).first()
    if not e:
        raise HTTPException(404, "entity not found")
    if payload.name is not None: e.name = payload.name
    if payload.summary is not None: e.summary = payload.summary
    if payload.attributes is not None: e.attributes = payload.attributes
    if payload.state is not None: e.state = payload.state
    if payload.persona is not None: e.persona = payload.persona
    if payload.memories is not None: e.memories = payload.memories
    if payload.tags is not None:
        seen: set[str] = set()
        cleaned: list[str] = []
        for t in payload.tags:
            s = (t or "").strip()
            if not s or s in seen:
                continue
            if len(s) > 32:
                s = s[:32]
            seen.add(s)
            cleaned.append(s)
            if len(cleaned) >= 16:
                break
        e.tags = cleaned
    if payload.pinned is not None: e.pinned = 1 if int(payload.pinned) else 0
    if payload.alive is not None: e.alive = int(payload.alive)
    db.commit()
    return {"ok": True, "id": e.id}


@router.get("/worlds/{world_id}/characters/{character_id}/view")
def character_view(world_id: str, character_id: str, sight: int = 8, max_events: int = 25, db: Session = Depends(get_db)):
    """Return the world as `character_id` perceives it."""
    from ..engine.character_view import build_character_view, view_as_prompt
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    try:
        view = build_character_view(db, world, character_id, sight_radius=sight, max_events=max_events)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {**view, "prompt": view_as_prompt(view)}
