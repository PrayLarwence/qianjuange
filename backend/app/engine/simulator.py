"""Narrative simulator: drives the LLM tool-loop that advances the world.

This module was lost and reconstructed from its call sites and the surrounding
engine modules. It exposes:

- run_step:       one tool-using turn
- run_auto:       N consecutive turns with cancel/progress hooks
- run_reconcile:  AI-driven causal patching after a user edit
- CancelledError: raised when an in-flight job is cancelled

Mock mode (`LLM_PROVIDER=mock`) skips the LLM and produces a deterministic
minimal advance so end-to-end tests don't require API keys.
"""

from __future__ import annotations
import json
import logging
import os
import re
import time
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from ..models import World, Branch, Entity, Event, NarrativeLog, ConsistencyIssue
from ..providers import get_provider, LLMProvider
from ..providers.base import Message, ToolCall, ToolSpec
from .state import build_state_snapshot, state_as_prompt
from .tools import TOOL_SPECS, SYSTEM_PROMPT, render_world_rules
from .executor import execute_tool, ToolError, active_branch_id

log = logging.getLogger(__name__)


class CancelledError(Exception):
    """Raised when run_auto / run_step detects cancellation."""


# Maximum tool-call hops within a single step before we force end_turn.
# Prevents runaway loops if the model keeps thinking.
MAX_HOPS_PER_STEP = 8


# ---------- helpers ----------

def _is_mock() -> bool:
    return (os.getenv("LLM_PROVIDER", "") or "").strip().lower() == "mock"


def _safe_progress(cb: Optional[Callable[[dict], None]], info: dict) -> None:
    if not cb:
        return
    try:
        cb(info)
    except Exception:
        log.exception("progress callback raised")


def _check_cancel(cancel_check: Optional[Callable[[], bool]]) -> None:
    if cancel_check and cancel_check():
        raise CancelledError("step cancelled")


def _serialize_tool_call(tc: ToolCall, result: Any, error: Optional[str] = None) -> dict:
    return {
        "id": tc.id,
        "name": tc.name,
        "arguments": tc.arguments,
        "result": result,
        "error": error,
    }


def _build_self_correction_block(db: Session, world: World) -> str:
    """A6 自纠环：把 Editor（一致性扫描）发现的未解决问题塞给 Director。

    取本 branch status='open' 的 ConsistencyIssue，按 severity（high → low）
    + tick_end 倒序排，最多 5 条。Director 写下一段时能看见'前面踩过哪些坑'。

    通过 world.rules.disable_self_correction = True 关闭。
    无 issues 或被关闭时返 ""。
    """
    if (world.rules or {}).get("disable_self_correction"):
        return ""
    branch_id = active_branch_id(world)
    if not branch_id:
        return ""

    issues = (
        db.query(ConsistencyIssue)
        .filter_by(branch_id=branch_id, status="open")
        .order_by(ConsistencyIssue.tick_end.desc())
        .limit(20)
        .all()
    )
    if not issues:
        return ""

    rank = {"high": 0, "medium": 1, "low": 2}
    issues.sort(key=lambda i: (rank.get(i.severity or "medium", 1), -(i.tick_end or 0)))
    top = issues[:5]

    lines = ["\n# 编辑反馈（之前章节发现的连贯性问题，下一段不要重蹈覆辙）"]
    for i in top:
        cat = i.category or "other"
        sev = i.severity or "medium"
        title = (i.title or "").strip()[:40]
        desc = (i.description or "").strip()[:120]
        sug = (i.suggestion or "").strip()[:120]
        line = f"- [{sev}/{cat}] {title}：{desc}"
        if sug:
            line += f"（建议：{sug}）"
        lines.append(line)
    return "\n".join(lines)


def _build_user_prompt(db: Session, snapshot: dict, user_directive: Optional[str], world: World) -> str:
    parts = [state_as_prompt(snapshot)]
    rules_text = render_world_rules(world.rules or {})
    if rules_text:
        parts.append("\n# 世界规则（强约束）\n" + rules_text)
    feedback = _build_self_correction_block(db, world)
    if feedback:
        parts.append(feedback)
    if user_directive and user_directive.strip():
        parts.append(f"\n# 用户指令\n{user_directive.strip()}")
    parts.append(
        "\n# 任务\n"
        "请基于上述状态推演下一段世界发展。通过工具调用改变状态："
        " advance_time 推进时间、add_event 记录事件、update_entity 更新角色，"
        " link_causality 建立因果，narrate 写一段散文（可选），最后必须 end_turn。"
    )
    return "\n".join(parts)


def _collect_recent_narration(db: Session, world: World, since_tick: int) -> list[str]:
    """取本回合的"展示用"叙述。

    新管线下同一 tick 可能有：
      - role='director_draft' (Author 改写前的粗稿，不展示)
      - role='author_final'   (Author 改写后的定稿，展示)
      - role='narrator'       (老数据/未跑 Author 的回合)

    展示规则：同 tick 内 author_final 优先；否则 narrator。director_draft 永远跳过。
    """
    branch_id = active_branch_id(world)
    rows = (
        db.query(NarrativeLog)
        .filter(NarrativeLog.branch_id == branch_id, NarrativeLog.tick >= since_tick)
        .order_by(NarrativeLog.tick.asc(), NarrativeLog.created_at.asc())
        .all()
    )
    # 每个 tick 选最佳一条；同优先级保留多条（同 tick 多次 author_final 不太常见，但允许）
    by_tick: dict[int, list[NarrativeLog]] = {}
    for r in rows:
        by_tick.setdefault(r.tick, []).append(r)
    out: list[str] = []
    for tick in sorted(by_tick.keys()):
        items = by_tick[tick]
        finals = [x for x in items if x.role == "author_final" and (x.text or "").strip()]
        if finals:
            for r in finals:
                out.append(r.text)
            continue
        narrators = [x for x in items if x.role in ("narrator", None) and (x.text or "").strip()]
        for r in narrators:
            out.append(r.text)
    return out


# ---------- mock executor ----------

def _run_mock_step(db: Session, world: World, user_directive: Optional[str]) -> dict:
    """Deterministic single-step advance used when LLM_PROVIDER=mock.

    Adds one event titled after the directive (or a generic one), advances
    one tick, and ends the turn. Useful for tests and demos.
    """
    start_tick = world.current_tick
    tool_calls: list[dict] = []

    title = (user_directive or "").strip() or "推演"
    title = title[:30]

    tc = ToolCall(id="mock_evt", name="add_event", arguments={
        "title": title,
        "description": f"[mock] 在 t={start_tick} 推演了一步：{title}",
    })
    try:
        res = execute_tool(db, world, tc.name, tc.arguments)
        tool_calls.append(_serialize_tool_call(tc, res))
    except ToolError as e:
        tool_calls.append(_serialize_tool_call(tc, None, error=str(e)))

    tc2 = ToolCall(id="mock_adv", name="advance_time", arguments={"ticks": 1})
    try:
        res = execute_tool(db, world, tc2.name, tc2.arguments)
        tool_calls.append(_serialize_tool_call(tc2, res))
    except ToolError as e:
        tool_calls.append(_serialize_tool_call(tc2, None, error=str(e)))

    tc3 = ToolCall(id="mock_end", name="end_turn", arguments={})
    res = execute_tool(db, world, tc3.name, tc3.arguments)
    tool_calls.append(_serialize_tool_call(tc3, res))

    db.commit()
    narration = _collect_recent_narration(db, world, start_tick)
    return {
        "ok": True,
        "tick": world.current_tick,
        "tick_start": start_tick,
        "tool_calls": tool_calls,
        "narration": "\n\n".join(narration),
        "hops": 1,
    }


# ---------- main loop ----------

def _resolve_provider(provider: Optional[LLMProvider]) -> Optional[LLMProvider]:
    if _is_mock():
        return None
    if provider is not None:
        return provider
    return get_provider()


def run_step(
    db: Session,
    world: World,
    user_directive: Optional[str] = None,
    provider: Optional[LLMProvider] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    on_progress: Optional[Callable[[dict], None]] = None,
    step_index: int = 1,
    step_total: int = 1,
) -> dict:
    """Run a single tool-using turn against the LLM.

    Returns a dict with:
      ok, tick, tick_start, tool_calls (list[dict]), narration (str), hops
    """
    _check_cancel(cancel_check)
    _safe_progress(on_progress, {"phase": "step_start", "step": step_index, "total": step_total})

    if _is_mock():
        return _run_mock_step(db, world, user_directive)

    llm = _resolve_provider(provider)
    if llm is None:
        # provider resolution failed and we're not in mock -> degrade to mock
        log.warning("no provider available, falling back to mock step")
        return _run_mock_step(db, world, user_directive)

    start_tick = world.current_tick
    snapshot = build_state_snapshot(db, world)
    user_prompt = _build_user_prompt(db, snapshot, user_directive, world)

    messages: list[Message] = [Message(role="user", content=user_prompt)]
    tool_calls_log: list[dict] = []
    ended = False

    for hop in range(MAX_HOPS_PER_STEP):
        _check_cancel(cancel_check)
        _safe_progress(on_progress, {
            "phase": "thinking", "hop": hop, "step": step_index, "total": step_total,
            "tool_calls": list(tool_calls_log),
        })
        try:
            resp = llm.chat(
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=TOOL_SPECS,
                max_tokens=2048,
                temperature=0.7,
            )
        except Exception as e:
            log.exception("LLM chat failed at hop %d", hop)
            raise

        # Append assistant turn (text + tool_calls) into history
        messages.append(Message(
            role="assistant",
            content=resp.text or "",
            tool_calls=list(resp.tool_calls or []),
        ))

        if not resp.tool_calls:
            # Model produced text but no tool calls — accept it as narration and end.
            if resp.text and resp.text.strip():
                try:
                    res = execute_tool(db, world, "narrate", {"text": resp.text.strip()})
                    tool_calls_log.append({
                        "id": f"auto_nar_{hop}", "name": "narrate",
                        "arguments": {"text": resp.text.strip()[:200]},
                        "result": res, "error": None,
                    })
                except ToolError as e:
                    log.warning("auto-narrate failed: %s", e)
            break

        _safe_progress(on_progress, {
            "phase": "executing", "hop": hop, "step": step_index, "total": step_total,
            "tool_calls": list(tool_calls_log),
        })

        for tc in resp.tool_calls:
            _check_cancel(cancel_check)
            try:
                result = execute_tool(db, world, tc.name, tc.arguments or {})
                tool_calls_log.append(_serialize_tool_call(tc, result))
                # Feed tool result back so the model can continue
                messages.append(Message(
                    role="tool",
                    content=json.dumps(result, ensure_ascii=False),
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                ))
                if tc.name == "end_turn":
                    ended = True
            except ToolError as e:
                err_msg = str(e)
                tool_calls_log.append(_serialize_tool_call(tc, None, error=err_msg))
                messages.append(Message(
                    role="tool",
                    content=json.dumps({"ok": False, "error": err_msg}, ensure_ascii=False),
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                ))
            except Exception as e:
                log.exception("tool %s raised", tc.name)
                err_msg = f"{type(e).__name__}: {e}"
                tool_calls_log.append(_serialize_tool_call(tc, None, error=err_msg))
                messages.append(Message(
                    role="tool",
                    content=json.dumps({"ok": False, "error": err_msg}, ensure_ascii=False),
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                ))

        if ended:
            break

    # If we hit the hop ceiling without end_turn, force a tick advance so the
    # world doesn't stall on this step.
    if not ended and world.current_tick == start_tick:
        try:
            execute_tool(db, world, "advance_time", {"ticks": 1})
        except ToolError:
            pass

    db.commit()

    # ----- Author 阶段：把本回合粗稿改写为小说级定稿 -----
    # 失败/无风格/mock 模式都会走 Author 内部回落逻辑（draft 直接 promote）。
    author_meta: dict | None = None
    try:
        from .author import run_author_for_step
        from .draft_cleanup import cleanup_old_drafts
        ar = run_author_for_step(
            db, world, active_branch_id(world), start_tick,
            provider=None,
        )
        if ar.ok and ar.log_id:
            author_meta = {
                "log_id": ar.log_id,
                "fell_back": ar.fell_back,
                "reason": ar.reason or None,
                "char_count": len(ar.text or ""),
            }
        # 不论成功/回落，都清理过期 draft
        cleanup_old_drafts(db, active_branch_id(world))
    except Exception as e:
        # Author 阶段本身崩溃也不能阻挡推演返回；老 narrator 会被 _collect 兜底。
        log.exception("author phase failed: %s", e)

    narration = _collect_recent_narration(db, world, start_tick)

    _safe_progress(on_progress, {
        "phase": "step_done", "step": step_index, "total": step_total,
        "tool_calls": list(tool_calls_log),
        "narration": "\n\n".join(narration),
    })

    return {
        "ok": True,
        "tick": world.current_tick,
        "tick_start": start_tick,
        "tool_calls": tool_calls_log,
        "narration": "\n\n".join(narration),
        "hops": hop + 1,
    }


def run_auto(
    db: Session,
    world: World,
    steps: int,
    user_directive: Optional[str] = None,
    provider: Optional[LLMProvider] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    on_progress: Optional[Callable[[dict], None]] = None,
) -> list[dict]:
    """Run N consecutive narrative steps. Stops early on cancel or HTTP exc."""
    steps = max(1, int(steps))
    results: list[dict] = []

    for i in range(steps):
        if cancel_check and cancel_check():
            raise CancelledError("auto-run cancelled before step %d" % (i + 1))
        if world.max_tick and world.current_tick >= world.max_tick:
            break
        try:
            r = run_step(
                db, world,
                user_directive=user_directive if i == 0 else None,
                provider=provider,
                cancel_check=cancel_check,
                on_progress=on_progress,
                step_index=i + 1,
                step_total=steps,
            )
        except CancelledError:
            raise
        except Exception as e:
            log.exception("step %d failed", i + 1)
            results.append({
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
                "tick": world.current_tick,
                "step": i + 1,
            })
            break
        results.append(r)

    return results


# ---------- reconcile ----------

RECONCILE_SYSTEM_PROMPT = """你是叙事一致性调和员。用户改动了既往的事件 / 实体属性，现在需要你
根据这些改动，自动改写下游受影响的事件，让整条因果链重新自洽。

要求：
* 用工具调用执行改写：update_event（改下游事件描述/参与者/后果）、delete_event（如果该事件不再可能发生）、
  link_causality（重新连接因果）、update_entity（修正角色状态）、narrate（必要时补一段过渡叙事）。
* 不要新建与改动无关的事件。改动应当最小但足够。
* 完成后调用 end_turn。
* 不要复述用户改动原文。
"""


def _build_reconcile_prompt(snapshot: dict, user_changes: list[str], seed_event_ids: list[str]) -> str:
    parts = [
        state_as_prompt(snapshot),
        "\n# 用户的改动（人话）",
    ]
    for c in user_changes or []:
        parts.append(f"- {c}")
    if seed_event_ids:
        parts.append("\n# 直接被改动的事件 id（下游需要联动改写）")
        for eid in seed_event_ids:
            parts.append(f"- {eid}")
    parts.append(
        "\n# 任务\n"
        "请审视上述世界状态与改动，找出因此变得不自洽的下游事件 / 实体状态，"
        "用 update_event / delete_event / link_causality / update_entity 执行最小化改写，最后 end_turn。"
    )
    return "\n".join(parts)


def run_reconcile(
    db: Session,
    world: World,
    user_changes: list[str],
    seed_event_ids: list[str],
    provider: Optional[LLMProvider] = None,
) -> dict:
    """Drive the LLM to patch downstream events after a user edit."""
    if _is_mock():
        return {
            "ok": True,
            "mock": True,
            "tool_calls": [],
            "narration": "",
            "tick": world.current_tick,
        }

    llm = _resolve_provider(provider)
    if llm is None:
        return {"ok": True, "mock": True, "tool_calls": [], "narration": "", "tick": world.current_tick}

    snapshot = build_state_snapshot(db, world, max_events=80)
    user_prompt = _build_reconcile_prompt(snapshot, user_changes, seed_event_ids)

    messages: list[Message] = [Message(role="user", content=user_prompt)]
    tool_calls_log: list[dict] = []
    ended = False
    start_tick = world.current_tick

    for hop in range(MAX_HOPS_PER_STEP):
        try:
            resp = llm.chat(
                system=RECONCILE_SYSTEM_PROMPT,
                messages=messages,
                tools=TOOL_SPECS,
                max_tokens=2048,
                temperature=0.4,
            )
        except Exception:
            log.exception("reconcile LLM call failed at hop %d", hop)
            raise

        messages.append(Message(
            role="assistant",
            content=resp.text or "",
            tool_calls=list(resp.tool_calls or []),
        ))
        if not resp.tool_calls:
            break

        for tc in resp.tool_calls:
            try:
                result = execute_tool(db, world, tc.name, tc.arguments or {})
                tool_calls_log.append(_serialize_tool_call(tc, result))
                messages.append(Message(
                    role="tool",
                    content=json.dumps(result, ensure_ascii=False),
                    tool_call_id=tc.id, tool_name=tc.name,
                ))
                if tc.name == "end_turn":
                    ended = True
            except ToolError as e:
                err_msg = str(e)
                tool_calls_log.append(_serialize_tool_call(tc, None, error=err_msg))
                messages.append(Message(
                    role="tool",
                    content=json.dumps({"ok": False, "error": err_msg}, ensure_ascii=False),
                    tool_call_id=tc.id, tool_name=tc.name,
                ))
            except Exception as e:
                log.exception("reconcile tool %s raised", tc.name)
                err_msg = f"{type(e).__name__}: {e}"
                tool_calls_log.append(_serialize_tool_call(tc, None, error=err_msg))
                messages.append(Message(
                    role="tool",
                    content=json.dumps({"ok": False, "error": err_msg}, ensure_ascii=False),
                    tool_call_id=tc.id, tool_name=tc.name,
                ))

        if ended:
            break

    db.commit()

    # ----- Author 阶段：把本回合粗稿改写为小说级定稿 -----
    # 失败/无风格/mock 模式都会走 Author 内部回落逻辑（draft 直接 promote）。
    author_meta: dict | None = None
    try:
        from .author import run_author_for_step
        from .draft_cleanup import cleanup_old_drafts
        ar = run_author_for_step(
            db, world, active_branch_id(world), start_tick,
            provider=None,
        )
        if ar.ok and ar.log_id:
            author_meta = {
                "log_id": ar.log_id,
                "fell_back": ar.fell_back,
                "reason": ar.reason or None,
                "char_count": len(ar.text or ""),
            }
        # 不论成功/回落，都清理过期 draft
        cleanup_old_drafts(db, active_branch_id(world))
    except Exception as e:
        # Author 阶段本身崩溃也不能阻挡推演返回；老 narrator 会被 _collect 兜底。
        log.exception("author phase failed: %s", e)

    narration = _collect_recent_narration(db, world, start_tick)
    return {
        "ok": True,
        "tick": world.current_tick,
        "tool_calls": tool_calls_log,
        "narration": "\n\n".join(narration),
        "hops": hop + 1,
    }
