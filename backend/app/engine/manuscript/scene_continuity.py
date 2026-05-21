"""B8: 场景连续性扫描。

不同于 consistency.py 关注角色性格/能力/规则违反，本扫描专门看
"场景元素"在相邻段落间是否衔接：位置、在场角色、时间/天气、物品状态。

复用 ConsistencyIssue 表，category 设为 "continuity"。
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from sqlalchemy.orm import Session

from ...models import World, Entity, Event, NarrativeLog, ConsistencyIssue, ScanRun
from ...providers import get_provider
from ...providers.base import Message
from ..core.executor import active_branch_id
from ..consistency.consistency import _extract_json, _normalize_issue

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是场景调度师，专门审查叙事中"场景连续性"的断裂。

# 你只关心这四类
1. location（位置）：上一段在 A，下一段在 B 但没交代如何到达 / 缺转场
2. presence（在场角色）：某角色未出现下场描写就消失，或未交代抵达就突然出现
3. time_weather（时间/天气）：白天 → 夜晚、晴 → 雨等基调切换缺过渡
4. item_state（物品状态）：手中物突然消失、伤口愈合却无说明

不属于这四类的（性格冲突/能力冲突/世界规则）请忽略——其它扫描器会处理。

# 严格度
- 只标"明显且无解释"的断裂。文学常用的省略（一笔带过的旅途）不算。
- 同一断裂只报一次。
- 找不到问题就返回 {"issues": []}。

# 输出格式
严格 JSON，不要解释、不要 markdown 围栏：
{
  "issues": [
    {
      "kind": "location|presence|time_weather|item_state",
      "title": "≤20字摘要",
      "description": "≤120字说明断裂在何处（用你自己的话）",
      "suggestion": "≤80字 一句修复建议（如何补一句过渡）",
      "tick_start": <int 起始 tick>,
      "tick_end": <int 结束 tick>,
      "entity_ids": ["可选：相关角色 id"]
    }
  ]
}"""


KIND_TO_TITLE_PREFIX = {
    "location": "位置跳跃",
    "presence": "在场断裂",
    "time_weather": "时间/天气跳跃",
    "item_state": "物品状态断裂",
}


def _gather(db: Session, branch_id: str, tick_from: int, tick_to: int) -> dict:
    entities = db.query(Entity).filter_by(branch_id=branch_id).all()
    name_lookup = {e.id: e.name for e in entities}
    events = (db.query(Event)
              .filter(Event.branch_id == branch_id, Event.deleted == 0,
                      Event.tick >= tick_from, Event.tick <= tick_to)
              .order_by(Event.tick).all())
    nars = (db.query(NarrativeLog)
            .filter(NarrativeLog.branch_id == branch_id,
                    NarrativeLog.tick >= tick_from, NarrativeLog.tick <= tick_to)
            .order_by(NarrativeLog.tick).all())
    return {"entities": entities, "events": events, "narrations": nars,
            "name_lookup": name_lookup}


def _build_prompt(world: World, ctx: dict, tick_from: int, tick_to: int) -> str:
    name_lookup = ctx["name_lookup"]
    lines = [f"# 世界：{world.name}",
             f"扫描范围：t{tick_from}–t{tick_to}\n"]
    if ctx["entities"]:
        lines.append("## 角色名单（id → 名字，引用时用 id）")
        for e in ctx["entities"][:30]:
            lines.append(f"- {e.id}: {e.name}")

    if ctx["events"]:
        lines.append("\n## 事件序列")
        for ev in ctx["events"][:60]:
            parts = [name_lookup.get(p, p) for p in (ev.participants or [])]
            head = f"[t{ev.tick}] {ev.title or ''}".strip()
            if parts:
                head += f"（在场：{', '.join(parts)}）"
            desc = (ev.description or "")[:200]
            if desc:
                head += f"：{desc}"
            lines.append(head)

    if ctx["narrations"]:
        lines.append("\n## 叙事段（仅供检查衔接，不得复述原文）")
        for n in ctx["narrations"][:25]:
            text = (n.text or "")[:240]
            lines.append(f"[t{n.tick}] {text}")

    lines.append(
        "\n# 任务\n"
        "找上面相邻段落间的『场景连续性』断裂（仅 location/presence/time_weather/item_state 四类）。"
        "用你自己的话写问题描述与修复建议，禁止照搬原文。"
        "按 system 指示输出 JSON。"
    )
    return "\n".join(lines)


def _normalize_scene_issue(raw: dict, valid_ids: set[str], tick_from: int, tick_to: int) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    kind = raw.get("kind")
    if kind not in KIND_TO_TITLE_PREFIX:
        return None
    title = (raw.get("title") or "").strip()[:40] or KIND_TO_TITLE_PREFIX[kind]
    desc = (raw.get("description") or "").strip()[:240]
    if not desc:
        return None
    sug = (raw.get("suggestion") or "").strip()[:240]
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
        "category": "continuity",
        "severity": "low" if kind in {"item_state", "time_weather"} else "medium",
        "title": f"[{KIND_TO_TITLE_PREFIX[kind]}] {title}" if not title.startswith("[") else title,
        "description": desc,
        "suggestion": sug,
        "entity_ids": eids,
        "tick_start": ts,
        "tick_end": te,
    }


def run_scene_scan(
    db: Session, world: World,
    tick_from: Optional[int] = None,
    tick_to: Optional[int] = None,
    scope: str = "recent",
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
        tf, tt = max(0, cur - 15), cur

    run = ScanRun(
        id=f"scene_{uuid.uuid4().hex[:10]}",
        world_id=world.id, branch_id=branch_id,
        scope=f"scene:{scope}", tick_from=tf, tick_to=tt,
        status="running",
    )
    db.add(run)
    db.commit()

    if not branch_id:
        run.status = "completed"
        run.issue_count = 0
        db.commit()
        return run

    try:
        ctx = _gather(db, branch_id, tf, tt)
        if not ctx["events"] and not ctx["narrations"]:
            run.status = "completed"
            run.issue_count = 0
            db.commit()
            return run

        prompt = _build_prompt(world, ctx, tf, tt)
        provider = get_provider(provider_key) if provider_key else get_provider()
        resp = provider.chat(
            system=SYSTEM_PROMPT,
            messages=[Message(role="user", content=prompt)],
            tools=[],
            max_tokens=2000,
            temperature=0.2,
        )
        content = getattr(resp, "text", None) or getattr(resp, "content", None) or str(resp)
        parsed = _extract_json(content) or {}
        raw_issues = parsed.get("issues") or []
        valid_ids = {e.id for e in ctx["entities"]}

        created = 0
        for raw in raw_issues[:10]:
            norm = _normalize_scene_issue(raw, valid_ids, tf, tt)
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
        log.exception("scene continuity scan failed")
        run.status = "failed"
        run.error = str(e)[:500]
        db.commit()

    return run
