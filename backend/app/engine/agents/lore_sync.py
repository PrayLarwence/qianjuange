"""Post-step lore extraction: scan Director output for implicit world-building facts.

This is a safety net. The primary mechanism is the Director's `add_lore` tool —
it should explicitly register new world rules during simulation. This module catches
settings that the Director established through events/narration but forgot to register.

Design:
- Runs after Director phase, before Author phase
- Scans new events and narration from the current step
- Asks LLM to identify implicit world-building facts not yet in the lore DB
- Auto-creates lore entries (low priority, not pinned) for review
- Lightweight: single LLM call, small token budget, fail-safe (never blocks pipeline)
"""
from __future__ import annotations
import json
import logging
import re
from typing import Optional

from sqlalchemy.orm import Session

from ...models import World, Entity, Event, NarrativeLog, WorldLore
from ...providers.base import LLMProvider, Message

log = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "你是世界观编辑。从给定的本轮推演产出中，提取隐含的、具有持久约束力的世界设定。"
    "只提取**规则性**事实（魔法体系、地理约束、社会制度、种族特性、物理法则等），"
    "不要提取一次性事件、角色动作、或已经在'已有设定'里的内容。"
    "返回 JSON：{\"lore\":[{\"title\":\"...\",\"content\":\"...\",\"category\":\"setting|magic|taboo|culture|geography|faction|other\"}]}"
    "如果没有新设定需要提取，返回 {\"lore\":[]}。最多 3 条。"
)


def extract_lore_from_step(
    db: Session,
    world: World,
    branch_id: str,
    tick: int,
    llm: LLMProvider,
) -> list[dict]:
    """Scan this step's output and extract implicit lore. Returns list of created entries."""
    events = (
        db.query(Event)
        .filter_by(branch_id=branch_id, deleted=0)
        .filter(Event.tick == tick)
        .all()
    )
    narrations = (
        db.query(NarrativeLog)
        .filter(
            NarrativeLog.branch_id == branch_id,
            NarrativeLog.tick == tick,
            NarrativeLog.role.in_(["narrator", "director_draft"]),
        )
        .all()
    )

    if not events and not narrations:
        return []

    existing_lore = db.query(WorldLore).filter_by(world_id=world.id).all()
    existing_titles = {l.title.lower() for l in existing_lore if l.title}
    existing_content_snippets = " ".join(
        (l.content or "")[:100] for l in existing_lore
    )

    source_parts = []
    for ev in events:
        source_parts.append(f"[事件] {ev.title}: {ev.description or ''}")
    for n in narrations:
        text = (n.text or "").strip()
        if text:
            source_parts.append(f"[叙事] {text[:500]}")

    source_text = "\n".join(source_parts)
    if len(source_text) < 50:
        return []

    existing_block = "\n".join(l.title for l in existing_lore) if existing_lore else "（暂无）"

    user_prompt = (
        f"# 已有设定（不要重复）\n{existing_block}\n\n"
        f"# 本轮推演产出\n{source_text}\n\n"
        "请提取隐含的新世界设定（规则性事实），返回 JSON。"
    )

    try:
        resp = llm.chat(
            system=SYSTEM_PROMPT,
            messages=[Message(role="user", content=user_prompt)],
            tools=[],
            max_tokens=800,
            temperature=0.2,
        )
        text = (resp.text or "").strip()
        parsed = _extract_json(text)
        if not parsed:
            return []

        items = parsed.get("lore") or []
        if not isinstance(items, list):
            return []

        created = []
        for item in items[:3]:
            if not isinstance(item, dict):
                continue
            title = (item.get("title") or "").strip()
            content = (item.get("content") or "").strip()
            if not title or not content:
                continue
            if title.lower() in existing_titles:
                continue

            category = (item.get("category") or "setting").strip().lower()
            valid_cats = {"setting", "magic", "taboo", "culture", "geography", "faction", "other"}
            if category not in valid_cats:
                category = "setting"

            import uuid
            row = WorldLore(
                id=f"lore_{uuid.uuid4().hex[:10]}",
                world_id=world.id,
                category=category,
                title=title[:200],
                content=content[:8000],
                priority=-1,  # low priority — auto-extracted, user can promote
                pinned=0,
            )
            db.add(row)
            existing_titles.add(title.lower())
            created.append({"id": row.id, "title": title, "category": category})

        if created:
            db.commit()
        return created

    except Exception as e:
        log.warning("lore extraction failed (non-fatal): %s", e)
        return []


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
