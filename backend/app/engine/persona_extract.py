"""Reverse-engineer an entity's persona from the events they've participated in.

Given a character, we collect every event where they appear (across the active
branch by default), feed it to the LLM, and ask: "based on what this person has
actually done and said, what drives them, how do they speak, what do they not see?"

The output is a structured dict matching the persona schema:

  {
    "drives":     [str, ...],   # 1-4 short motivations
    "voice":      str,          # one-line speech style
    "blindspots": [str, ...],   # 0-3 things they tend to ignore or misread
    "knowledge_of": [str, ...], # entity ids/names they know about
    "rationale":  str,          # one paragraph explaining the inference
  }

The endpoint returns the suggestion without writing it. The user reviews in
the UI and decides whether to accept (PATCH /entities/{id}).
"""
from __future__ import annotations
import json
import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import Entity, Event, Branch, World
from ..providers import LLMProvider, Message, get_provider

log = logging.getLogger(__name__)

MAX_EVENTS = 60   # cap context length
MAX_TOKENS = 1200


SYSTEM_PROMPT = """你是一位心理画像分析师。我会给你一个角色在故事里实际做过、说过的事，请反推他的 persona。

输出必须是 JSON 对象，包含以下字段（不要加任何解释或 markdown 代码块）：

{
  "drives":     ["驱动1", "驱动2"],         // 1-4 条；他真正在追求什么
  "voice":      "一句话描述他的说话风格",     // 例：谨慎多疑，用词简短直接
  "blindspots": ["盲区1"],                  // 0-3 条；他容易忽略或误判什么
  "knowledge_of": ["他显然认识的角色名"],    // 0-N 条；从事件交互推断
  "rationale":  "一段不超过 80 字的中文，说明你为什么这么判断（基于哪些事件）"
}

规则：
- 只能基于给定事件做推断。事件没体现的东西，不要写。
- 如果事件不足以判断某项（比如只有 1-2 件事），把对应字段留空数组或空字符串，宁可少写不要编。
- voice 写"语气特点"，不是台词内容。
- drives 写持续的动机（保护亲人、向上爬、复仇），不是当下要做的具体任务。
"""


def extract_persona(
    db: Session,
    entity_id: str,
    *,
    branch_id: Optional[str] = None,
    provider: Optional[LLMProvider] = None,
) -> dict[str, Any]:
    """Return a suggested persona dict (does NOT save to DB)."""
    entity = db.query(Entity).filter_by(id=entity_id).first()
    if not entity:
        raise ValueError(f"entity {entity_id} not found")
    bid = branch_id or entity.branch_id

    # collect events that involve this entity
    events = (db.query(Event)
                .filter_by(branch_id=bid, deleted=0)
                .order_by(Event.tick, Event.created_at).all())
    relevant = [e for e in events
                if entity_id in (e.participants or [])
                or entity_id == e.location_id]
    if len(relevant) < 2:
        return {
            "ok": False,
            "reason": "事件太少（至少需要 2 条参与事件）",
            "event_count": len(relevant),
        }
    relevant = relevant[-MAX_EVENTS:]

    # gather names of the other entities involved (so the LLM can cite them)
    other_ids = set()
    for ev in relevant:
        for pid in (ev.participants or []):
            if pid != entity_id:
                other_ids.add(pid)
    others = {e.id: e.name for e in db.query(Entity).filter(Entity.id.in_(other_ids)).all()} if other_ids else {}

    user_prompt = _build_prompt(entity, relevant, others)

    llm = provider
    if llm is None:
        try:
            llm = get_provider()
        except Exception as e:
            return {"ok": False, "reason": f"LLM unavailable: {e}", "event_count": len(relevant)}

    try:
        resp = llm.chat(
            system=SYSTEM_PROMPT,
            messages=[Message(role="user", content=user_prompt)],
            tools=[],
            max_tokens=MAX_TOKENS,
            temperature=0.4,
        )
    except Exception as e:
        log.exception("persona extract llm call failed")
        return {"ok": False, "reason": f"LLM 调用失败: {e}", "event_count": len(relevant)}

    text = (resp.text or "").strip()
    parsed = _parse_json_object(text)
    if not parsed:
        return {
            "ok": False,
            "reason": "无法解析 LLM 输出为 JSON",
            "raw": text[:500],
            "event_count": len(relevant),
        }

    # normalize fields
    suggestion = {
        "drives":       _as_str_list(parsed.get("drives"), max_n=4),
        "voice":        str(parsed.get("voice") or "").strip(),
        "blindspots":   _as_str_list(parsed.get("blindspots"), max_n=3),
        "knowledge_of": _as_str_list(parsed.get("knowledge_of"), max_n=20),
        "rationale":    str(parsed.get("rationale") or "").strip(),
    }
    # try to map knowledge_of names back to entity ids when possible
    name_to_id = {v: k for k, v in others.items()}
    suggestion["knowledge_of_resolved"] = [
        {"name": n, "id": name_to_id.get(n)} for n in suggestion["knowledge_of"]
    ]

    return {
        "ok": True,
        "event_count": len(relevant),
        "current_persona": entity.persona or {},
        "suggestion": suggestion,
    }


def _build_prompt(entity: Entity, events: list[Event],
                  others: dict[str, str]) -> str:
    parts = [
        f"## 目标角色：{entity.name}",
    ]
    if entity.summary:
        parts.append(f"简介：{entity.summary}")
    if entity.persona:
        cur = entity.persona
        parts.append("当前已填的 persona（仅供参考，请基于事件重新独立判断，不要照抄）：")
        parts.append(json.dumps(cur, ensure_ascii=False, indent=2))

    parts.append(f"\n## 他参与过的事件（共 {len(events)} 条，按时间）")
    for ev in events:
        line = f"- t={ev.tick} 《{ev.title}》"
        if ev.description:
            line += f"：{ev.description}"
        co_actors = [others[p] for p in (ev.participants or [])
                     if p != entity.id and p in others]
        if co_actors:
            line += f"  [同场：{', '.join(co_actors)}]"
        if ev.consequences:
            line += f"  [后果：{'; '.join(ev.consequences)}]"
        parts.append(line)

    parts.append("\n现在，请输出 JSON。只输出 JSON 对象本身，不要 ```json``` 包裹，不要任何解释。")
    return "\n".join(parts)


def _parse_json_object(text: str) -> Optional[dict]:
    """Pull the first JSON object out of `text`, tolerant to fences."""
    if not text:
        return None
    # strip ```json ... ``` if present
    s = text.strip()
    if s.startswith("```"):
        s = s.lstrip("`")
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip().rstrip("`").strip()
    # find first { ... } that parses
    start = s.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(s)):
            if s[i] == "{": depth += 1
            elif s[i] == "}":
                depth -= 1
                if depth == 0:
                    candidate = s[start:i+1]
                    try:
                        return json.loads(candidate)
                    except Exception:
                        break
        start = s.find("{", start + 1)
    return None


def _as_str_list(v: Any, max_n: int) -> list[str]:
    if not v: return []
    if isinstance(v, str):
        v = [x.strip() for x in v.split(",") if x.strip()]
    if not isinstance(v, list): return []
    out = []
    for item in v:
        s = str(item).strip()
        if s and s not in out:
            out.append(s)
        if len(out) >= max_n:
            break
    return out
