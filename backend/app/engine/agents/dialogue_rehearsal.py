"""P2: 双角色对话演练。

让 LLM 模拟两个角色之间的一段对话，不写入主线，仅生成可参考/可采纳的稿件。
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Optional

from sqlalchemy.orm import Session

from ...models import World, Entity, NarrativeLog
from ...providers import get_provider
from ...providers.base import Message
from ..core.executor import active_branch_id

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是双人对话编剧，擅长在尊重角色档案的前提下写出有张力的对话。

# 你要写什么
两个指定角色之间的一段连续对话（用户给出 turn 数，请尽量贴近）。
不写旁白、不写场景描写、不替第三方说话。每一轮只是一句对白与可选的极短动作括注。

# 风格规则
- 严格按角色档案中的语气/口头禅/性格写。
- 不复读用户给的 scene 与 goal 原文。
- 节奏：开头切入主题，中段升温或反复，结尾给出一个明确的小落点（不是大反转）。
- 单 turn 文本 ≤120 字，整体对话 ≤2000 字。
- beat 字段（可空）：用 ≤6 字的中文标签描述这轮的功能，如"试探""正面冲突""退让""转移话题"。

# 输出（严格 JSON，不要 markdown 围栏）
{
  "title": "≤16字 对这段对话的极简概括",
  "turns": [
    {"speaker_id": "<两个 id 之一>", "text": "...", "beat": "..."},
    ...
  ],
  "summary": "≤80字 一句话总结这段对话发生了什么"
}"""


def _entity_card(e: Entity) -> str:
    parts = [f"id={e.id}", f"name={e.name}"]
    if e.summary:
        parts.append(f"summary={e.summary[:120]}")
    attrs = e.attributes or {}
    if attrs:
        kept = {k: v for k, v in list(attrs.items())[:6] if k not in {"_relations", "_emotion_curve"}}
        if kept:
            parts.append("attrs=" + json.dumps(kept, ensure_ascii=False))
    state = e.state or {}
    if state:
        s = {k: v for k, v in list(state.items())[:4]}
        if s:
            parts.append("state=" + json.dumps(s, ensure_ascii=False))
    return " | ".join(parts)


def _build_user_prompt(actor_a: Entity, actor_b: Entity,
                       scene: str, goal: str, turns: int) -> str:
    lines = [
        "## 角色 A",
        _entity_card(actor_a),
        "\n## 角色 B",
        _entity_card(actor_b),
        f"\n## 情境\n{scene.strip() or '（无指定情境，请你自行想象一个合理场合）'}",
    ]
    if goal.strip():
        lines.append(f"\n## 张力点 / 用户希望聚焦的话题\n{goal.strip()}")
    lines.append(
        f"\n## 任务\n请按 system 指示写一段约 {turns} 轮的对话。"
        f"严格使用上面给定的两个 speaker_id。"
        f"务必输出符合规范的 JSON。"
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
    s = text.find("{"); e = text.rfind("}")
    if s >= 0 and e > s:
        try:
            return json.loads(text[s:e + 1])
        except Exception:
            pass
    return None


def _normalize(parsed: dict, valid_ids: set[str], turns_hint: int) -> dict:
    title = (parsed.get("title") or "").strip()[:40]
    summary = (parsed.get("summary") or "").strip()[:160]
    raw_turns = parsed.get("turns") or []
    if not isinstance(raw_turns, list):
        raw_turns = []
    out: list[dict] = []
    cap = max(2, min(turns_hint * 2, 40))
    for raw in raw_turns[:cap]:
        if not isinstance(raw, dict):
            continue
        sid = raw.get("speaker_id")
        text = (raw.get("text") or "").strip()
        if sid not in valid_ids or not text:
            continue
        beat = (raw.get("beat") or "").strip()[:12]
        out.append({"speaker_id": sid, "text": text[:240], "beat": beat})
    return {"title": title, "turns": out, "summary": summary}


def rehearse_dialogue(
    db: Session, world: World,
    actor_a_id: str, actor_b_id: str,
    scene: str = "", goal: str = "", turns: int = 12,
    provider_key: Optional[str] = None,
) -> dict:
    if actor_a_id == actor_b_id:
        raise ValueError("两个角色必须不同")
    branch_id = active_branch_id(world)
    if not branch_id:
        raise ValueError("世界没有激活分支")

    a = db.query(Entity).filter_by(id=actor_a_id, branch_id=branch_id).first()
    b = db.query(Entity).filter_by(id=actor_b_id, branch_id=branch_id).first()
    if not a or not b:
        raise ValueError("找不到指定角色（可能不在当前分支）")

    turns = max(3, min(int(turns or 12), 20))
    prompt = _build_user_prompt(a, b, scene, goal, turns)

    provider = get_provider(provider_key) if provider_key else get_provider()
    resp = provider.chat(
        system=SYSTEM_PROMPT,
        messages=[Message(role="user", content=prompt)],
        tools=[],
        max_tokens=2000,
        temperature=0.9,
    )
    text = getattr(resp, "text", None) or getattr(resp, "content", None) or str(resp)
    parsed = _extract_json(text) or {}
    valid = {a.id, b.id}
    payload = _normalize(parsed, valid, turns)

    return {
        "actors": [
            {"id": a.id, "name": a.name},
            {"id": b.id, "name": b.name},
        ],
        "scene": scene.strip(),
        "goal": goal.strip(),
        **payload,
        "raw_text": text if not payload["turns"] else "",  # 解析失败时给原文便于排查
    }


def render_dialogue_text(payload: dict, name_lookup: dict[str, str]) -> str:
    """把 turns 渲染为可读文本（用于落库到 NarrativeLog.text）。"""
    lines: list[str] = []
    if payload.get("title"):
        lines.append(f"【对话演练 · {payload['title']}】")
    for t in payload.get("turns", []):
        name = name_lookup.get(t["speaker_id"], "?")
        beat = f" ({t['beat']})" if t.get("beat") else ""
        lines.append(f"**{name}**{beat}：{t['text']}")
    if payload.get("summary"):
        lines.append("")
        lines.append(f"_小结：{payload['summary']}_")
    return "\n".join(lines)


def save_dialogue_as_narration(
    db: Session, world: World, payload: dict,
) -> NarrativeLog:
    branch_id = active_branch_id(world)
    if not branch_id:
        raise ValueError("世界没有激活分支")
    name_lookup: dict[str, str] = {}
    for actor in (payload.get("actors") or []):
        if isinstance(actor, dict) and actor.get("id"):
            name_lookup[actor["id"]] = actor.get("name") or actor["id"]
    text = render_dialogue_text(payload, name_lookup)
    if not text.strip():
        raise ValueError("空对话不能保存")
    log_row = NarrativeLog(
        id=f"nl_{uuid.uuid4().hex[:10]}",
        branch_id=branch_id,
        tick=world.current_tick or 0,
        role="dialogue_rehearsal",
        text=text,
        revision_index=0,
    )
    db.add(log_row)
    db.commit()
    return log_row
