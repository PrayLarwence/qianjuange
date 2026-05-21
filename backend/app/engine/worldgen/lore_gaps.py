"""B7: 让 LLM 扫描叙事中反复出现但缺乏 lore 解释的名词候选。

不落库，仅返回候选列表，前端可一键 -> POST /worlds/{wid}/lore 创建。
"""
from __future__ import annotations

import json
import re
from typing import Optional

from sqlalchemy.orm import Session

from ...models import World, Entity, Event, NarrativeLog, WorldLore
from ...providers import get_provider
from ...providers.base import Message


SYSTEM_PROMPT = (
    "你是世界观编辑助手。读者读到一个不熟悉的专有名词时，会希望有 lore 条目解释它。"
    "你的任务是从给定的叙事素材中，挑出反复出现、读者可能困惑、但目前世界设定里没有解释的名词候选。"
    "只返回 JSON：{\"gaps\":[{\"name\":\"...\",\"kind\":\"person|location|organization|item|concept\","
    "\"mentions\":[\"原文片段1\",\"原文片段2\"],\"reason\":\"为什么需要 lore\","
    "\"suggested_summary\":\"50 字以内的初步解释建议\"}]}。"
    "已经在'已知名单'里的名词不要返回。"
    "至少出现 2 次或处于关键情节才值得加 lore。"
    "kind 必须是上述五种之一。最多 8 个候选。"
)


def _extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except Exception:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            pass
    return None


VALID_KINDS = {"person", "location", "organization", "item", "concept"}


def _gather_sources(
    db: Session, world: World, branch_id: str, max_events: int = 60, max_narrations: int = 30,
) -> tuple[list[Event], list[NarrativeLog]]:
    """取最近的事件和叙事段落作为扫描素材。"""
    events = (db.query(Event).filter_by(branch_id=branch_id, deleted=0)
              .order_by(Event.tick.desc()).limit(max_events).all())
    events = list(reversed(events))
    narrations = (db.query(NarrativeLog).filter_by(branch_id=branch_id)
                  .order_by(NarrativeLog.tick.desc()).limit(max_narrations).all())
    narrations = list(reversed(narrations))
    return events, narrations


def _build_user_prompt(
    known_names: list[str], events: list[Event], narrations: list[NarrativeLog],
) -> str:
    parts = ["【已知名单·这些不要返回】"]
    if known_names:
        parts.append("、".join(known_names[:200]))
    else:
        parts.append("（暂无）")

    parts.append("\n【叙事素材】")
    if events:
        parts.append("--事件--")
        for ev in events:
            line = f"t{ev.tick} {ev.title or ''}"
            if ev.description:
                line += f"：{ev.description[:200]}"
            parts.append(line)
    if narrations:
        parts.append("--叙事段落--")
        for n in narrations:
            txt = (n.text or "").strip()
            if not txt:
                continue
            parts.append(f"t{n.tick} {txt[:300]}")

    parts.append("\n请按 system 指示输出 JSON。")
    return "\n".join(parts)


def _validate_gap(raw: dict, known_lower: set[str]) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    name = (raw.get("name") or "").strip()
    if not name or len(name) > 60:
        return None
    if name.lower() in known_lower:
        return None
    kind = (raw.get("kind") or "").strip().lower()
    if kind not in VALID_KINDS:
        kind = "concept"
    mentions = raw.get("mentions") or []
    if not isinstance(mentions, list):
        mentions = []
    mentions = [str(m)[:200] for m in mentions[:5] if m]
    reason = (raw.get("reason") or "").strip()[:300]
    suggested = (raw.get("suggested_summary") or "").strip()[:500]
    return {
        "name": name[:60],
        "kind": kind,
        "mentions": mentions,
        "reason": reason,
        "suggested_summary": suggested,
    }


def scan_lore_gaps(
    db: Session, world: World,
    branch_id: Optional[str] = None,
    provider_key: Optional[str] = None,
    max_gaps: int = 8,
) -> dict:
    """返回 {gaps:[...], scanned:{events:N, narrations:N}, model:str}。

    not 落库；前端要创建时再 POST /worlds/{wid}/lore。
    """
    bid = branch_id or world.active_branch_id
    if not bid:
        return {"gaps": [], "scanned": {"events": 0, "narrations": 0}, "model": ""}

    events, narrations = _gather_sources(db, world, bid)
    if not events and not narrations:
        return {"gaps": [], "scanned": {"events": 0, "narrations": 0}, "model": ""}

    lores = db.query(WorldLore).filter_by(world_id=world.id).all()
    entities = db.query(Entity).filter_by(branch_id=bid).all()
    known = [l.title for l in lores] + [e.name for e in entities]
    known_lower = {n.lower() for n in known if n}

    user_prompt = _build_user_prompt(known, events, narrations)
    provider = get_provider(provider_key) if provider_key else get_provider()
    resp = provider.chat(
        system=SYSTEM_PROMPT,
        messages=[Message(role="user", content=user_prompt)],
        tools=[],
        max_tokens=1500,
        temperature=0.4,
    )
    content = getattr(resp, "text", None) or getattr(resp, "content", None) or str(resp)
    parsed = _extract_json(content) or {}
    raw_gaps = parsed.get("gaps") or []

    cap = max(1, min(int(max_gaps or 8), 20))
    out: list[dict] = []
    seen: set[str] = set()
    for raw in raw_gaps:
        norm = _validate_gap(raw, known_lower)
        if not norm:
            continue
        key = norm["name"].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(norm)
        if len(out) >= cap:
            break

    return {
        "gaps": out,
        "scanned": {"events": len(events), "narrations": len(narrations)},
        "model": getattr(resp, "model", "") or "",
    }
