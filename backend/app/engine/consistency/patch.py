"""A 收尾：editor 针对 ConsistencyIssue 输出可应用的具体 patch 建议。"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from ...models import (
    World, Event, NarrativeLog, ConsistencyIssue, IssuePatch,
)
from ...providers import get_provider
from ...providers.base import Message


SYSTEM_PROMPT = """你是叙事改稿编辑。给定一个一致性问题（issue）和涉及的原文片段，
请输出 1-3 个具体的、可一键应用的"文字 patch"。

要求：
1. 每个 patch 必须能精确定位到一段已存在的原文。优先在 narration（叙事段落）上动刀；
2. before_excerpt 必须是原文里**逐字出现**的连续片段，长度 5-100 字，足够用于定位但不要整段；
3. after_text 是替换 before_excerpt 后的新文字，应当解决 issue 指出的问题；
4. rationale 用一句话解释这个改动为何能解决 issue。不要复述 issue 本身。
5. 不要输出与原文完全一致的 after_text；不要输出空 patch。

输出 JSON（不带 markdown 代码块）：
{
  "patches": [
    {
      "target_kind": "narration" | "event_title" | "event_description",
      "target_id": "n_xxx 或 ev_xxx",
      "before_excerpt": "原文片段",
      "after_text": "改后文字",
      "rationale": "一句话解释"
    }
  ]
}"""


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


def _gather_targets(db: Session, issue: ConsistencyIssue) -> tuple[list[NarrativeLog], list[Event]]:
    """收集 issue 涉及的 tick 范围内的可改写候选。"""
    if not issue.branch_id:
        return [], []
    tf = max(0, (issue.tick_start or 0) - 1)
    tt = (issue.tick_end or issue.tick_start or 0) + 1
    narrations = (
        db.query(NarrativeLog)
        .filter(NarrativeLog.branch_id == issue.branch_id)
        .filter(NarrativeLog.tick >= tf, NarrativeLog.tick <= tt)
        .filter(NarrativeLog.role.in_(["narrator", "author", None]))
        .order_by(NarrativeLog.tick)
        .all()
    )
    events = (
        db.query(Event)
        .filter(Event.branch_id == issue.branch_id, Event.deleted == 0)
        .filter(Event.tick >= tf, Event.tick <= tt)
        .order_by(Event.tick)
        .all()
    )
    return narrations, events


def _build_user_prompt(issue: ConsistencyIssue, narrations: list[NarrativeLog], events: list[Event]) -> str:
    lines = [
        f"# 一致性问题",
        f"类别: {issue.category} · 严重度: {issue.severity}",
        f"标题: {issue.title}",
        f"描述: {issue.description}",
    ]
    if issue.suggestion:
        lines.append(f"原 suggestion: {issue.suggestion}")
    lines.append(f"涉及 tick: {issue.tick_start} ~ {issue.tick_end}")

    lines.append("\n# 可改写的候选原文")
    if events:
        lines.append("## 事件 (event)")
        for ev in events[:6]:
            lines.append(f"- id={ev.id} tick={ev.tick} title={ev.title!r}")
            if ev.description:
                lines.append(f"  description: {ev.description[:300]}")
    if narrations:
        lines.append("## 叙事段落 (narration) — 优先在这里动刀")
        for n in narrations[:8]:
            text = (n.text or "").strip()
            if text:
                lines.append(f"- id={n.id} tick={n.tick}: {text[:500]}")
    if not events and not narrations:
        lines.append("（候选为空——无法生成 patch）")
    lines.append("\n请输出 JSON，1-3 个 patch。")
    return "\n".join(lines)


def _validate_patch(raw: dict, narr_ids: set[str], ev_ids: set[str], texts: dict[str, str]) -> Optional[dict]:
    """校验 LLM 输出的单个 patch：target 存在 + before_excerpt 能在 target 文本中找到。"""
    if not isinstance(raw, dict):
        return None
    kind = (raw.get("target_kind") or "").strip()
    tid = (raw.get("target_id") or "").strip()
    before = (raw.get("before_excerpt") or "").strip()
    after = (raw.get("after_text") or "").strip()
    rationale = (raw.get("rationale") or "").strip()
    if kind not in ("narration", "event_title", "event_description"):
        return None
    if not tid or not after or after == before:
        return None
    if kind == "narration" and tid not in narr_ids:
        return None
    if kind in ("event_title", "event_description") and tid not in ev_ids:
        return None
    target_text = texts.get(f"{kind}:{tid}", "")
    if before and before not in target_text:
        return None
    return {
        "target_kind": kind, "target_id": tid,
        "before_excerpt": before, "after_text": after,
        "rationale": rationale,
    }


def suggest_patches_for_issue(
    db: Session, world: World, issue: ConsistencyIssue,
    provider_key: Optional[str] = None,
    max_patches: int = 3,
) -> list[IssuePatch]:
    narrations, events = _gather_targets(db, issue)
    if not narrations and not events:
        return []

    narr_ids = {n.id for n in narrations}
    ev_ids = {e.id for e in events}
    texts: dict[str, str] = {}
    for n in narrations:
        texts[f"narration:{n.id}"] = n.text or ""
    for e in events:
        texts[f"event_title:{e.id}"] = e.title or ""
        texts[f"event_description:{e.id}"] = e.description or ""

    user_prompt = _build_user_prompt(issue, narrations, events)
    provider = get_provider(provider_key) if provider_key else get_provider()
    resp = provider.chat(
        system=SYSTEM_PROMPT,
        messages=[Message(role="user", content=user_prompt)],
        tools=[],
        max_tokens=1500,
        temperature=0.3,
    )
    content = getattr(resp, "text", None) or getattr(resp, "content", None) or str(resp)
    parsed = _extract_json(content) or {}
    raw_patches = parsed.get("patches") or []

    created: list[IssuePatch] = []
    model_used = getattr(resp, "model", "") or ""
    for raw in raw_patches[: max(1, min(max_patches, 5))]:
        norm = _validate_patch(raw, narr_ids, ev_ids, texts)
        if not norm:
            continue
        patch = IssuePatch(
            id=f"pch_{uuid.uuid4().hex[:10]}",
            issue_id=issue.id,
            model_used=model_used,
            **norm,
        )
        db.add(patch)
        created.append(patch)
    db.commit()
    return created


def apply_patch(db: Session, patch: IssuePatch) -> tuple[bool, str]:
    """把 patch 应用到 target 上。返回 (ok, message)。

    apply 前会把目标字段的当前值整段存到 patch.original_snapshot，便于 undo 还原。
    多个 patch 应用到同一 target 时按 LIFO 逻辑 undo——后 apply 的 snapshot 自然包含先前 patch 的结果。
    """
    if patch.status != "pending":
        return False, f"patch 当前状态是 {patch.status}，无法应用"

    if patch.target_kind == "narration":
        row = db.query(NarrativeLog).filter_by(id=patch.target_id).first()
        if not row:
            return False, "target narration 已不存在"
        original = row.text or ""
        patch.original_snapshot = original
        if patch.before_excerpt and patch.before_excerpt in original:
            row.text = original.replace(patch.before_excerpt, patch.after_text, 1)
        else:
            row.text = patch.after_text
    elif patch.target_kind == "event_title":
        row = db.query(Event).filter_by(id=patch.target_id).first()
        if not row:
            return False, "target event 已不存在"
        original = row.title or ""
        patch.original_snapshot = original
        if patch.before_excerpt and patch.before_excerpt in original:
            row.title = original.replace(patch.before_excerpt, patch.after_text, 1)
        else:
            row.title = patch.after_text
    elif patch.target_kind == "event_description":
        row = db.query(Event).filter_by(id=patch.target_id).first()
        if not row:
            return False, "target event 已不存在"
        original = row.description or ""
        patch.original_snapshot = original
        if patch.before_excerpt and patch.before_excerpt in original:
            row.description = original.replace(patch.before_excerpt, patch.after_text, 1)
        else:
            row.description = patch.after_text
    else:
        return False, f"unknown target_kind {patch.target_kind}"

    patch.status = "applied"
    patch.applied_at = datetime.utcnow()
    db.commit()
    return True, "applied"


def undo_patch(db: Session, patch: IssuePatch) -> tuple[bool, str]:
    """把已应用的 patch 撤销，target 字段还原到 apply 之前的整段文本。

    撤销后 patch 状态回到 pending，可以重新 apply 或 reject。
    """
    if patch.status != "applied":
        return False, f"patch 当前状态是 {patch.status}，无法撤销"

    if patch.target_kind == "narration":
        row = db.query(NarrativeLog).filter_by(id=patch.target_id).first()
        if not row:
            return False, "target narration 已不存在"
        row.text = patch.original_snapshot or ""
    elif patch.target_kind == "event_title":
        row = db.query(Event).filter_by(id=patch.target_id).first()
        if not row:
            return False, "target event 已不存在"
        row.title = patch.original_snapshot or ""
    elif patch.target_kind == "event_description":
        row = db.query(Event).filter_by(id=patch.target_id).first()
        if not row:
            return False, "target event 已不存在"
        row.description = patch.original_snapshot or ""
    else:
        return False, f"unknown target_kind {patch.target_kind}"

    patch.status = "pending"
    patch.applied_at = None
    db.commit()
    return True, "undone"


def preview_patch(db: Session, patch: IssuePatch, ctx_chars: int = 80) -> dict:
    """模拟 apply 但不落库，返回完整原文/替换后文本 + 三段切片（前文/改动块/后文）。

    若 before_excerpt 命中：定位首个出现位置，按 ctx_chars 取上下文。
    若不命中或为空：整段替换，前后上下文为空。
    target 已不存在时 found=False，原文为空字符串。
    """
    target_text = ""
    found_target = False

    if patch.target_kind == "narration":
        row = db.query(NarrativeLog).filter_by(id=patch.target_id).first()
        if row:
            target_text = row.text or ""
            found_target = True
    elif patch.target_kind == "event_title":
        row = db.query(Event).filter_by(id=patch.target_id).first()
        if row:
            target_text = row.title or ""
            found_target = True
    elif patch.target_kind == "event_description":
        row = db.query(Event).filter_by(id=patch.target_id).first()
        if row:
            target_text = row.description or ""
            found_target = True

    excerpt = patch.before_excerpt or ""
    after = patch.after_text or ""
    excerpt_match = bool(excerpt) and excerpt in target_text

    if excerpt_match:
        idx = target_text.index(excerpt)
        before_ctx = target_text[max(0, idx - ctx_chars): idx]
        after_ctx = target_text[idx + len(excerpt): idx + len(excerpt) + ctx_chars]
        replaced_full = target_text.replace(excerpt, after, 1)
        original_changed = excerpt
    else:
        before_ctx = ""
        after_ctx = ""
        replaced_full = after if found_target else after
        original_changed = target_text

    return {
        "patch_id": patch.id,
        "target_kind": patch.target_kind,
        "target_id": patch.target_id,
        "found_target": found_target,
        "excerpt_match": excerpt_match,
        "original": target_text,
        "replaced": replaced_full,
        "before_context": before_ctx,
        "original_changed": original_changed,
        "new_changed": after,
        "after_context": after_ctx,
    }
