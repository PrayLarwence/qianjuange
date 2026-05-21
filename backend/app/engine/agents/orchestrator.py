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
    obj: dict | None = None
    # 先试整体
    try:
        parsed = json.loads(s)
        if isinstance(parsed, dict):
            obj = parsed
    except Exception:
        pass
    # 退一步：括号匹配抽第一个完整 {...}
    if obj is None:
        start = s.find("{")
        while start != -1 and obj is None:
            depth = 0
            for i in range(start, len(s)):
                if s[i] == "{":
                    depth += 1
                elif s[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            parsed = json.loads(s[start:i + 1])
                            if isinstance(parsed, dict):
                                obj = parsed
                        except Exception:
                            pass
                        break
            start = s.find("{", start + 1)
    if obj is None:
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


def _best_of_k_temperatures(k: int, base: float = 0.85) -> list[float]:
    """K 个候选温度：K=1 走默认 [0.85]；K>=2 在 [0.55, 1.15] 上均匀分布。"""
    if k <= 1:
        return [base]
    spread = 0.6  # 总跨度
    lo = max(0.0, base - spread / 2)
    return [round(lo + spread * i / (k - 1), 2) for i in range(k)]


def _build_candidate_specs(cfg: PipelineConfig) -> list[dict]:
    """生成"要跑哪几个候选"的清单。

    - N=1, K=1：单候选 → 调用方走单次 author 路径，不进 ranking
    - N=1, K>1：1 个 author × K 个温度
    - N>1, K=1：N 个 author × 各自温度（system_prompt_extra 不同 → 真分工）
    - N>1, K>1：N 个 author × K 个温度（cartesian），每个 spec 标 author/temp 来源
    """
    N = len(cfg.authors)
    K = cfg.author_best_of
    if N == 1 and K == 1:
        return []
    specs: list[dict] = []
    if N == 1:
        for k_idx, t in enumerate(_best_of_k_temperatures(K)):
            specs.append({"author_idx": 0, "k_idx": k_idx, "temperature": t,
                          "author_cfg": cfg.authors[0]})
    elif K == 1:
        for a_idx, a in enumerate(cfg.authors):
            specs.append({"author_idx": a_idx, "k_idx": 0, "temperature": a.temperature,
                          "author_cfg": a})
    else:
        # N>1 且 K>1：cartesian，但每个 author 的温度只取自身值（K 决定每个 author 跑几次相同温度的多样性意义不大）
        # 简化：把 K 当成"每个 author 跑多少次", 仍用 _best_of_k_temperatures(K) 作温度变化
        for a_idx, a in enumerate(cfg.authors):
            for k_idx, t in enumerate(_best_of_k_temperatures(K)):
                specs.append({"author_idx": a_idx, "k_idx": k_idx, "temperature": t,
                              "author_cfg": a})
    return specs


def _best_of_k_author_phase(
    db: Session,
    job_id: str,
    world: World,
    seq_in: int,
    branch_id: str,
    start_tick: int,
    primary_author,
    cfg: PipelineConfig,
    provider: Optional[LLMProvider],
    budget: _Budget,
    cancel_check: Optional[Callable[[], bool]],
    arc_context: Optional[str],
) -> Optional[dict]:
    """生成 N×K 个候选 + 用 critic 总分挑出 winner，写为 author_final。

    触发条件：(K>1 OR N>1) AND 至少 1 个 critic AND 有 draft+style。
    返回 None 表示无法做 ranking（candidates 列表为空 / 无 provider / 无 critic / 无 draft 等），
    调用方应该 fallthrough 到单次 author 路径。

    成功返回 dict：
      seq_after, final_text, author_log_id,
      winner_idx (绝对 idx, 0..N*K-1), winner_author_idx, winner_temperature,
      winner_critic_results: dict[name → parsed],
      winner_all_pass: bool, winner_failed_feedback: list[dict],
    """
    specs = _build_candidate_specs(cfg)
    if not specs or not cfg.critics:
        return None
    from .author import (
        prepare_author_inputs, call_author_llm_once,
        write_author_final, write_author_fallback,
    )
    from ..core.simulator import _resolve_provider as _sim_resolve_provider
    llm = provider or _sim_resolve_provider(world)
    if llm is None:
        return None

    prep, early = prepare_author_inputs(db, world, branch_id, start_tick)
    if early is not None or prep is None:
        return None  # no draft / no style → 走单次路径

    seq = seq_in
    candidates: list[dict] = []  # {idx, author_idx, temperature, author_cfg, text|None, reason}

    for i, spec in enumerate(specs):
        if cancel_check and cancel_check():
            from ..core.simulator import CancelledError
            raise CancelledError()
        try:
            budget.check()
            budget.add_call()
        except BudgetExhausted:
            log.info("budget exhausted at candidate %d/%d", i, len(specs))
            break
        a_cfg = spec["author_cfg"]
        text, reason = call_author_llm_once(
            llm, prep,
            temperature=spec["temperature"],
            system_prompt_extra=a_cfg.system_prompt_extra,
        )
        candidates.append({
            "idx": i, "author_idx": spec["author_idx"],
            "temperature": spec["temperature"],
            "author_cfg": a_cfg, "text": text, "reason": reason,
        })
        seq += 1
        _write_trace(
            db, job_id=job_id, world_id=world.id, seq=seq,
            role="author", agent_name=a_cfg.name,
            model=a_cfg.model,
            status="done" if text else "error",
            input_summary=f"候选 #{i} (author={a_cfg.name}, T={spec['temperature']})",
            output_summary=_summarize(text or f"(rejected: {reason})", 200),
            extra={
                "candidate_index": i, "author_idx": spec["author_idx"],
                "temperature": spec["temperature"],
                "is_best_of_candidate": True, "char_count": len(text or ""),
                "reject_reason": None if text else reason,
            },
        )

    valid = [c for c in candidates if c["text"]]
    if not valid:
        # 所有候选都失败：fallback 一次
        log.warning("all %d candidates failed, falling back to draft", len(candidates))
        ar = write_author_fallback(db, prep, reason="all candidates failed")
        return {
            "seq_after": seq, "final_text": ar.text, "author_log_id": ar.log_id,
            "winner_idx": -1, "winner_critic_results": {},
            "winner_all_pass": False, "winner_failed_feedback": [],
            "fell_back": True,
        }

    # 给每个候选跑全套 critic（ranking phase, iteration=0 但 extra.is_ranking=True）
    candidate_critic_results: list[dict] = []  # 每项: {idx, scores, all_pass, failed_feedback, results: dict[name→parsed]}
    for cand in valid:
        per: dict = {"idx": cand["idx"], "results": {}, "scores": [],
                     "all_pass": True, "failed_feedback": []}
        for c in cfg.critics:
            if cancel_check and cancel_check():
                from ..core.simulator import CancelledError
                raise CancelledError()
            seq += 1
            try:
                parsed, _ = _run_one_critic(
                    db, job_id, world, seq, 0, c,
                    cand["text"], None, llm, budget, cancel_check,
                    previous_round=None,
                    arc_context=arc_context if c.kind == "arc" else None,
                )
            except BudgetExhausted:
                log.info("budget exhausted at ranking critic")
                # 把当前候选标 incomplete，但已评的还能用
                per["incomplete"] = True
                break
            # 标记为 ranking
            tr = db.query(AgentTrace).filter_by(job_id=job_id, seq=seq).first()
            if tr:
                ex = dict(tr.extra or {})
                ex["is_ranking"] = True
                ex["candidate_index"] = cand["idx"]
                tr.extra = ex
                db.commit()
            per["results"][c.name] = parsed
            per["scores"].append(parsed.get("score", 5))
            if parsed["verdict"] == "fail":
                per["all_pass"] = False
                per["failed_feedback"].append({
                    "name": c.name,
                    "reason": parsed["reason"],
                    "suggestions": parsed["suggestions"],
                })
        per["total_score"] = sum(per["scores"]) if per["scores"] else 0
        candidate_critic_results.append(per)

    # 选 winner: 先看 all_pass 候选; 平分时 idx 小者优先
    passing = [r for r in candidate_critic_results if r.get("all_pass") and not r.get("incomplete")]
    pool = passing if passing else candidate_critic_results
    pool_sorted = sorted(pool, key=lambda r: (-r.get("total_score", 0), r["idx"]))
    winner_summary = pool_sorted[0] if pool_sorted else None

    if winner_summary is None:
        # 极端：连 critic 都没跑成 → fallback 第一个有效候选
        winner_text = valid[0]["text"]
        winner_idx = valid[0]["idx"]
        winner_results: dict = {}
        winner_all_pass = False
        winner_feedback: list[dict] = []
    else:
        winner_idx = winner_summary["idx"]
        winner_text = next(c["text"] for c in valid if c["idx"] == winner_idx)
        winner_results = winner_summary["results"]
        winner_all_pass = bool(winner_summary.get("all_pass"))
        winner_feedback = list(winner_summary.get("failed_feedback") or [])

    final = write_author_final(db, prep, winner_text)

    winner_cand = next((c for c in valid if c["idx"] == winner_idx), None)
    seq += 1
    _write_trace(
        db, job_id=job_id, world_id=world.id, seq=seq,
        role="orchestrator", agent_name="(best-of-K pick)",
        status="done", verdict="pass" if winner_all_pass else "fail",
        input_summary=f"N={len(cfg.authors)} K={cfg.author_best_of} 候选 / {len(valid)} 有效",
        output_summary=f"选中 #{winner_idx} (author={winner_cand['author_cfg'].name if winner_cand else 'n/a'}, score={winner_summary.get('total_score') if winner_summary else 'n/a'}, all_pass={winner_all_pass})",
        extra={
            "k": cfg.author_best_of,
            "n_authors": len(cfg.authors),
            "winner_idx": winner_idx,
            "winner_author_idx": winner_cand["author_idx"] if winner_cand else -1,
            "winner_all_pass": winner_all_pass,
            "summary": [
                {"idx": r["idx"], "total_score": r.get("total_score"),
                 "all_pass": r.get("all_pass"), "fail_count": len(r.get("failed_feedback") or [])}
                for r in candidate_critic_results
            ],
        },
    )

    return {
        "seq_after": seq,
        "final_text": winner_text,
        "author_log_id": final.log_id,
        "winner_idx": winner_idx,
        "winner_author_idx": winner_cand["author_idx"] if winner_cand else -1,
        "winner_critic_results": winner_results,
        "winner_all_pass": winner_all_pass,
        "winner_failed_feedback": winner_feedback,
        "fell_back": False,
    }


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
    primary_author = cfg.authors[0]
    final_text = ""
    author_log_id = None
    best_of_state: Optional[dict] = None

    # arc critic 用的章节回顾：提到 author 阶段之前算，后续 best-of-K 评分 + 正式 critic 阶段共用
    arc_context: Optional[str] = None
    if cfg.critics and any(c.kind == "arc" for c in cfg.critics):
        from ..narrative.recap import build_chapter_recap_block
        try:
            arc_context = build_chapter_recap_block(db, world)
        except Exception as e:
            log.warning("build_chapter_recap_block failed: %s", e)
            arc_context = ""

    # 优先 ranking 路径：K>1（best-of-K）或 N>1（多 author 投票），且至少 1 个 critic
    if (cfg.author_best_of > 1 or len(cfg.authors) > 1) and cfg.critics:
        from ..core.simulator import CancelledError
        try:
            best_of_state = _best_of_k_author_phase(
                db, job_id, world, seq, branch_id, start_tick,
                primary_author, cfg, provider, budget, cancel_check, arc_context,
            )
        except CancelledError:
            return {
                "ok": False, "tick": world.current_tick, "tick_start": start_tick,
                "hops": sim_result.get("hops", 0), "tool_calls": sim_result.get("tool_calls", []),
                "narration": "", "critic_rounds": 0, "final_verdict": "cancelled",
                "unresolved_critics": [],
                "budget_used": {"llm_calls": budget.calls, "wall_seconds": int(time.monotonic() - budget.start)},
            }
        except BudgetExhausted:
            return {
                "ok": False, "tick": world.current_tick, "tick_start": start_tick,
                "hops": sim_result.get("hops", 0), "tool_calls": sim_result.get("tool_calls", []),
                "narration": "", "critic_rounds": 0, "final_verdict": "budget_exhausted",
                "unresolved_critics": [],
                "budget_used": {"llm_calls": budget.calls, "wall_seconds": int(time.monotonic() - budget.start)},
            }
        if best_of_state is not None:
            seq = best_of_state["seq_after"]
            final_text = best_of_state["final_text"]
            author_log_id = best_of_state["author_log_id"]
            from ..narrative.draft_cleanup import cleanup_old_drafts
            cleanup_old_drafts(db, branch_id)

    # 单次 author（K=1，或 best-of-K 早退）
    if best_of_state is None:
        seq += 1
        author_started = datetime.utcnow()
        author_t0 = time.monotonic()
        try:
            from .author import run_author_for_step
            from ..narrative.draft_cleanup import cleanup_old_drafts
            ar = run_author_for_step(db, world, branch_id, start_tick, provider=provider)
            if ar.ok and ar.log_id:
                author_log_id = ar.log_id
                final_text = ar.text or ""
            elif ar.ok and not ar.log_id:
                final_text = ""
            else:
                final_text = ar.text or ""
            cleanup_old_drafts(db, branch_id)
            budget.calls += 0 if ar.fell_back else 1
            author_status = "done"
            author_err = ""
        except Exception as e:
            log.exception("author phase crashed")
            author_status = "error"
            author_err = str(e)[:500]

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
            seeded_feedback: Optional[list[dict]] = None  # best-of-K 在 ranking 阶段已得到的 feedback

            # best-of-K 已经在 ranking 阶段跑过 critic：抽出结果做 seed，避免对 winner 文本再跑一遍 critic
            if best_of_state is not None:
                critic_rounds = 1  # ranking 算 1 轮
                for c_name, parsed in (best_of_state.get("winner_critic_results") or {}).items():
                    prev_by_critic[c_name] = {
                        "verdict": parsed.get("verdict", ""),
                        "reason": parsed.get("reason", ""),
                        "suggestions": parsed.get("suggestions", ""),
                    }
                if best_of_state.get("winner_all_pass"):
                    final_verdict = "pass"
                else:
                    seeded_feedback = list(best_of_state.get("winner_failed_feedback") or [])

            if final_verdict not in ("pass",):
                for iter_idx in range(cfg.max_critic_retries + 1):
                    feedback: list[dict] = []
                    # 第一轮且有 seed：直接用 ranking 阶段结果，不再调 critic
                    if iter_idx == 0 and seeded_feedback is not None:
                        feedback = list(seeded_feedback)
                    elif cfg.critic_mode == "serial":
                        critic_rounds += 1
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
                        critic_rounds += 1
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
                            seeded_feedback = None  # 已经基于 seed rewrite 完，下一轮要真跑 critic
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
        non_ranking = [t for t in critic_traces if not (t.extra or {}).get("is_ranking")]
        bok_pick = next(
            (t for t in traces if t.role == "orchestrator" and t.agent_name == "(best-of-K pick)"),
            None,
        )
        # critic_rounds: best-of-K 的 ranking 算 1 轮 + 后续重试循环每轮算 1
        if bok_pick is not None:
            loop_rounds = (max((t.iteration for t in non_ranking), default=-1) + 1)
            critic_rounds = 1 + loop_rounds
        else:
            critic_rounds = max(t.iteration for t in critic_traces) + 1
        rounds_total += critic_rounds
        if critic_rounds > 1:
            rounds_when_retried_total += critic_rounds
            rounds_when_retried_count += 1

        # first_pass：K=1 看 round 0 全 pass；best-of-K 看 winner_all_pass
        if bok_pick is not None:
            if (bok_pick.extra or {}).get("winner_all_pass"):
                first_pass_jobs += 1
        else:
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
