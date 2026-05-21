"""并行探索 / 变体评估 API。

2 端点：
- POST /worlds/{id}/explore
- POST /worlds/{id}/evaluate_variants
"""
from __future__ import annotations
import json
import logging
import threading
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..models import (
    get_db, SessionLocal, World, Branch, Entity, Event, CausalLink, NarrativeLog,
)
from ..engine import (
    run_auto, capture_branch_snapshot, create_job, CancelledError,
)
from ..engine.tools import render_world_rules
from ..providers import get_provider, Message
from ._common import _new_id

log = logging.getLogger(__name__)
router = APIRouter()


def _fork_branch(db: Session, world: World, parent_branch_id: str, name: str, description: str = "") -> Branch:
    new_branch = Branch(
        id=_new_id("br"), world_id=world.id, name=name,
        description=description, parent_branch_id=parent_branch_id,
        diverged_at_tick=world.current_tick,
    )
    db.add(new_branch)
    db.flush()
    old_to_new: dict[str, str] = {}
    for entity in db.query(Entity).filter_by(branch_id=parent_branch_id).all():
        new_id = _new_id("ent")
        old_to_new[entity.id] = new_id
        db.add(Entity(
            id=new_id, branch_id=new_branch.id, type=entity.type, name=entity.name,
            summary=entity.summary, attributes=dict(entity.attributes or {}), aliases=list(entity.aliases or []),
            state=dict(entity.state or {}), location_id=None,
            created_at_tick=entity.created_at_tick, alive=entity.alive,
        ))
    db.flush()
    for entity in db.query(Entity).filter_by(branch_id=parent_branch_id).all():
        if entity.location_id:
            new_id = old_to_new.get(entity.id)
            new_loc = old_to_new.get(entity.location_id, entity.location_id)
            db.query(Entity).filter_by(id=new_id).update({"location_id": new_loc})
    ev_old_to_new: dict[str, str] = {}
    for ev in db.query(Event).filter_by(branch_id=parent_branch_id).all():
        new_id = _new_id("evt")
        ev_old_to_new[ev.id] = new_id
        db.add(Event(
            id=new_id, branch_id=new_branch.id, tick=ev.tick, title=ev.title,
            description=ev.description,
            location_id=old_to_new.get(ev.location_id) if ev.location_id else None,
            participants=[old_to_new.get(p, p) for p in (ev.participants or [])],
            consequences=list(ev.consequences or []),
            metadata_=dict(ev.metadata_ or {}), deleted=ev.deleted,
        ))
    for l in db.query(CausalLink).filter_by(branch_id=parent_branch_id).all():
        db.add(CausalLink(
            id=_new_id("cau"), branch_id=new_branch.id,
            cause_event_id=ev_old_to_new.get(l.cause_event_id, l.cause_event_id),
            effect_event_id=ev_old_to_new.get(l.effect_event_id, l.effect_event_id),
            description=l.description, weight=l.weight,
        ))
    for n in db.query(NarrativeLog).filter_by(branch_id=parent_branch_id).all():
        db.add(NarrativeLog(
            id=_new_id("nar"), branch_id=new_branch.id,
            tick=n.tick, role=n.role, text=n.text,
        ))
    db.flush()
    return new_branch


class ExploreVariant(BaseModel):
    label: str
    directive: str


class ExploreRequest(BaseModel):
    variants: list[ExploreVariant]
    steps: int = 1
    provider: str | None = None


@router.post("/worlds/{world_id}/explore")
def parallel_explore(world_id: str, payload: ExploreRequest, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    if not payload.variants or len(payload.variants) < 2:
        raise HTTPException(400, "need at least 2 variants")
    if len(payload.variants) > 5:
        raise HTTPException(400, "max 5 variants per explore run")

    parent_branch_id = world.active_branch_id
    parent_branch = db.query(Branch).filter_by(id=parent_branch_id).first()
    parent_name = parent_branch.name if parent_branch else "main"

    forked = []
    for v in payload.variants:
        label = (v.label or "").strip() or "what-if"
        new_branch = _fork_branch(
            db, world, parent_branch_id,
            name=f"{parent_name}/{label}",
            description=f"并发探索：{v.directive[:80]}",
        )
        forked.append((new_branch.id, new_branch.name, v.directive))
    db.commit()

    out = []
    steps = max(1, min(payload.steps, 5))
    for branch_id, branch_name, directive in forked:
        job = create_job(world_id, "explore")
        job.status = "running"
        job.progress_message = f"分支 {branch_name} 准备中"

        def runner(bid=branch_id, bname=branch_name, drct=directive, j=job):
            local_db = SessionLocal()
            try:
                local_world = local_db.query(World).filter_by(id=world_id).first()
                if not local_world:
                    j.error = "world not found"; j.status = "error"; return
                local_world._override_branch_id = bid
                try:
                    capture_branch_snapshot(local_db, local_world, label=f"探索前 · {drct[:30]}")
                    local_db.commit()
                except Exception:
                    log.exception("explore pre-snapshot failed")
                    local_db.rollback()

                provider = get_provider(payload.provider) if payload.provider else None

                def progress(info):
                    if "tool_calls" in info:
                        j.tool_calls = list(info["tool_calls"])
                    if "narration" in info:
                        j.narration = info["narration"]
                    phase = info.get("phase", "")
                    if phase == "step_start":
                        j.progress_message = f"[{bname}] 第 {info['step']}/{info['total']} 步"
                    elif phase == "thinking":
                        j.progress_message = f"[{bname}] AI 思考中"
                    elif phase == "executing":
                        j.progress_message = f"[{bname}] 已执行 {len(j.tool_calls)} 个工具"

                results = run_auto(
                    local_db, local_world, steps=steps,
                    user_directive=drct, provider=provider,
                    cancel_check=j.is_cancelled, on_progress=progress,
                )
                j.result = {
                    "branch_id": bid, "branch_name": bname,
                    "directive": drct, "results": results,
                    "tick": local_world.current_tick,
                }
                j.status = "cancelled" if j.is_cancelled() else "completed"
            except CancelledError:
                j.status = "cancelled"
            except Exception as e:
                log.exception("explore job failed")
                j.error = f"{type(e).__name__}: {e}"
                j.status = "error"
            finally:
                import time as _t
                j.finished_at = _t.time()
                local_db.close()

        threading.Thread(target=runner, daemon=True).start()
        out.append({
            "job_id": job.id, "branch_id": branch_id,
            "branch_name": branch_name, "directive": directive,
        })

    return {"variants": out, "parent_branch_id": parent_branch_id}


class EvaluateVariantsRequest(BaseModel):
    variant_branch_ids: list[str]
    parent_branch_id: str
    parent_tick: int
    provider: str | None = None


@router.post("/worlds/{world_id}/evaluate_variants")
def evaluate_variants(world_id: str, payload: EvaluateVariantsRequest, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")

    parent_events = (
        db.query(Event)
        .filter_by(branch_id=payload.parent_branch_id, deleted=0)
        .filter(Event.tick <= payload.parent_tick)
        .order_by(Event.tick.desc())
        .limit(8).all()
    )
    parent_summary = "\n".join(f"- t{e.tick} {e.title}：{e.description[:100]}" for e in reversed(parent_events)) or "（无前情）"

    variants_text_parts = []
    variant_meta = []
    for bid in payload.variant_branch_ids:
        branch = db.query(Branch).filter_by(id=bid).first()
        if not branch:
            continue
        new_events = (
            db.query(Event)
            .filter_by(branch_id=bid, deleted=0)
            .filter(Event.tick > payload.parent_tick)
            .order_by(Event.tick).all()
        )
        new_narration = (
            db.query(NarrativeLog).filter_by(branch_id=bid)
            .filter(NarrativeLog.tick > payload.parent_tick)
            .order_by(NarrativeLog.tick).all()
        )
        ev_text = "\n".join(f"  - t{e.tick} {e.title}：{e.description[:140]}" for e in new_events) or "  （未产生事件）"
        nar_text = "\n".join(f"  > {n.text[:160]}" for n in new_narration[:4]) or ""
        variants_text_parts.append(
            f"### 变体 {branch.name.split('/')[-1]} (id={bid})\n指令：{branch.description or '无'}\n新增事件：\n{ev_text}" + (f"\n叙事片段：\n{nar_text}" if nar_text else "")
        )
        variant_meta.append({"branch_id": bid, "label": branch.name.split('/')[-1]})

    if not variants_text_parts:
        raise HTTPException(400, "no valid variants found")

    rules_block = render_world_rules(world.rules)
    from ..engine.tools import build_world_lore_block as _bwlb_eval
    lore_block = _bwlb_eval(db, world)

    sys_prompt = f"""你是一位资深叙事编辑，擅长在多个故事走向中评估优劣。

世界设定：{world.name} — {world.description or ''}
{rules_block}
{lore_block}

# 评估前的局面（分叉点之前最近 8 件事）
{parent_summary}

# 候选变体（从同一节点分别推演而成）
{chr(10).join(variants_text_parts)}

# 你的任务
对每个变体打 4 项分（1-10 整数）：
- tension：戏剧张力（冲突/悬念/转折是否抓人）
- consistency：角色一致性（角色行为是否符合此前的属性与处境）
- rules：世界规则吻合度（是否违反硬规则或基调；无规则时按设定合理性打）
- originality：新意（是否陈词滥调）

并给出 verdict：一句话点评每个变体的核心亮点或硬伤（不超过 50 字）。
最后给 recommended：你最推荐采纳的 branch_id（只能选一个）。

严格输出 JSON，禁止任何额外说明：
{{
  "evaluations": [
    {{"branch_id": "br_xxx", "scores": {{"tension": 8, "consistency": 7, "rules": 9, "originality": 6}}, "verdict": "..."}},
    ...
  ],
  "recommended": "br_xxx",
  "reasoning": "为什么推荐这个（不超过 80 字）"
}}
"""

    provider = get_provider(payload.provider) if payload.provider else get_provider()
    try:
        resp = provider.chat(
            system=sys_prompt,
            messages=[Message(role="user", content="请评估上述变体并按规定 JSON 输出。")],
            tools=[],
            max_tokens=1200,
            temperature=0.3,
        )
    except Exception as e:
        log.exception("evaluate failed")
        raise HTTPException(500, f"evaluate failed: {e}")

    raw = resp.text or ""
    parsed: dict[str, Any] = {}
    try:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            parsed = json.loads(raw[start:end+1])
    except Exception:
        log.warning("evaluate JSON parse failed: %s", raw[:200])
        parsed = {}

    evals = parsed.get("evaluations") or []
    recommended = parsed.get("recommended") or ""
    reasoning = parsed.get("reasoning") or ""
    by_id = {e.get("branch_id"): e for e in evals if isinstance(e, dict)}

    enriched = []
    for v in variant_meta:
        e = by_id.get(v["branch_id"]) or {}
        scores = e.get("scores") or {}
        total = sum(int(scores.get(k, 0) or 0) for k in ("tension", "consistency", "rules", "originality"))
        enriched.append({
            "branch_id": v["branch_id"],
            "label": v["label"],
            "scores": {
                "tension": int(scores.get("tension", 0) or 0),
                "consistency": int(scores.get("consistency", 0) or 0),
                "rules": int(scores.get("rules", 0) or 0),
                "originality": int(scores.get("originality", 0) or 0),
            },
            "total": total,
            "verdict": str(e.get("verdict") or ""),
        })

    return {
        "evaluations": enriched,
        "recommended": recommended,
        "reasoning": reasoning,
        "raw_ok": bool(parsed),
    }
