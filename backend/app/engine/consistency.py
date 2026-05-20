"""一致性扫描引擎。

扫五类矛盾：
  personality - 角色性格冲突
  ability     - 角色能力冲突
  rule        - 世界规则违反
  timeline    - 时间线悖论
  relation    - 关系冲突

LLM 输出严格 JSON。提示词明确禁止回吐叙事原文片段。
"""
from __future__ import annotations
import json
import logging
import re
import uuid
from typing import Optional

from sqlalchemy.orm import Session

from ..models import (
    World, Branch, Entity, Event, NarrativeLog,
    ConsistencyIssue, ScanRun,
)
from ..providers import get_provider
from ..providers.base import Message
from .executor import active_branch_id

log = logging.getLogger(__name__)


CATEGORY_LABELS = {
    "personality": "性格冲突",
    "ability": "能力冲突",
    "rule": "规则违反",
    "timeline": "时间线悖论",
    "relation": "关系冲突",
    "other": "其它",
}

SEVERITIES = {"high", "medium", "low"}
CATEGORIES = set(CATEGORY_LABELS.keys())


SYSTEM_PROMPT = """你是叙事一致性审稿人，负责发现故事中的连贯性问题。

# 扫描的五类矛盾
1. personality（性格冲突）：同一角色前后行为/言谈风格出现明显矛盾，且无合理过渡
2. ability（能力冲突）：前文设定不会某能力，后文未经训练突然精通
3. rule（规则违反）：叙事踩了世界规则或禁忌列表
4. timeline（时间线悖论）：已死亡角色出场、不在场角色干预、年龄/身份与时间不符
5. relation（关系冲突）：角色关系剧烈反转却无情节铺垫

# 严格输出要求
* 只输出 JSON 对象，根字段为 issues 数组
* 每个 issue 字段：category（上述 5 类之一）、severity（high/medium/low）、title（≤20 字标签）、description（≤80 字，用你自己的话总结问题，绝不复述叙事原文片段）、suggestion（≤80 字，给作者的修复建议）、entity_ids（涉及实体 id 数组，可空）、tick_start、tick_end
* 没有发现问题就返回 {"issues": []}
* 严禁引用、复制、改写叙事原文的句子；只描述"什么不一致"

# 边界
* 风格变化、情节起伏、刻意伏笔不算矛盾
* 不要重复同一问题
* 一次最多列 10 个最重要的 issue
"""


def _entity_card(e: Entity) -> str:
    bits = [f"id={e.id}", f"name={e.name}", f"type={e.type}"]
    if e.alive == 0:
        bits.append("DEAD")
    if e.summary:
        bits.append(f"summary={e.summary[:120]}")
    if e.attributes:
        attr = ", ".join(f"{k}={v}" for k, v in list(e.attributes.items())[:8])
        bits.append(f"attrs={attr}")
    return " | ".join(bits)


def _event_line(ev: Event, name_lookup: dict[str, str]) -> str:
    parts = (ev.participants or [])[:6]
    names = [name_lookup.get(p, p[:8]) for p in parts]
    title = ev.title or ""
    desc = (ev.description or "")[:120]
    body = title if not desc else f"{title} - {desc}"
    return f"[t{ev.tick}] {body}（参与者：{', '.join(names) if names else '无'}）"


def _narration_line(n: NarrativeLog) -> str:
    text = (n.text or "").replace("\n", " ")
    if len(text) > 240:
        text = text[:240] + "…"
    return f"[t{n.tick}] {text}"


def _gather_context(
    db: Session, world: World, branch_id: str,
    tick_from: int, tick_to: int,
) -> dict:
    entities = db.query(Entity).filter_by(branch_id=branch_id).all()
    name_lookup = {e.id: e.name for e in entities}

    events = (
        db.query(Event)
        .filter_by(branch_id=branch_id, deleted=0)
        .filter(Event.tick >= tick_from, Event.tick <= tick_to)
        .order_by(Event.tick.asc(), Event.created_at.asc())
        .all()
    )
    narrations = (
        db.query(NarrativeLog)
        .filter_by(branch_id=branch_id)
        .filter(NarrativeLog.tick >= tick_from, NarrativeLog.tick <= tick_to)
        .order_by(NarrativeLog.tick.asc(), NarrativeLog.created_at.asc())
        .all()
    )
    involved_ids: set[str] = set()
    for ev in events:
        for p in (ev.participants or []):
            involved_ids.add(p)

    relevant_entities = [e for e in entities if e.id in involved_ids] or entities[:30]

    return {
        "entities": relevant_entities,
        "events": events,
        "narrations": narrations,
        "name_lookup": name_lookup,
        "all_entities": entities,
    }


def _build_user_prompt(world: World, ctx: dict, tick_from: int, tick_to: int) -> str:
    rules = world.rules or {}
    core = rules.get("core_rules") or []
    forbidden = rules.get("forbidden") or []

    lines: list[str] = []
    lines.append(f"# 世界：{world.name}")
    if rules.get("tone"):
        lines.append(f"基调：{rules['tone']}")
    if core:
        lines.append("\n## 核心规则")
        for r in core[:20]:
            lines.append(f"- {r}")
    if forbidden:
        lines.append("\n## 禁忌")
        for r in forbidden[:20]:
            lines.append(f"- {r}")

    lines.append(f"\n## 角色档案（扫描范围 t{tick_from}-t{tick_to}）")
    for e in ctx["entities"][:25]:
        lines.append(f"- {_entity_card(e)}")

    if ctx["events"]:
        lines.append("\n## 事件序列（按 tick 排序）")
        for ev in ctx["events"][:60]:
            lines.append(_event_line(ev, ctx["name_lookup"]))

    if ctx["narrations"]:
        lines.append("\n## 叙事日志（仅供参考，不得复述其原文）")
        for n in ctx["narrations"][:25]:
            lines.append(_narration_line(n))

    lines.append(
        "\n# 任务"
        "\n请按系统提示扫描以上内容，输出 JSON：{\"issues\": [...]}。"
        "\n务必：用你自己的话描述每个问题，禁止复述上面任何句子。"
    )
    return "\n".join(lines)


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


def _normalize_issue(raw: dict, valid_ids: set[str], tick_from: int, tick_to: int) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    cat = raw.get("category")
    if cat not in CATEGORIES:
        cat = "other"
    sev = raw.get("severity") or "medium"
    if sev not in SEVERITIES:
        sev = "medium"
    title = (raw.get("title") or "").strip()[:40]
    desc = (raw.get("description") or "").strip()[:240]
    sug = (raw.get("suggestion") or "").strip()[:240]
    if not desc:
        return None
    eids = raw.get("entity_ids") or []
    if not isinstance(eids, list):
        eids = []
    eids = [eid for eid in eids if isinstance(eid, str) and eid in valid_ids][:8]
    try:
        ts = int(raw.get("tick_start", tick_from))
        te = int(raw.get("tick_end", tick_to))
    except Exception:
        ts, te = tick_from, tick_to
    ts = max(tick_from, min(ts, tick_to))
    te = max(ts, min(te, tick_to))
    return {
        "category": cat, "severity": sev,
        "title": title or CATEGORY_LABELS.get(cat, "问题"),
        "description": desc, "suggestion": sug,
        "entity_ids": eids,
        "tick_start": ts, "tick_end": te,
    }


def run_scan(
    db: Session, world: World,
    scope: str = "recent",
    tick_from: Optional[int] = None,
    tick_to: Optional[int] = None,
    provider_key: Optional[str] = None,
) -> ScanRun:
    branch_id = active_branch_id(world)
    cur = world.current_tick or 0

    if scope == "all":
        tf, tt = 0, cur
    elif scope == "custom" and tick_from is not None and tick_to is not None:
        tf, tt = max(0, int(tick_from)), max(0, int(tick_to))
        if tf > tt:
            tf, tt = tt, tf
    else:
        tf, tt = max(0, cur - 20), cur

    run = ScanRun(
        id=f"scan_{uuid.uuid4().hex[:10]}",
        world_id=world.id, branch_id=branch_id,
        scope=scope, tick_from=tf, tick_to=tt,
        status="running",
    )
    db.add(run)
    db.commit()

    try:
        ctx = _gather_context(db, world, branch_id, tf, tt)
        if not ctx["events"] and not ctx["narrations"]:
            run.status = "completed"
            run.issue_count = 0
            db.commit()
            return run

        user_prompt = _build_user_prompt(world, ctx, tf, tt)
        provider = get_provider(provider_key) if provider_key else get_provider()
        resp = provider.chat(
            system=SYSTEM_PROMPT,
            messages=[Message(role="user", content=user_prompt)],
            tools=[],
            max_tokens=2000,
            temperature=0.2,
        )
        content = getattr(resp, "text", None) or getattr(resp, "content", None) or str(resp)

        parsed = _extract_json(content) or {}
        raw_issues = parsed.get("issues") or []
        valid_ids = {e.id for e in ctx["all_entities"]}

        created = 0
        for raw in raw_issues[:10]:
            norm = _normalize_issue(raw, valid_ids, tf, tt)
            if not norm:
                continue
            issue = ConsistencyIssue(
                id=f"iss_{uuid.uuid4().hex[:10]}",
                world_id=world.id, branch_id=branch_id,
                scan_id=run.id,
                **norm,
            )
            db.add(issue)
            created += 1

        run.issue_count = created
        run.status = "completed"
        db.commit()
    except Exception as e:
        log.exception("consistency scan failed")
        run.status = "failed"
        run.error = str(e)[:500]
        db.commit()

    return run
