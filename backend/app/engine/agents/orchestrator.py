"""Multi-agent orchestrator：director(s) → author → critic(s) → 可选重写。

设计要点：
- director phase 复用 simulator.run_step（skip_author=True）。多 director 配置仅取
  第一个跑工具循环，剩余记录到 trace 标 'skipped'（多 director 同时改世界状态会冲突，
  策略层面留待后续）。
- author phase 复用 author.run_author_for_step；若失败/无 style 则 fallback。
- critic phase 是新写的：每个 critic 独立 LLM 调用，喂 final 文本 + focus + severity，
  返回结构化 verdict（pass/fail）+ reason。
- 任一 critic fail → 收集所有 reason → author 改写（重新跑 author）。最多 max_critic_retries 轮。
- 每个 LLM 调用前 check budget（max_llm_calls / max_wall_seconds）+ check cancel。
"""
from __future__ import annotations
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Callable, Optional

from sqlalchemy.orm import Session

from ...models import World, NarrativeLog, AgentTrace
from ...providers import get_provider
from ...providers.base import LLMProvider, Message
from .agent_pipeline import PipelineConfig, CriticAgent, resolve_for_world
from ..core.executor import active_branch_id
from ..core.simulator import run_step as sim_run_step, _is_mock as sim_is_mock

log = logging.getLogger(__name__)


class BudgetExhausted(Exception):
    """超出预算（LLM 调用数 / 挂钟）"""
    def __init__(self, kind: str, limit, used):
        self.kind = kind
        self.limit = limit
        self.used = used
        super().__init__(f"budget exhausted: {kind} limit={limit} used={used}")


class _Budget:
    def __init__(self, cfg: PipelineConfig):
        self.max_calls = cfg.budget.max_llm_calls
        self.max_wall = cfg.budget.max_wall_seconds
        self.calls = 0
        self.start = time.monotonic()

    def check(self):
        if self.calls >= self.max_calls:
            raise BudgetExhausted("llm_calls", self.max_calls, self.calls)
        if (time.monotonic() - self.start) > self.max_wall:
            raise BudgetExhausted("wall_seconds", self.max_wall, time.monotonic() - self.start)

    def add_call(self):
        self.calls += 1


def _new_trace_id() -> str:
    return f"at_{uuid.uuid4().hex[:10]}"


def _summarize(text: str, max_len: int = 240) -> str:
    if not text:
        return ""
    s = text.strip().replace("\n", " ")
    return s if len(s) <= max_len else s[:max_len] + "…"


def _write_trace(
    db: Session,
    *,
    job_id: str,
    world_id: str,
    seq: int,
    role: str,
    agent_name: str = "",
    iteration: int = 0,
    model: str = "",
    status: str = "running",
    verdict: str = "",
    input_summary: str = "",
    output_summary: str = "",
    full_prompt: str = "",
    full_response: str = "",
    extra: dict | None = None,
    started_at: Optional[datetime] = None,
    ended_at: Optional[datetime] = None,
) -> AgentTrace:
    tr = AgentTrace(
        id=_new_trace_id(),
        job_id=job_id,
        world_id=world_id,
        seq=seq,
        role=role,
        agent_name=agent_name,
        iteration=iteration,
        model=model,
        status=status,
        verdict=verdict,
        input_summary=input_summary,
        output_summary=output_summary,
        full_prompt=full_prompt,
        full_response=full_response,
        extra=extra or {},
        started_at=started_at or datetime.utcnow(),
        ended_at=ended_at,
    )
    db.add(tr)
    db.commit()
    return tr


CRITIC_SYSTEM_PROMPT = """你是小说审稿人。你只回复 JSON，不要任何额外文字。
你会拿到一段刚写好的小说定稿，以及你的关注点（focus）和严格度（severity）。
你的任务是判断这段定稿是否在你的关注维度上达标。

输出格式（严格 JSON）：
{
  "verdict": "pass" | "fail",
  "score": 0-10,
  "reason": "≤120 字的原因。fail 时必须具体指出问题；pass 时一句话即可。",
  "suggestions": "≤200 字的修改建议；pass 时为空字符串"
}

severity 含义：
- lenient：只在严重问题时打 fail（评分≤4 才 fail）
- normal：中等问题就打 fail（评分≤6 才 fail）
- strict：高标准，有任何明显瑕疵就 fail（评分≤7 才 fail）"""


def _build_critic_user_prompt(
    critic: CriticAgent,
    final_text: str,
    directive: Optional[str],
    previous_round: Optional[dict] = None,
    arc_context: Optional[str] = None,
) -> str:
    parts = []
    if directive:
        parts.append(f"# 用户本回合指令\n{directive}")
    parts.append(f"# 你的关注点（focus）\n{critic.focus or '（无特别关注，请整体把关）'}")
    parts.append(f"# 严格度\n{critic.severity}")
    if critic.kind == "arc" and arc_context and arc_context.strip():
        parts.append(
            "# 前文章节回顾（按时间顺序，主线发展）\n"
            f"{arc_context.strip()}\n"
            "（你是 arc critic：在判断本段定稿时，请额外检查"
            "1) 是否与前文设定 / 已发生事件冲突；"
            "2) 是否推进或至少不阻碍主线。"
            "纯文笔 / 节奏问题不归你管，让其它 critic 评。）"
        )
    if previous_round:
        prev_v = previous_round.get("verdict", "")
        prev_r = previous_round.get("reason", "")
        prev_s = previous_round.get("suggestions", "")
        parts.append(
            "# 你上一轮的审稿\n"
            f"- verdict: {prev_v}\n"
            f"- reason: {prev_r}\n"
            f"- suggestions: {prev_s}\n"
            "（作者已按上述建议改写。请只评估改后的版本是否解决了你提的问题；"
            "如果解决就 pass；如仍未解决，说明哪一条建议没被采纳；不要重复上一轮提过且已被改掉的问题。）"
        )
    parts.append(f"# 待审定稿\n{final_text}")
    parts.append("# 输出（仅 JSON）")
    return "\n\n".join(parts)


def _parse_critic_response(text: str) -> dict:
    """容忍 LLM 在 JSON 外面包了 markdown / 闲话；尽量提取核心字段。"""
    import re
    s = (text or "").strip()
    # 去掉 ```json ... ``` 包裹
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", s, re.S)
    if m:
        s = m.group(1)
    # 再退一步：抓第一个 {...} 块
    if not s.startswith("{"):
        m = re.search(r"\{.*\}", s, re.S)
        if m:
            s = m.group(0)
    try:
        obj = json.loads(s)
    except Exception:
        return {"verdict": "pass", "score": 5, "reason": "(critic response unparseable, default pass)", "suggestions": ""}
    verdict = str(obj.get("verdict", "pass")).lower().strip()
    if verdict not in ("pass", "fail"):
        verdict = "pass"
    return {
        "verdict": verdict,
        "score": int(obj.get("score", 5)) if isinstance(obj.get("score"), (int, float, str)) and str(obj.get("score")).strip().lstrip("-").isdigit() else 5,
        "reason": str(obj.get("reason", ""))[:600],
        "suggestions": str(obj.get("suggestions", ""))[:1000],
    }


def _run_one_critic(
    db: Session,
    job_id: str,
    world: World,
    seq: int,
    iteration: int,
    critic: CriticAgent,
    final_text: str,
    directive: Optional[str],
    provider: LLMProvider,
    budget: _Budget,
    cancel_check: Optional[Callable[[], bool]] = None,
    previous_round: Optional[dict] = None,
    arc_context: Optional[str] = None,
) -> tuple[dict, AgentTrace]:
    if cancel_check and cancel_check():
        from ..core.simulator import CancelledError
        raise CancelledError()
    budget.check()

    user_prompt = _build_critic_user_prompt(critic, final_text, directive, previous_round, arc_context)
    started = datetime.utcnow()
    t0 = time.monotonic()
    err_msg = ""
    resp_text = ""
    parsed = {"verdict": "pass", "score": 5, "reason": "(skipped)", "suggestions": ""}
    status = "done"
    try:
        budget.add_call()
        resp = provider.chat(
            system=CRITIC_SYSTEM_PROMPT,
            messages=[Message(role="user", content=user_prompt)],
            tools=[],
            max_tokens=512,
            temperature=0.3,
        )
        resp_text = resp.text or ""
        parsed = _parse_critic_response(resp_text)
    except Exception as e:
        log.exception("critic %s failed", critic.name)
        err_msg = f"{type(e).__name__}: {e}"
        status = "error"
        # critic 自己崩溃不应该阻挡定稿；当作 pass 让流程继续
        parsed = {"verdict": "pass", "score": 5, "reason": f"(critic crashed: {err_msg[:80]})", "suggestions": ""}

    duration_ms = int((time.monotonic() - t0) * 1000)
    tr = _write_trace(
        db,
        job_id=job_id,
        world_id=world.id,
        seq=seq,
        role="critic",
        agent_name=critic.name,
        iteration=iteration,
        model=critic.model or (provider.name if hasattr(provider, "name") else ""),
        status=status,
        verdict=parsed["verdict"],
        input_summary=_summarize(critic.focus or "(general)"),
        output_summary=f"[{parsed['verdict']} {parsed['score']}/10] {_summarize(parsed['reason'], 200)}",
        full_prompt=user_prompt,
        full_response=resp_text,
        extra={
            "score": parsed["score"],
            "suggestions": parsed["suggestions"],
            "duration_ms": duration_ms,
            "severity": critic.severity,
            "error": err_msg or None,
            "prev_round_used": bool(previous_round),
            "kind": critic.kind,
            "arc_context_used": bool(arc_context and arc_context.strip()) if critic.kind == "arc" else False,
        },
        started_at=started,
        ended_at=datetime.utcnow(),
    )
    return parsed, tr


def _author_rewrite(
    db: Session,
    job_id: str,
    world: World,
    seq: int,
    iteration: int,
    branch_id: str,
    start_tick: int,
    critic_feedback: list[dict],
    provider: LLMProvider,
    budget: _Budget,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> tuple[str, AgentTrace]:
    """根据 critic 反馈让 author 再写一遍。

    实现：把 critic 的 reason+suggestions 拼成提示，让 LLM 在原 author_final 文本基础上重写，
    覆盖最近一条 author_final（同 branch_id, tick==start_tick, role=author_final）的 text。
    返回 (新文本, trace)。
    """
    if cancel_check and cancel_check():
        from ..core.simulator import CancelledError
        raise CancelledError()
    budget.check()

    final = (
        db.query(NarrativeLog)
        .filter(
            NarrativeLog.branch_id == branch_id,
            NarrativeLog.tick >= start_tick,
            NarrativeLog.role == "author_final",
        )
        .order_by(NarrativeLog.revision_index.desc(), NarrativeLog.created_at.desc())
        .first()
    )
    original_text = final.text if final else ""

    feedback_str = "\n".join(
        f"- 【{c['name']}】{c['reason']}" + (f"\n  建议：{c['suggestions']}" if c.get("suggestions") else "")
        for c in critic_feedback
    )

    sys_prompt = "你是小说作者。你会拿到一段已经写好的章节正文，和审稿人的反馈。请按反馈修改，输出修改后的完整正文（仅正文，不要解释）。保持原长度量级，不要过度删减。"
    user_prompt = f"# 原文\n{original_text}\n\n# 审稿反馈\n{feedback_str}\n\n# 修改后正文（仅正文）"

    started = datetime.utcnow()
    t0 = time.monotonic()
    new_text = original_text
    status = "done"
    err_msg = ""
    resp_text = ""
    try:
        budget.add_call()
        resp = provider.chat(
            system=sys_prompt,
            messages=[Message(role="user", content=user_prompt)],
            tools=[],
            max_tokens=4096,
            temperature=0.7,
        )
        resp_text = resp.text or ""
        if resp_text.strip():
            new_text = resp_text.strip()
            if final is not None:
                final.text = new_text
                final.revision_index = (final.revision_index or 0) + 1
                db.flush()
                db.commit()
    except Exception as e:
        log.exception("author rewrite failed")
        err_msg = f"{type(e).__name__}: {e}"
        status = "error"

    duration_ms = int((time.monotonic() - t0) * 1000)
    tr = _write_trace(
        db,
        job_id=job_id,
        world_id=world.id,
        seq=seq,
        role="author",
        agent_name="author (rewrite)",
        iteration=iteration,
        model=provider.name if hasattr(provider, "name") else "",
        status=status,
        input_summary=f"重写：吸收 {len(critic_feedback)} 条 critic 反馈",
        output_summary=_summarize(new_text, 300),
        full_prompt=user_prompt,
        full_response=resp_text,
        extra={"duration_ms": duration_ms, "error": err_msg or None, "char_count": len(new_text)},
        started_at=started,
        ended_at=datetime.utcnow(),
    )
    return new_text, tr


def run_orchestrated_step(
    db: Session,
    world: World,
    user_directive: Optional[str] = None,
    *,
    job_id: str,
    cfg: Optional[PipelineConfig] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    on_progress: Optional[Callable[[dict], None]] = None,
    provider: Optional[LLMProvider] = None,
) -> dict:
    """完整执行：director(s) → author → critic(s) → 可选重写循环。

    返回 dict：
      ok, tick, tick_start, hops, narration, critic_rounds,
      final_verdict ("pass" | "forced_accept" | "no_critics" | "budget_exhausted" | "cancelled"),
      tool_calls (director 阶段产物)
    """
    cfg = cfg or resolve_for_world(world.agent_pipeline)
    budget = _Budget(cfg)
    seq = 0
    branch_id = active_branch_id(world)
    start_tick = world.current_tick

    def progress(info: dict):
        if on_progress:
            try:
                on_progress(info)
            except Exception:
                pass

    progress({"phase": "orchestrator_start", "config": cfg.model_dump()})

    # ----- director phase（复用 simulator.run_step，但 skip_author）-----
    seq += 1
    primary_director = cfg.directors[0]
    director_started = datetime.utcnow()
    director_t0 = time.monotonic()

    # director 这一阶段会有多 hop，每 hop 算一次 LLM 调用——所以预扣 max_hops 次预算检查
    if cfg.directors[0].max_hops + budget.calls > budget.max_calls:
        # 不强制阻挡，让 simulator.run_step 自己跑，到 budget 用尽时由 cancel_check 兜底
        pass

    sim_result: dict
    try:
        budget.check()
        sim_result = sim_run_step(
            db, world,
            user_directive=user_directive,
            provider=provider,
            cancel_check=cancel_check,
            on_progress=on_progress,
            skip_author=True,
        )
        # director phase 的 LLM 调用次数 ≈ hops。一次保守加 hops
        budget.calls += int(sim_result.get("hops", 1))
    except Exception as e:
        from ..core.simulator import CancelledError as _CancelledError
        is_cancel = isinstance(e, _CancelledError)
        log.warning("director phase ended early: %s", type(e).__name__) if is_cancel else log.exception("director phase crashed")
        _write_trace(
            db, job_id=job_id, world_id=world.id, seq=seq,
            role="director", agent_name=primary_director.name,
            status="cancelled" if is_cancel else "error",
            input_summary=_summarize(user_directive or "(no directive)"),
            output_summary=("director 阶段被取消" if is_cancel else f"director phase 崩溃：{type(e).__name__}"),
            extra={"error": None if is_cancel else str(e)[:500]},
            started_at=director_started, ended_at=datetime.utcnow(),
        )
        if is_cancel:
            return {
                "ok": False,
                "tick": world.current_tick,
                "tick_start": start_tick,
                "hops": 0,
                "tool_calls": [],
                "narration": "",
                "critic_rounds": 0,
                "final_verdict": "cancelled",
                "budget_used": {
                    "llm_calls": budget.calls,
                    "wall_seconds": int(time.monotonic() - budget.start),
                },
            }
        raise

    _write_trace(
        db, job_id=job_id, world_id=world.id, seq=seq,
        role="director", agent_name=primary_director.name,
        model=primary_director.model,
        status="done",
        input_summary=_summarize(user_directive or "(no directive)"),
        output_summary=f"工具调用 {len(sim_result.get('tool_calls', []))} 次 / hops {sim_result.get('hops', 0)} / tick {sim_result.get('tick_start')}→{sim_result.get('tick')}",
        extra={
            "tool_calls": sim_result.get("tool_calls", []),
            "duration_ms": int((time.monotonic() - director_t0) * 1000),
            "hops": sim_result.get("hops", 0),
        },
        started_at=director_started, ended_at=datetime.utcnow(),
    )

    # 多余的 director 配置：mark skipped trace（透明告知用户）
    for extra_dir in cfg.directors[1:]:
        seq += 1
        _write_trace(
            db, job_id=job_id, world_id=world.id, seq=seq,
            role="director", agent_name=extra_dir.name,
            status="done", verdict="skipped",
            input_summary="(skipped)",
            output_summary="多 director 模式暂未启用：仅第一个 director 跑工具循环",
            extra={"skipped_reason": "multi_director_not_yet_supported"},
        )

    # ----- author phase -----
    seq += 1
    primary_author = cfg.authors[0]
    author_started = datetime.utcnow()
    author_t0 = time.monotonic()
    final_text = ""
    author_log_id = None
    try:
        from .author import run_author_for_step
        from ..narrative.draft_cleanup import cleanup_old_drafts
        ar = run_author_for_step(db, world, branch_id, start_tick, provider=provider)
        if ar.ok and ar.log_id:
            author_log_id = ar.log_id
            final_text = ar.text or ""
        elif ar.ok and not ar.log_id:
            # no draft / no style 等"软回落"
            final_text = ""
        else:
            final_text = ar.text or ""
        cleanup_old_drafts(db, branch_id)
        # author 内部会调一次 LLM，加进 budget
        budget.calls += 0 if ar.fell_back else 1
        author_status = "done"
        author_err = ""
    except Exception as e:
        log.exception("author phase crashed")
        author_status = "error"
        author_err = str(e)[:500]

    # 若 final_text 为空，从库里反查最新 author_final / director_draft 兜底
    if not final_text:
        log_row = (
            db.query(NarrativeLog)
            .filter(
                NarrativeLog.branch_id == branch_id,
                NarrativeLog.tick >= start_tick,
                NarrativeLog.role.in_(["author_final", "director_draft", "narrator"]),
            )
            .order_by(NarrativeLog.created_at.desc())
            .first()
        )
        if log_row and log_row.text:
            final_text = log_row.text
            author_log_id = log_row.id

    _write_trace(
        db, job_id=job_id, world_id=world.id, seq=seq,
        role="author", agent_name=primary_author.name,
        model=primary_author.model,
        status=author_status if final_text else "error",
        input_summary=f"汇总本回合 director_draft（tick {start_tick}+）",
        output_summary=_summarize(final_text, 300),
        extra={
            "duration_ms": int((time.monotonic() - author_t0) * 1000),
            "log_id": author_log_id,
            "char_count": len(final_text),
            "error": author_err if author_status == "error" else None,
        },
        started_at=author_started, ended_at=datetime.utcnow(),
    )

    # ----- critic phase -----
    final_verdict = "no_critics"
    critic_rounds = 0
    unresolved_feedback: list[dict] = []  # forced_accept 时仍未解决的 critic 反馈

    if cfg.critics and final_text:
        from ..core.simulator import _resolve_provider, CancelledError
        critic_provider = provider if provider is not None else _resolve_provider(None)
        if critic_provider is None or sim_is_mock():
            # 没 provider / mock 模式：跳过 critic，直接 pass
            final_verdict = "no_critics"
            seq += 1
            _write_trace(
                db, job_id=job_id, world_id=world.id, seq=seq,
                role="orchestrator", agent_name="(skip critics)",
                status="done", verdict="skipped",
                input_summary="(no provider available)",
                output_summary="跳过 critic 阶段（mock 模式或 provider 未配置）",
            )
        else:
            prev_by_critic: dict[str, dict] = {}
            # arc critic 需要章节回顾。任一 critic 是 arc kind 才算一次 build（避免无谓 IO）
            arc_context: Optional[str] = None
            if any(c.kind == "arc" for c in cfg.critics):
                from ..narrative.recap import build_chapter_recap_block
                try:
                    arc_context = build_chapter_recap_block(db, world)
                except Exception as e:  # 不让 recap 故障阻断推演
                    log.warning("build_chapter_recap_block failed: %s", e)
                    arc_context = ""
            for iter_idx in range(cfg.max_critic_retries + 1):
                critic_rounds = iter_idx + 1
                feedback: list[dict] = []
                # parallel: 全部 critic 都跑完再决定。serial: 第一个 fail 立即停。
                if cfg.critic_mode == "serial":
                    for c in cfg.critics:
                        seq += 1
                        try:
                            parsed, _ = _run_one_critic(
                                db, job_id, world, seq, iter_idx, c,
                                final_text, user_directive, critic_provider, budget, cancel_check,
                                previous_round=prev_by_critic.get(c.name),
                                arc_context=arc_context if c.kind == "arc" else None,
                            )
                        except BudgetExhausted:
                            final_verdict = "budget_exhausted"
                            break
                        except CancelledError:
                            final_verdict = "cancelled"
                            break
                        prev_by_critic[c.name] = {
                            "verdict": parsed["verdict"],
                            "reason": parsed["reason"],
                            "suggestions": parsed["suggestions"],
                        }
                        if parsed["verdict"] == "fail":
                            feedback.append({
                                "name": c.name,
                                "reason": parsed["reason"],
                                "suggestions": parsed["suggestions"],
                            })
                            break  # serial：第一个 fail 即触发 rewrite
                    if final_verdict in ("budget_exhausted", "cancelled"):
                        break
                else:  # parallel
                    for c in cfg.critics:
                        seq += 1
                        try:
                            parsed, _ = _run_one_critic(
                                db, job_id, world, seq, iter_idx, c,
                                final_text, user_directive, critic_provider, budget, cancel_check,
                                previous_round=prev_by_critic.get(c.name),
                                arc_context=arc_context if c.kind == "arc" else None,
                            )
                        except BudgetExhausted:
                            final_verdict = "budget_exhausted"
                            break
                        except CancelledError:
                            final_verdict = "cancelled"
                            break
                        prev_by_critic[c.name] = {
                            "verdict": parsed["verdict"],
                            "reason": parsed["reason"],
                            "suggestions": parsed["suggestions"],
                        }
                        if parsed["verdict"] == "fail":
                            feedback.append({
                                "name": c.name,
                                "reason": parsed["reason"],
                                "suggestions": parsed["suggestions"],
                            })
                    if final_verdict in ("budget_exhausted", "cancelled"):
                        break

                if not feedback:
                    final_verdict = "pass"
                    break

                # 还有重试机会才 rewrite
                if iter_idx < cfg.max_critic_retries:
                    seq += 1
                    try:
                        new_text, _ = _author_rewrite(
                            db, job_id, world, seq, iter_idx + 1,
                            branch_id, start_tick, feedback, critic_provider, budget, cancel_check,
                        )
                        final_text = new_text or final_text
                    except BudgetExhausted:
                        final_verdict = "budget_exhausted"
                        break
                    except CancelledError:
                        final_verdict = "cancelled"
                        break
                else:
                    # 用完重试次数，强制接受
                    final_verdict = "forced_accept"
                    unresolved_feedback = feedback
                    seq += 1
                    _write_trace(
                        db, job_id=job_id, world_id=world.id, seq=seq,
                        role="orchestrator", agent_name="(forced accept)",
                        status="done", verdict="forced_accept",
                        input_summary=f"已重写 {cfg.max_critic_retries} 次",
                        output_summary=f"达到重试上限，强制接受当前定稿（仍有 {len(feedback)} 个 critic 反对）",
                        extra={"feedback": feedback, "is_forced_accept": True},
                    )
                    break

    progress({"phase": "orchestrator_done", "verdict": final_verdict, "rounds": critic_rounds})

    return {
        "ok": True,
        "tick": world.current_tick,
        "tick_start": start_tick,
        "hops": sim_result.get("hops", 0),
        "tool_calls": sim_result.get("tool_calls", []),
        "narration": final_text,
        "critic_rounds": critic_rounds,
        "final_verdict": final_verdict,
        "unresolved_critics": unresolved_feedback,
        "budget_used": {
            "llm_calls": budget.calls,
            "wall_seconds": int(time.monotonic() - budget.start),
        },
    }


def query_pipeline_metrics(db: Session, world_id: str, hours: int = 168) -> dict:
    """聚合 AgentTrace 给出 pipeline 维度指标。

    返回：
      summary: total_jobs / forced_accept / forced_accept_rate / first_pass / first_pass_rate
               / avg_critic_rounds / avg_critic_rounds_when_retried
      by_critic: {name: {runs, pass, fail, error, avg_score, fail_rate}}
      recent_forced: 最近 forced_accept 的 job 列表（job_id, ts, unresolved_count, traces 摘要）
    """
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(hours=hours)

    rows = (
        db.query(AgentTrace)
        .filter(AgentTrace.world_id == world_id, AgentTrace.started_at >= cutoff)
        .order_by(AgentTrace.started_at.asc(), AgentTrace.seq.asc())
        .all()
    )

    by_job: dict[str, list[AgentTrace]] = {}
    for r in rows:
        by_job.setdefault(r.job_id, []).append(r)

    total_jobs = 0
    forced_accept_jobs: list[dict] = []
    first_pass_jobs = 0
    rounds_total = 0
    rounds_when_retried_total = 0
    rounds_when_retried_count = 0

    by_critic: dict[str, dict] = {}

    for job_id, traces in by_job.items():
        critic_traces = [t for t in traces if t.role == "critic"]
        # 只把"真的跑过 critic"的 job 算进来；纯单 agent / no_critics 的不参与统计
        if not critic_traces:
            continue
        total_jobs += 1
        max_iter = max(t.iteration for t in critic_traces)
        critic_rounds = max_iter + 1
        rounds_total += critic_rounds
        if critic_rounds > 1:
            rounds_when_retried_total += critic_rounds
            rounds_when_retried_count += 1

        # 第一轮全 pass = first_pass
        round0 = [t for t in critic_traces if t.iteration == 0]
        if round0 and all(t.verdict == "pass" for t in round0):
            first_pass_jobs += 1

        # forced_accept 检测
        fa = next(
            (t for t in traces if t.role == "orchestrator" and t.verdict == "forced_accept"),
            None,
        )
        if fa is not None:
            unresolved = (fa.extra or {}).get("feedback") or []
            forced_accept_jobs.append({
                "job_id": job_id,
                "ts": fa.started_at.isoformat() if fa.started_at else None,
                "unresolved_count": len(unresolved),
                "unresolved": unresolved[:5],
            })

        # 每个 critic 的统计
        for t in critic_traces:
            name = t.agent_name or "(unnamed)"
            d = by_critic.setdefault(name, {
                "runs": 0, "pass": 0, "fail": 0, "error": 0,
                "score_sum": 0, "score_count": 0,
            })
            d["runs"] += 1
            if t.status == "error":
                d["error"] += 1
            elif t.verdict == "pass":
                d["pass"] += 1
            elif t.verdict == "fail":
                d["fail"] += 1
            score = (t.extra or {}).get("score")
            if isinstance(score, (int, float)):
                d["score_sum"] += float(score)
                d["score_count"] += 1

    by_critic_out = {}
    for name, d in by_critic.items():
        runs = d["runs"]
        avg_score = round(d["score_sum"] / d["score_count"], 2) if d["score_count"] else None
        by_critic_out[name] = {
            "runs": runs,
            "pass": d["pass"],
            "fail": d["fail"],
            "error": d["error"],
            "avg_score": avg_score,
            "fail_rate": round(d["fail"] / runs, 3) if runs else 0.0,
        }

    summary = {
        "total_jobs": total_jobs,
        "forced_accept": len(forced_accept_jobs),
        "forced_accept_rate": round(len(forced_accept_jobs) / total_jobs, 3) if total_jobs else 0.0,
        "first_pass": first_pass_jobs,
        "first_pass_rate": round(first_pass_jobs / total_jobs, 3) if total_jobs else 0.0,
        "avg_critic_rounds": round(rounds_total / total_jobs, 2) if total_jobs else 0.0,
        "avg_critic_rounds_when_retried": (
            round(rounds_when_retried_total / rounds_when_retried_count, 2)
            if rounds_when_retried_count else None
        ),
        "hours": hours,
    }

    forced_accept_jobs.sort(key=lambda j: j["ts"] or "", reverse=True)
    return {
        "summary": summary,
        "by_critic": by_critic_out,
        "recent_forced": forced_accept_jobs[:5],
    }
