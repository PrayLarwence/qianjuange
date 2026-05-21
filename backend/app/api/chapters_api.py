"""章节标记 / 章节批注 / 自动分章 / 建议指令相关 API。

10 端点：
- GET    /worlds/{id}/chapters
- POST   /worlds/{id}/chapters
- PATCH  /chapters/{id}
- DELETE /chapters/{id}
- DELETE /worlds/{id}/chapters/{id}
- POST   /chapters/{id}/critique
- GET    /chapters/{id}/critique
- POST   /worlds/{id}/chapters/regenerate-summaries
- POST   /worlds/{id}/chapters/auto
- POST   /worlds/{id}/suggest_directives
"""
from __future__ import annotations
import json
import logging
import uuid
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..models import (
    get_db, World, Branch, Entity, Event, NarrativeLog, ChapterMarker, ChapterFeedback,
)
from ..engine import build_state_snapshot
from ..engine.tools import render_world_rules
from ..engine.state import state_as_prompt
from ..providers import get_provider, Message
from ._common import _new_id

log = logging.getLogger(__name__)
router = APIRouter()


# ============== chapter markers ==============

@router.get("/worlds/{world_id}/chapters")
def list_chapters(world_id: str, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    rows = (
        db.query(ChapterMarker)
        .filter_by(branch_id=world.active_branch_id)
        .order_by(ChapterMarker.tick).all()
    )
    return {"chapters": [{
        "id": r.id, "tick": r.tick, "title": r.title or "",
        "note": r.note or "", "summary": r.summary or ""
    } for r in rows]}


class ChapterCreateRequest(BaseModel):
    tick: int
    title: str = ""
    note: str = ""
    branch_id: str | None = None  # default: world.active_branch_id


@router.post("/worlds/{world_id}/chapters")
def create_chapter(world_id: str, payload: ChapterCreateRequest, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    bid = payload.branch_id or world.active_branch_id
    # ensure branch belongs to this world
    if not db.query(Branch).filter_by(id=bid, world_id=world_id).first():
        raise HTTPException(400, "branch not in this world")
    existing = db.query(ChapterMarker).filter_by(
        branch_id=bid, tick=payload.tick
    ).first()
    if existing:
        existing.title = payload.title or existing.title
        existing.note = payload.note or existing.note
        db.commit()
        return {"id": existing.id, "branch_id": existing.branch_id, "tick": existing.tick,
                "title": existing.title, "note": existing.note}
    cm = ChapterMarker(
        id=f"ch_{uuid.uuid4().hex[:10]}",
        branch_id=bid,
        tick=payload.tick,
        title=payload.title.strip(),
        note=payload.note.strip(),
    )
    db.add(cm); db.commit()
    return {"id": cm.id, "branch_id": cm.branch_id, "tick": cm.tick, "title": cm.title, "note": cm.note}


class ChapterPatchRequest(BaseModel):
    title: str | None = None
    note: str | None = None
    tick: int | None = None


@router.patch("/chapters/{chapter_id}")
def patch_chapter(chapter_id: str, payload: ChapterPatchRequest, db: Session = Depends(get_db)):
    cm = db.query(ChapterMarker).filter_by(id=chapter_id).first()
    if not cm:
        raise HTTPException(404, "chapter not found")
    if payload.title is not None: cm.title = payload.title.strip()
    if payload.note  is not None: cm.note  = payload.note.strip()
    if payload.tick  is not None: cm.tick  = payload.tick
    db.commit()
    return {"id": cm.id, "branch_id": cm.branch_id, "tick": cm.tick, "title": cm.title, "note": cm.note}


@router.delete("/chapters/{chapter_id}")
def delete_chapter_global(chapter_id: str, db: Session = Depends(get_db)):
    cm = db.query(ChapterMarker).filter_by(id=chapter_id).first()
    if not cm:
        raise HTTPException(404, "chapter not found")
    db.delete(cm); db.commit()
    return {"ok": True}



@router.delete("/worlds/{world_id}/chapters/{chapter_id}")
def delete_chapter(world_id: str, chapter_id: str, db: Session = Depends(get_db)):
    cm = db.query(ChapterMarker).filter_by(id=chapter_id).first()
    if not cm:
        raise HTTPException(404, "chapter not found")
    db.delete(cm); db.commit()
    return {"ok": True}


# ============== editor agent (A5) ==============

class ChapterCritiqueRequest(BaseModel):
    provider: str | None = None


@router.post("/chapters/{chapter_id}/critique")
def critique_chapter(chapter_id: str, payload: ChapterCritiqueRequest, db: Session = Depends(get_db)):
    """对某一章节跑 Editor 审稿。同步执行——LLM 调用可能需要几秒到几十秒，
    前端应给出 loading 反馈。返回评注文本 + issue 列表。
    """
    cm = db.query(ChapterMarker).filter_by(id=chapter_id).first()
    if not cm:
        raise HTTPException(404, "chapter not found")
    branch = db.query(Branch).filter_by(id=cm.branch_id).first()
    if not branch:
        raise HTTPException(500, "chapter has no branch")
    world = db.query(World).filter_by(id=branch.world_id).first()
    if not world:
        raise HTTPException(500, "branch has no world")

    from ..engine.editor import run_editor_for_chapter
    result = run_editor_for_chapter(db, world, cm, provider_key=payload.provider)
    return {
        "ok": result.ok,
        "reason": result.reason,
        "scan_id": result.scan_id,
        "issue_count": result.issue_count,
        "critique_log_id": result.critique_log_id,
        "critique_text": result.critique_text,
        "tick_from": result.tick_from,
        "tick_to": result.tick_to,
    }


@router.get("/chapters/{chapter_id}/critique")
def get_chapter_critique(chapter_id: str, db: Session = Depends(get_db)):
    """读章节当前评注与对应的 issues。没审过返 has_critique=False。"""
    cm = db.query(ChapterMarker).filter_by(id=chapter_id).first()
    if not cm:
        raise HTTPException(404, "chapter not found")
    from ..engine.editor import get_chapter_critique as _get
    return _get(db, cm)


class AutoChapterRequest(BaseModel):
    target_count: int = 5
    provider: str | None = None


class RegenerateSummariesRequest(BaseModel):
    provider: str | None = None
    only_missing: bool = False  # True 时跳过已有 summary 的章节


@router.post("/worlds/{world_id}/chapters/regenerate-summaries")
def regenerate_chapter_summaries(
    world_id: str, payload: RegenerateSummariesRequest, db: Session = Depends(get_db)
):
    """B1：批量为本世界 active branch 的章节生成 summary（喂 Director prompt 用）。

    同步执行——每章一次 LLM 调用，章节多时会比较慢。前端应给 loading。
    only_missing=True 时只补漏，否则全量重写。
    """
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")

    from ..engine.recap import regenerate_all_summaries
    provider = get_provider(payload.provider) if payload.provider else get_provider()
    if provider is None:
        raise HTTPException(503, "no LLM provider available")
    result = regenerate_all_summaries(db, world, provider, only_missing=payload.only_missing)
    return {
        "ok": result.ok,
        "reason": result.reason,
        "chapters_processed": result.chapters_processed,
        "chapters_succeeded": result.chapters_succeeded,
        "chapters_failed": result.chapters_failed,
    }


@router.post("/worlds/{world_id}/chapters/auto")
def auto_chapter(world_id: str, payload: AutoChapterRequest, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    branch_id = world.active_branch_id
    events = db.query(Event).filter_by(branch_id=branch_id, deleted=0).order_by(Event.tick).all()
    if len(events) < 2:
        return {"chapters": [], "reason": "事件太少，无需分章"}

    target = max(2, min(payload.target_count, 12))
    by_id = {e.id: e for e in db.query(Entity).filter_by(branch_id=branch_id).all()}
    ev_lines = []
    for ev in events:
        parts = "、".join(by_id[p].name for p in (ev.participants or []) if p in by_id) or "—"
        ev_lines.append(f"t{ev.tick}|《{ev.title}》|参与:{parts}|{ev.description[:80]}")

    sys_prompt = f"""你是一位资深小说编辑，要给以下故事划分**约 {target} 个**章节。

世界：{world.name}
{render_world_rules(world.rules)}

事件序列（按时间）：
{chr(10).join(ev_lines)}

# 你的任务
找出**自然的章节断点**——通常是：场景切换、时间跳跃、视角转换、剧情节奏转折。
每个断点选一个 tick 作为"章末"。
给每章起一个 4-12 字的题眼（不含"第X章"字样）。

严格输出 JSON：
{{
  "chapters": [
    {{"end_tick": 7, "title": "鲁山雪夜"}},
    {{"end_tick": 15, "title": "刀光初现"}},
    ...
  ]
}}
不要输出任何额外说明。
"""
    provider = get_provider(payload.provider) if payload.provider else get_provider()
    try:
        resp = provider.chat(
            system=sys_prompt,
            messages=[Message(role="user", content="开始分章。")],
            tools=[],
            max_tokens=1200,
            temperature=0.5,
        )
    except Exception as e:
        log.exception("auto chapter failed")
        raise HTTPException(500, f"auto chapter failed: {e}")

    raw = resp.text or ""
    parsed: dict[str, Any] = {}
    try:
        s = raw.find("{"); e = raw.rfind("}")
        if s >= 0 and e > s:
            parsed = json.loads(raw[s:e+1])
    except Exception:
        log.warning("auto chapter JSON parse failed")

    chs = parsed.get("chapters") or []
    db.query(ChapterMarker).filter_by(branch_id=branch_id).delete()
    out = []
    new_chapter_ids: list[str] = []
    for ch in chs:
        if not isinstance(ch, dict):
            continue
        try:
            t = int(ch.get("end_tick", -1))
        except Exception:
            continue
        title = (ch.get("title") or "").strip()
        if t < 0 or not title:
            continue
        cm = ChapterMarker(
            id=f"ch_{uuid.uuid4().hex[:10]}",
            branch_id=branch_id, tick=t, title=title,
        )
        db.add(cm)
        out.append({"id": cm.id, "tick": t, "title": title})
        new_chapter_ids.append(cm.id)
    db.commit()

    # B4: 顺手生成每章 summary——失败不影响章节本体
    summaries_generated = 0
    summaries_failed = 0
    summaries_skipped_reason: str | None = None
    if (world.rules or {}).get("disable_chapter_recap"):
        summaries_skipped_reason = "disabled_by_rule"
    elif new_chapter_ids:
        from ..engine.recap import generate_chapter_summary
        for ch_id in new_chapter_ids:
            cm = db.query(ChapterMarker).filter_by(id=ch_id).first()
            if not cm:
                continue
            try:
                result = generate_chapter_summary(db, world, cm, provider)
            except Exception:
                log.exception("auto recap unexpected error for %s", ch_id)
                result = None
            if result is None:
                summaries_failed += 1
            else:
                summaries_generated += 1
        db.commit()

    return {
        "chapters": out,
        "raw_ok": bool(parsed),
        "summaries_generated": summaries_generated,
        "summaries_failed": summaries_failed,
        "summaries_skipped_reason": summaries_skipped_reason,
    }


class SuggestDirectivesRequest(BaseModel):
    n: int = 4
    style: str = ""
    provider: str | None = None


@router.post("/worlds/{world_id}/suggest_directives")
def suggest_directives(world_id: str, payload: SuggestDirectivesRequest, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")

    snapshot = build_state_snapshot(db, world, max_events=20, max_entities=40)
    state_text = state_as_prompt(snapshot)
    rules_block = render_world_rules(world.rules)
    n = max(2, min(payload.n, 6))
    style_hint = (payload.style or "").strip()

    sys_prompt = f"""你是叙事教练，看到当前世界状态后，要给作者推荐 {n} 个**截然不同**的下一步推演方向。

世界：{world.name}
{rules_block}

# 当前状态
{state_text}

# 你的任务
基于现有人物、未解决的伏笔、关系张力，提出 {n} 条可执行的"下一步指令"。要求：
- 每条都是**具体动作**，不是抽象描述（错：让矛盾升级；对：让张三在酒馆撞见李四的妻子）
- 各条之间**走向迥异**（一条悲剧路线、一条温情路线、一条意外转折…）
- 充分利用当前已埋下的钩子和角色关系
- 每条带 kind 标签：'continue' 顺势 / 'twist' 反转 / 'tragic' 悲剧 / 'tender' 温情 / 'reveal' 揭秘 / 'conflict' 冲突
{f'- 风格倾向：{style_hint}' if style_hint else ''}

严格输出 JSON：
{{
  "suggestions": [
    {{"kind": "twist", "directive": "...", "rationale": "为什么这条有戏（不超过 40 字）"}},
    ...
  ]
}}
"""
    provider = get_provider(payload.provider) if payload.provider else get_provider()
    try:
        resp = provider.chat(
            system=sys_prompt,
            messages=[Message(role="user", content="请按 JSON 给出建议。")],
            tools=[],
            max_tokens=1200,
            temperature=0.85,
        )
    except Exception as e:
        log.exception("suggest failed")
        raise HTTPException(500, f"suggest failed: {e}")

    raw = resp.text or ""
    parsed: dict[str, Any] = {}
    try:
        s = raw.find("{"); e = raw.rfind("}")
        if s >= 0 and e > s:
            parsed = json.loads(raw[s:e+1])
    except Exception:
        log.warning("suggest JSON parse failed: %s", raw[:200])

    sugg = parsed.get("suggestions") or []
    out = []
    for x in sugg[:n]:
        if not isinstance(x, dict):
            continue
        d = (x.get("directive") or "").strip()
        if not d:
            continue
        out.append({
            "kind": (x.get("kind") or "continue").strip(),
            "directive": d,
            "rationale": (x.get("rationale") or "").strip(),
        })
    return {"suggestions": out, "raw_ok": bool(parsed)}


# ============== chapter feedback (路线 #8 MVP) ==============

ALLOWED_SCORES = {-1, 0, 1}


def _serialize_feedback(fb: ChapterFeedback | None) -> dict | None:
    if fb is None:
        return None
    return {
        "id": fb.id,
        "chapter_id": fb.chapter_id,
        "score": fb.score,
        "comment": fb.comment or "",
        "created_at": fb.created_at.isoformat() if fb.created_at else "",
        "updated_at": fb.updated_at.isoformat() if fb.updated_at else "",
    }


class ChapterFeedbackUpsertRequest(BaseModel):
    score: int = Field(..., description="-1 差 / 0 普通 / 1 好")
    comment: str = ""


@router.put("/chapters/{chapter_id}/feedback")
def upsert_chapter_feedback(
    chapter_id: str,
    payload: ChapterFeedbackUpsertRequest,
    db: Session = Depends(get_db),
):
    if payload.score not in ALLOWED_SCORES:
        raise HTTPException(400, "score 必须是 -1 / 0 / 1")
    chapter = db.query(ChapterMarker).filter_by(id=chapter_id).first()
    if not chapter:
        raise HTTPException(404, "chapter not found")
    fb = db.query(ChapterFeedback).filter_by(chapter_id=chapter_id).first()
    if fb is None:
        fb = ChapterFeedback(
            id=_new_id("fb"),
            chapter_id=chapter_id,
            branch_id=chapter.branch_id,
            score=payload.score,
            comment=(payload.comment or "")[:2000],
        )
        db.add(fb)
    else:
        fb.score = payload.score
        fb.comment = (payload.comment or "")[:2000]
    db.commit()
    db.refresh(fb)
    return _serialize_feedback(fb)


@router.delete("/chapters/{chapter_id}/feedback")
def delete_chapter_feedback(chapter_id: str, db: Session = Depends(get_db)):
    fb = db.query(ChapterFeedback).filter_by(chapter_id=chapter_id).first()
    if fb is None:
        return {"deleted": 0}
    db.delete(fb)
    db.commit()
    return {"deleted": 1}


@router.get("/worlds/{world_id}/chapter_feedback")
def list_chapter_feedback(world_id: str, db: Session = Depends(get_db)):
    """列出该世界 active branch 上所有章节的反馈（含尚未打分的章节，feedback=None）。"""
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    chapters = (
        db.query(ChapterMarker)
        .filter_by(branch_id=world.active_branch_id)
        .order_by(ChapterMarker.tick).all()
    )
    chapter_ids = [c.id for c in chapters]
    fb_by_chapter: dict[str, ChapterFeedback] = {}
    if chapter_ids:
        for fb in db.query(ChapterFeedback).filter(ChapterFeedback.chapter_id.in_(chapter_ids)).all():
            fb_by_chapter[fb.chapter_id] = fb
    items = []
    score_counts = {-1: 0, 0: 0, 1: 0}
    for c in chapters:
        fb = fb_by_chapter.get(c.id)
        if fb is not None:
            score_counts[fb.score] = score_counts.get(fb.score, 0) + 1
        items.append({
            "chapter_id": c.id,
            "tick": c.tick,
            "title": c.title or "",
            "feedback": _serialize_feedback(fb),
        })
    return {
        "items": items,
        "summary": {
            "total_chapters": len(chapters),
            "rated": sum(score_counts.values()),
            "good": score_counts[1],
            "neutral": score_counts[0],
            "bad": score_counts[-1],
        },
    }

