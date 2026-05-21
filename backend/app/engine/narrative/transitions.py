"""C3: 给 storyboard 中相邻两章衔接处打分并生成过渡桥句。

调用方式：前端从 storyboard 拿到章节列表后，按需 POST 任意两章 index 触发评估。
不落库——只是 ad-hoc 工具。
"""
from __future__ import annotations

import json
import re
from typing import Optional

from sqlalchemy.orm import Session

from ...models import (
    World, ChapterMarker, Event, NarrativeLog,
)
from ...providers import get_provider
from ...providers.base import Message


SYSTEM_PROMPT = (
    "你是结构编辑。读者读完前一章末尾、再翻到下一章开头时，应该感到衔接自然——"
    "无突兀跳跃、无遗失的因果、节奏过渡合适。"
    "你的任务是评估这两段衔接，并写一句可放在两章之间的过渡桥句（可选）。"
    "只返回 JSON：{\"score\":0-100,\"issues\":[\"...\"],\"suggested_bridge\":\"...\"}。"
    "score 是衔接流畅度，越高越好；issues 列出具体衔接问题（角色突然消失、时间跳跃缺交代、情绪基调断裂等），"
    "找不到问题就返回空数组；suggested_bridge 可空字符串，"
    "建议时控制在 50 字内、与前后语气贴合。"
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


def _build_intervals(db: Session, world: World, branch_id: str) -> list[dict]:
    """复刻 storyboard 的章节切分（仅返回 id/title/tick_start/tick_end/index）。"""
    markers = (db.query(ChapterMarker).filter_by(branch_id=branch_id)
               .order_by(ChapterMarker.tick).all())
    events = db.query(Event).filter_by(branch_id=branch_id, deleted=0).order_by(Event.tick).all()

    max_tick = max(
        [world.max_tick or 0, world.current_tick or 0]
        + [e.tick for e in events] + [m.tick for m in markers],
        default=0,
    )

    intervals: list[dict] = []
    if not markers:
        intervals.append({
            "id": "_unmarked", "title": "（未分章）",
            "tick_start": 0, "tick_end": max_tick, "is_synthetic": True,
        })
    else:
        if markers[0].tick > 0:
            prologue_events = [e for e in events if e.tick < markers[0].tick]
            if prologue_events:
                intervals.append({
                    "id": "_prologue", "title": "（序章）",
                    "tick_start": 0, "tick_end": markers[0].tick - 1, "is_synthetic": True,
                })
        for i, m in enumerate(markers):
            ts = m.tick
            te = markers[i + 1].tick - 1 if i + 1 < len(markers) else max(max_tick, m.tick)
            intervals.append({
                "id": m.id, "title": m.title or f"第{i+1}章",
                "tick_start": ts, "tick_end": te, "is_synthetic": False,
            })
    for idx, ch in enumerate(intervals):
        ch["index"] = idx
    return intervals


def _slice_text(
    db: Session, branch_id: str, tick_start: int, tick_end: int,
    events_limit: int = 5, narrations_limit: int = 3, from_end: bool = True,
) -> dict:
    """取某章范围内的事件 + 叙事段落。from_end=True 取末尾若干，否则取开头。"""
    evs = (db.query(Event)
           .filter(Event.branch_id == branch_id, Event.deleted == 0,
                   Event.tick >= tick_start, Event.tick <= tick_end)
           .order_by(Event.tick).all())
    nars = (db.query(NarrativeLog)
            .filter(NarrativeLog.branch_id == branch_id,
                    NarrativeLog.tick >= tick_start, NarrativeLog.tick <= tick_end)
            .order_by(NarrativeLog.tick).all())
    if from_end:
        evs = evs[-events_limit:]
        nars = nars[-narrations_limit:]
    else:
        evs = evs[:events_limit]
        nars = nars[:narrations_limit]
    return {
        "events": [{"tick": e.tick, "title": e.title or "", "description": (e.description or "")[:200]} for e in evs],
        "narrations": [{"tick": n.tick, "text": (n.text or "")[:300]} for n in nars],
    }


def _format_block(label: str, chap: dict, slc: dict) -> str:
    lines = [f"【{label}：{chap['title']} (t{chap['tick_start']}–t{chap['tick_end']})】"]
    if slc["events"]:
        lines.append("--事件--")
        for e in slc["events"]:
            line = f"t{e['tick']} {e['title']}"
            if e["description"]:
                line += f"：{e['description']}"
            lines.append(line)
    if slc["narrations"]:
        lines.append("--叙事--")
        for n in slc["narrations"]:
            lines.append(f"t{n['tick']} {n['text']}")
    if not slc["events"] and not slc["narrations"]:
        lines.append("（空白章节）")
    return "\n".join(lines)


def evaluate_transition(
    db: Session, world: World, from_index: int, to_index: int,
    branch_id: Optional[str] = None,
    provider_key: Optional[str] = None,
) -> dict:
    bid = branch_id or world.active_branch_id
    if not bid:
        raise ValueError("no active branch")

    intervals = _build_intervals(db, world, bid)
    if from_index < 0 or to_index < 0 or from_index >= len(intervals) or to_index >= len(intervals):
        raise ValueError(f"chapter index out of range (have {len(intervals)} chapters)")
    if to_index <= from_index:
        raise ValueError("to_index must be greater than from_index")

    a = intervals[from_index]
    b = intervals[to_index]
    tail = _slice_text(db, bid, a["tick_start"], a["tick_end"], from_end=True)
    head = _slice_text(db, bid, b["tick_start"], b["tick_end"], from_end=False)

    if not (tail["events"] or tail["narrations"]) and not (head["events"] or head["narrations"]):
        return {
            "from_index": from_index, "to_index": to_index,
            "from_chapter": {"id": a["id"], "title": a["title"]},
            "to_chapter": {"id": b["id"], "title": b["title"]},
            "score": None, "issues": ["两章均无内容，无法评估"],
            "suggested_bridge": "", "model": "", "skipped": True,
        }

    user_prompt = (
        _format_block("前章末尾", a, tail) + "\n\n"
        + _format_block("下章开头", b, head) + "\n\n请按 system 指示输出 JSON。"
    )
    provider = get_provider(provider_key) if provider_key else get_provider()
    resp = provider.chat(
        system=SYSTEM_PROMPT,
        messages=[Message(role="user", content=user_prompt)],
        tools=[],
        max_tokens=800,
        temperature=0.3,
    )
    content = getattr(resp, "text", None) or getattr(resp, "content", None) or str(resp)
    parsed = _extract_json(content) or {}

    score_raw = parsed.get("score")
    try:
        score = max(0, min(100, int(score_raw)))
    except (TypeError, ValueError):
        score = None
    issues = parsed.get("issues") or []
    if not isinstance(issues, list):
        issues = []
    issues = [str(x)[:300] for x in issues[:8] if x]
    bridge = (parsed.get("suggested_bridge") or "").strip()[:300]

    return {
        "from_index": from_index, "to_index": to_index,
        "from_chapter": {"id": a["id"], "title": a["title"],
                         "tick_start": a["tick_start"], "tick_end": a["tick_end"]},
        "to_chapter": {"id": b["id"], "title": b["title"],
                       "tick_start": b["tick_start"], "tick_end": b["tick_end"]},
        "score": score,
        "issues": issues,
        "suggested_bridge": bridge,
        "model": getattr(resp, "model", "") or "",
        "skipped": False,
    }
