"""风格档案 / 小说化导出（export-novel）API。

3 端点：
- GET  /style_profiles
- GET  /style_profiles/{id}
- POST /worlds/{id}/export
"""
from __future__ import annotations
import json
import logging
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..models import (
    get_db, World, Branch, Entity, Event, NarrativeLog, ChapterMarker, StyleProfile,
)
from ..engine.tools import render_world_rules
from ..providers import get_provider, Message

log = logging.getLogger(__name__)
router = APIRouter()


# ============== style profiles (A4) ==============

@router.get("/style_profiles")
def list_style_profiles(db: Session = Depends(get_db)):
    """列所有风格档案。前端在'世界设置'弹窗里展示给用户选择。

    返回 builtin（系统内置）+ custom（用户自建）两组。spec_text 不返回——
    前端只需要展示用元数据，需要看 spec 再单独 GET /style_profiles/{id}。
    """
    rows = db.query(StyleProfile).order_by(StyleProfile.kind.asc(), StyleProfile.name.asc()).all()
    return {
        "profiles": [
            {
                "id": r.id,
                "name": r.name,
                "description": r.description or "",
                "kind": r.kind or "builtin",
                "category": r.category or "",
                "frozen": bool(r.frozen),
            }
            for r in rows
        ]
    }


@router.get("/style_profiles/{style_id}")
def get_style_profile(style_id: str, db: Session = Depends(get_db)):
    r = db.query(StyleProfile).filter_by(id=style_id).first()
    if not r:
        raise HTTPException(404, "style_profile not found")
    return {
        "id": r.id,
        "name": r.name,
        "description": r.description or "",
        "kind": r.kind or "builtin",
        "category": r.category or "",
        "spec_text": r.spec_text or "",
        "sample_paragraphs": r.sample_paragraphs or [],
        "frozen": bool(r.frozen),
    }



class ExportRequest(BaseModel):
    mode: str = "raw"
    tick_from: int | None = None
    tick_to: int | None = None
    chapter_size: int = 5
    use_chapter_markers: bool = True
    include_critique: bool = False
    include_events: bool = True
    include_narration: bool = True
    include_entities: bool = False
    provider: str | None = None


@router.post("/worlds/{world_id}/export")
def export_world(world_id: str, payload: ExportRequest, db: Session = Depends(get_db)):
    world = db.query(World).filter_by(id=world_id).first()
    if not world:
        raise HTTPException(404, "world not found")
    branch_id = world.active_branch_id
    branch = db.query(Branch).filter_by(id=branch_id).first()

    tick_lo = 0 if payload.tick_from is None else max(0, payload.tick_from)
    tick_hi = world.current_tick if payload.tick_to is None else payload.tick_to

    events = (
        db.query(Event).filter_by(branch_id=branch_id, deleted=0)
        .filter(Event.tick >= tick_lo, Event.tick <= tick_hi)
        .order_by(Event.tick).all()
    )
    narration = (
        db.query(NarrativeLog).filter_by(branch_id=branch_id)
        .filter(NarrativeLog.tick >= tick_lo, NarrativeLog.tick <= tick_hi)
        .order_by(NarrativeLog.tick).all()
    )
    entities = db.query(Entity).filter_by(branch_id=branch_id).all()
    by_id = {e.id: e for e in entities}

    if payload.mode == "json":
        return {
            "format": "json",
            "filename": f"{world.name}_{branch.name if branch else 'main'}_{tick_lo}-{tick_hi}.json",
            "content": json.dumps({
                "world": {"name": world.name, "description": world.description, "rules": world.rules or {}},
                "branch": branch.name if branch else "main",
                "tick_range": [tick_lo, tick_hi],
                "entities": [{"id": e.id, "type": e.type, "name": e.name, "summary": e.summary,
                              "attributes": e.attributes or {}, "state": e.state or {}, "alive": e.alive,
                              "location_id": e.location_id, "created_at_tick": e.created_at_tick} for e in entities],
                "events": [{"id": ev.id, "tick": ev.tick, "title": ev.title, "description": ev.description,
                            "participants": ev.participants or [], "consequences": ev.consequences or [],
                            "location_id": ev.location_id} for ev in events],
                "narration": [{"tick": n.tick, "role": n.role, "text": n.text} for n in narration],
            }, ensure_ascii=False, indent=2),
        }

    if payload.mode == "raw":
        lines = [f"# {world.name}", ""]
        if world.description:
            lines += [world.description, ""]
        lines += [f"*分支：{branch.name if branch else 'main'} · tick {tick_lo}–{tick_hi}*", ""]

        if payload.include_entities:
            chars = [e for e in entities if e.type == "character"]
            if chars:
                lines += ["## 主要人物", ""]
                for e in chars:
                    state = "" if e.alive else "（已逝）"
                    lines.append(f"- **{e.name}**{state} — {e.summary or ''}")
                lines.append("")

        ticks = sorted(set([ev.tick for ev in events] + [n.tick for n in narration]))
        if ticks:
            lines += ["## 故事正文", ""]
            ev_by_tick: dict[int, list[Event]] = {}
            for ev in events:
                ev_by_tick.setdefault(ev.tick, []).append(ev)
            nar_by_tick: dict[int, list[NarrativeLog]] = {}
            for n in narration:
                nar_by_tick.setdefault(n.tick, []).append(n)

            for t in ticks:
                lines.append(f"### t{t}")
                if payload.include_narration:
                    for n in nar_by_tick.get(t, []):
                        lines.append(n.text)
                        lines.append("")
                if payload.include_events:
                    for ev in ev_by_tick.get(t, []):
                        parts = "、".join(by_id[p].name for p in (ev.participants or []) if p in by_id)
                        loc = by_id.get(ev.location_id).name if ev.location_id and ev.location_id in by_id else ""
                        meta_bits = " ".join(f"[{x}]" for x in [parts, loc] if x)
                        lines.append(f"- **{ev.title}** {meta_bits}")
                        if ev.description:
                            lines.append(f"  > {ev.description}")
                lines.append("")

        return {
            "format": "markdown",
            "filename": f"{world.name}_{tick_lo}-{tick_hi}.md",
            "content": "\n".join(lines),
        }

    if payload.mode == "novelize":
        if not events and not narration:
            raise HTTPException(400, "no events or narration in range to novelize")

        markers = []
        if payload.use_chapter_markers:
            markers = (
                db.query(ChapterMarker).filter_by(branch_id=branch_id)
                .filter(ChapterMarker.tick >= tick_lo, ChapterMarker.tick <= tick_hi)
                .order_by(ChapterMarker.tick).all()
            )

        chunks: list[tuple[int, int, list[Event], list[NarrativeLog], str]] = []
        if markers:
            cursor = tick_lo
            for m in markers:
                cs, ce_t = cursor, m.tick
                ce_events = [ev for ev in events if cs <= ev.tick <= ce_t]
                ce_narr = [n for n in narration if cs <= n.tick <= ce_t]
                if ce_events or ce_narr:
                    chunks.append((cs, ce_t, ce_events, ce_narr, m.title or ""))
                cursor = m.tick + 1
            if cursor <= tick_hi:
                ce_events = [ev for ev in events if cursor <= ev.tick <= tick_hi]
                ce_narr = [n for n in narration if cursor <= n.tick <= tick_hi]
                if ce_events or ce_narr:
                    chunks.append((cursor, tick_hi, ce_events, ce_narr, ""))
        else:
            chunk_size = max(1, min(payload.chapter_size, 20))
            for chunk_start in range(tick_lo, tick_hi + 1, chunk_size):
                chunk_end = min(chunk_start + chunk_size - 1, tick_hi)
                chunk_events = [ev for ev in events if chunk_start <= ev.tick <= chunk_end]
                chunk_narr = [n for n in narration if chunk_start <= n.tick <= chunk_end]
                if chunk_events or chunk_narr:
                    chunks.append((chunk_start, chunk_end, chunk_events, chunk_narr, ""))

        rules_block = render_world_rules(world.rules)
        from ..engine.tools import build_world_lore_block as _bwlb_novel
        lore_block = _bwlb_novel(db, world)
        char_list = "\n".join(
            f"- {e.name}（{e.type}）: {e.summary or ''}" for e in entities if e.type == "character"
        ) or "（无角色）"
        provider = get_provider(payload.provider) if payload.provider else get_provider()

        chapters_md: list[str] = [f"# {world.name}"]
        if world.description:
            chapters_md += ["", world.description]
        chunk_source = "章节标记" if markers else f"每 {payload.chapter_size} ticks"
        chapters_md += [f"\n*分支 {branch.name if branch else 'main'} · 共 {len(chunks)} 章 · 切分方式：{chunk_source}*", ""]

        for idx, (cs, ce, ce_events, ce_narr, hint_title) in enumerate(chunks, start=1):
            ev_text = "\n".join(
                f"- t{ev.tick} 《{ev.title}》参与：{'、'.join(by_id[p].name for p in (ev.participants or []) if p in by_id) or '—'}\n  详情：{ev.description}"
                for ev in ce_events
            ) or "（无事件）"
            narr_text = "\n".join(f"- t{n.tick}: {n.text}" for n in ce_narr) or "（无既有叙事）"
            title_hint = f"\n章节标题已由编辑预设为：{hint_title}（请直接使用）" if hint_title else ""

            sys_prompt = f"""你是一位优秀的小说家，正在把一段世界推演的结构化日志改写成连贯的小说章节。

世界：{world.name} — {world.description or ''}
{rules_block}
{lore_block}

主要人物：
{char_list}

# 第 {idx} 章原始材料（t{cs}–t{ce}）
## 事件
{ev_text}

## 已有叙事片段（可借鉴或忽略）
{narr_text}

# 你的任务
把以上事件改写成一段 600-1200 字的连贯小说章节散文。要求：
- 不要列举事件，要叙述
- 用对话和细节让人物活起来
- 保留事件的因果与时序
- 尊重世界规则与基调
- 章节开头给一个吸引人的标题（不带"第X章"字样，只一个 4-12 字的题眼）{title_hint}

输出格式：
## {{章节标题}}

{{正文段落，多段}}

不要输出额外说明、不要写元注释。
"""
            chap_text = ""
            try:
                resp = provider.chat(
                    system=sys_prompt,
                    messages=[Message(role="user", content="开始写作。")],
                    tools=[],
                    max_tokens=2400,
                    temperature=0.85,
                )
                chap_text = (resp.text or "").strip()
                if not chap_text.startswith("##"):
                    chap_text = f"## {hint_title or f'第 {idx} 章'}\n\n{chap_text}"
                chapters_md.append(chap_text)
            except Exception as e:
                log.exception("novelize chapter failed")
                chapters_md.append(f"## 第 {idx} 章\n\n*[小说化失败：{e}]*\n\n原始事件：\n{ev_text}")

            if payload.include_critique and chap_text:
                critique_prompt = f"""你是写作教练。下方是一章新写出的小说，给作者一段 80-160 字的简短点评。

世界基调：{(world.rules or {}).get('tone','')}
本章原始事件清单（看是否被妥善表达）：
{ev_text}

本章正文：
{chap_text[:3000]}

要求点评聚焦：
- 伏笔/钩子：本章埋了或回收了哪些
- 角色弧：哪些角色的状态、关系、动机有推进
- 节奏：是否拖沓或过快
- 一个**具体可执行**的修改建议

格式：纯文本，不要标题，2-3 段。"""
                try:
                    cr = provider.chat(
                        system=critique_prompt,
                        messages=[Message(role="user", content="给出点评。")],
                        tools=[], max_tokens=600, temperature=0.5,
                    )
                    crit = (cr.text or "").strip()
                    if crit:
                        chapters_md.append("")
                        chapters_md.append(f"> 📝 **编辑笔记**\n>\n> " + crit.replace("\n", "\n> "))
                except Exception as e:
                    log.warning("critique failed: %s", e)
            chapters_md.append("")

        return {
            "format": "markdown",
            "filename": f"{world.name}_小说_{tick_lo}-{tick_hi}.md",
            "content": "\n".join(chapters_md),
            "chapters": len(chunks),
            "chunked_by": "markers" if markers else "size",
        }

    raise HTTPException(400, f"unknown mode: {payload.mode}")

