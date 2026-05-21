"""Author agent。

把 Director 的粗稿（NarrativeLog role=director_draft）改写为小说级文字
（role=author_final）。Author 不调任何工具——只输入 context，输出文本。

设计原则：
1. 无工具权限：分工纪律——Director 管世界，Author 只管文字
2. 失败回落：任何异常都把粗稿 promote 为最终稿（用户永远能看到结果）
3. 风格指纹：spec_text + sample_paragraphs 一起喂，sample 比 spec 重要
4. 不扩展剧情：prompt 明确禁止"新增事件/角色/对白细节"——Author 只能改写
   Director 已写下的内容，需要新事件请 Director 下一回合处理

阶段 1（A3）：Author 只看 long_memory + 最近 author_final + persona +
本回合 director_draft + style_spec。RAG 召回的相关历史段在 B2 阶段加。
"""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass
from typing import Optional
from sqlalchemy.orm import Session

from ...models import World, NarrativeLog, Entity, Event, StyleProfile
from ...providers import get_provider_for_role
from ...providers.base import LLMProvider, Message

log = logging.getLogger(__name__)


# 输出长度的健康度阈值。Author 输出过短/过长一般是模型抽风，回落用粗稿。
MIN_OUTPUT_RATIO = 0.3   # 不少于粗稿总长 30%
MAX_OUTPUT_RATIO = 5.0   # 不多于粗稿总长 5 倍
MAX_RECENT_FINAL_CHARS = 2400  # 喂给 Author 的最近定稿历史窗口


@dataclass
class AuthorResult:
    ok: bool
    log_id: Optional[str] = None
    text: str = ""
    reason: str = ""  # 失败 / 跳过原因
    fell_back: bool = False  # True 表示走了"粗稿 promote 为定稿"的回落分支


@dataclass
class _AuthorPrep:
    """run_author_for_step 内部共享的输入：drafts 及构造 prompt 所需的全部上下文。

    best-of-K 模式下 orchestrator 会复用本结构以多次调用 LLM。
    """
    style: StyleProfile
    drafts: list[NarrativeLog]
    draft_text: str
    system_prompt: str
    user_prompt: str


def _new_id() -> str:
    import uuid
    return f"nar_{uuid.uuid4().hex[:10]}"


def _resolve_style(db: Session, world: World) -> Optional[StyleProfile]:
    sid = (world.style_profile_id or "").strip()
    if not sid:
        return None
    return db.query(StyleProfile).filter_by(id=sid).first()


def _collect_recent_finals(db: Session, branch_id: str, before_tick: int) -> str:
    """取此 tick 之前最近的若干段 author_final 作为风格连续性参考。"""
    rows = (
        db.query(NarrativeLog)
        .filter(
            NarrativeLog.branch_id == branch_id,
            NarrativeLog.tick < before_tick,
            NarrativeLog.role == "author_final",
        )
        .order_by(NarrativeLog.tick.desc(), NarrativeLog.created_at.desc())
        .limit(6)
        .all()
    )
    rows = list(reversed(rows))
    out, total = [], 0
    for r in rows:
        t = (r.text or "").strip()
        if not t:
            continue
        if total + len(t) > MAX_RECENT_FINAL_CHARS:
            break
        out.append(t)
        total += len(t)
    return "\n\n".join(out)


def _personas_for_events(db: Session, branch_id: str, events: list[Event]) -> str:
    pids: set[str] = set()
    for e in events:
        for p in (e.participants or []):
            if isinstance(p, str):
                pids.add(p)
    if not pids:
        return ""
    rows = db.query(Entity).filter(Entity.branch_id == branch_id, Entity.id.in_(pids)).all()
    chunks = []
    for e in rows:
        persona = e.persona or {}
        # persona 可能是 dict 或 字符串；都用 json 简化
        persona_text = (
            json.dumps(persona, ensure_ascii=False, indent=None)
            if isinstance(persona, dict) else str(persona)
        )
        if len(persona_text) > 600:
            persona_text = persona_text[:600] + "…"
        chunks.append(f"### {e.name}（{e.type}）\n{e.summary or ''}\n人格: {persona_text}")
    return "\n\n".join(chunks)


def _format_events(events: list[Event]) -> str:
    lines = []
    for e in events:
        parts = [f"[t{e.tick}] {e.title}"]
        if e.description:
            parts.append(e.description)
        lines.append(" — ".join(parts))
    return "\n".join(lines)


def _format_drafts(drafts: list[NarrativeLog]) -> str:
    out = []
    for d in drafts:
        t = (d.text or "").strip()
        if t:
            out.append(t)
    return "\n\n".join(out)


def _build_prompt(
    style: StyleProfile,
    long_memory: str,
    recent_finals: str,
    persona_block: str,
    events_text: str,
    draft_text: str,
) -> tuple[str, str]:
    """返回 (system, user) 两段 prompt。"""
    sample_text = ""
    samples = style.sample_paragraphs or []
    if isinstance(samples, list) and samples:
        bits = []
        for s in samples[:3]:
            if isinstance(s, dict):
                title = s.get("title", "")
                text = s.get("text", "")
                if text:
                    bits.append(f"### {title}\n{text}" if title else text)
            elif isinstance(s, str):
                bits.append(s)
        sample_text = "\n\n".join(bits)

    system = f"""你是一名小说家。请按下面的风格规范，把用户给你的"剧情粗稿"改写为小说级正文。

# 风格规范
{style.spec_text or '(无 spec)'}

# 风格示例（最重要的参考——你的输出在句法、词汇、节奏上要与之一致）
{sample_text or '(无样例)'}

# 改写纪律
1. **绝对不要新增剧情**：粗稿里没写的事件、对白、角色，不要凭空加
2. **不要改变事件走向**：发生了什么不能改，怎么发生的可以改
3. **可以删减啰嗦**：粗稿往往啰嗦，按风格要求的节奏可以合并/删减
4. **可以重排顺序**：为了节奏可以打乱粗稿内部段落顺序，但要保持因果通顺
5. **保持人物口吻**：参考下面的角色 persona，对白和心理要符合各自人格
6. **直接输出小说正文**：不要用 markdown 标题、不要解释你做了什么、不要写"以下是改写后的版本"之类的元话语"""

    user_parts = []
    if long_memory:
        user_parts.append(f"# 全书印象\n{long_memory}")
    if recent_finals:
        user_parts.append(f"# 最近章节定稿（你之前的输出，保持风格连贯）\n{recent_finals}")
    if persona_block:
        user_parts.append(f"# 本回合涉及角色\n{persona_block}")
    if events_text:
        user_parts.append(f"# 本回合事件骨架（不可改）\n{events_text}")
    user_parts.append(f"# 粗稿（请改写为小说正文）\n{draft_text}")
    user_parts.append("\n请直接输出改写后的小说正文。")
    user = "\n\n".join(user_parts)
    return system, user


def run_author_for_step(
    db: Session,
    world: World,
    branch_id: str,
    start_tick: int,
    *,
    provider: Optional[LLMProvider] = None,
    long_memory: str = "",
) -> AuthorResult:
    """对本回合（tick >= start_tick）的所有粗稿调一次 Author。

    流程：
    1. 找本回合 role='narrator' 的 NarrativeLog（Director 推完产生的原始稿）
    2. 把它们的 role 标记为 'director_draft'（这是回合结束后的 retag）
    3. 若 World 没绑 style_profile 或 LLM 不可用 → 把第一条 draft 拷贝为 author_final 回落
    4. 否则调 LLM 改写，写一行 author_final（parent_log_id 指向第一条 draft）
    5. 输出长度异常或 LLM 异常 → 同样回落
    """
    prep, early = prepare_author_inputs(db, world, branch_id, start_tick, long_memory=long_memory)
    if early is not None:
        return early
    assert prep is not None

    try:
        llm = provider or get_provider_for_role(world, "author")
    except Exception as e:
        log.warning("author provider resolution failed: %s", e)
        return write_author_fallback(db, prep, reason=f"provider error: {e}")
    if llm is None:
        return write_author_fallback(db, prep, reason="no provider")

    text, reason = call_author_llm_once(llm, prep, temperature=0.85)
    if text is None:
        return write_author_fallback(db, prep, reason=reason)
    return write_author_final(db, prep, text)


def prepare_author_inputs(
    db: Session,
    world: World,
    branch_id: str,
    start_tick: int,
    *,
    long_memory: str = "",
) -> tuple[Optional[_AuthorPrep], Optional[AuthorResult]]:
    """收集粗稿 + 风格 + 上下文，retag narrator → director_draft，构造 system/user prompt。

    返回 (prep, early_result)：
      - prep != None：可继续调 LLM
      - early_result != None：无草稿 / 无风格的早退路径，调用方直接返回
    """
    drafts = (
        db.query(NarrativeLog)
        .filter(
            NarrativeLog.branch_id == branch_id,
            NarrativeLog.tick >= start_tick,
            NarrativeLog.role == "narrator",
        )
        .order_by(NarrativeLog.tick.asc(), NarrativeLog.created_at.asc())
        .all()
    )
    if not drafts:
        return None, AuthorResult(ok=True, reason="no draft")

    style = _resolve_style(db, world)
    if style is None:
        return None, AuthorResult(ok=True, reason="no style profile (legacy world)", fell_back=False)

    for d in drafts:
        d.role = "director_draft"
    db.flush()

    draft_text = _format_drafts(drafts)

    events = (
        db.query(Event)
        .filter(Event.branch_id == branch_id, Event.tick >= start_tick, Event.deleted == 0)
        .order_by(Event.tick.asc(), Event.created_at.asc())
        .all()
    )
    recent_finals = _collect_recent_finals(db, branch_id, start_tick)
    persona_block = _personas_for_events(db, branch_id, events)
    events_text = _format_events(events)

    system, user = _build_prompt(
        style=style,
        long_memory=long_memory,
        recent_finals=recent_finals,
        persona_block=persona_block,
        events_text=events_text,
        draft_text=draft_text,
    )
    return _AuthorPrep(
        style=style, drafts=drafts, draft_text=draft_text,
        system_prompt=system, user_prompt=user,
    ), None


def call_author_llm_once(
    llm: LLMProvider,
    prep: _AuthorPrep,
    *,
    temperature: float = 0.85,
    system_prompt_extra: str = "",
) -> tuple[Optional[str], str]:
    """单次 LLM 调用 + 长度健康度校验。

    成功返回 (text, "ok")；任何失败返回 (None, reason)。无 DB 写入。

    system_prompt_extra: 在共享 system prompt 末尾追加的额外指令（多 author 投票时
    每个 author 用自己的 extra 制造分工/风格差异）。
    """
    system = prep.system_prompt
    if system_prompt_extra and system_prompt_extra.strip():
        system = system + "\n\n# 本 author 的额外指令\n" + system_prompt_extra.strip()
    try:
        resp = llm.chat(
            system=system,
            messages=[Message(role="user", content=prep.user_prompt)],
            tools=[],
            max_tokens=4096,
            temperature=temperature,
            timeout=90.0,
        )
    except Exception as e:
        log.warning("author LLM call failed: %s", e)
        return None, f"llm error: {e}"

    text = (resp.text or "").strip()
    if not text:
        return None, "empty output"

    draft_len = max(1, len(prep.draft_text))
    ratio = len(text) / draft_len
    if ratio < MIN_OUTPUT_RATIO or ratio > MAX_OUTPUT_RATIO:
        log.info("author output length suspicious (ratio=%.2f); rejecting", ratio)
        return None, f"length anomaly (ratio={ratio:.2f})"
    return text, "ok"


def write_author_final(db: Session, prep: _AuthorPrep, text: str) -> AuthorResult:
    """把成功输出落库为 author_final。"""
    final = NarrativeLog(
        id=_new_id(), branch_id=prep.drafts[0].branch_id, tick=prep.drafts[0].tick,
        role="author_final", text=text, revision_index=0,
        parent_log_id=prep.drafts[0].id,
    )
    db.add(final); db.commit()
    return AuthorResult(ok=True, log_id=final.id, text=text, fell_back=False)


def write_author_fallback(db: Session, prep: _AuthorPrep, *, reason: str) -> AuthorResult:
    """LLM 失败时把粗稿 promote 为 author_final。"""
    final = NarrativeLog(
        id=_new_id(), branch_id=prep.drafts[0].branch_id, tick=prep.drafts[0].tick,
        role="author_final", text=prep.draft_text, revision_index=0,
        parent_log_id=prep.drafts[0].id,
    )
    db.add(final); db.commit()
    return AuthorResult(ok=True, log_id=final.id, text=prep.draft_text,
                        reason=reason, fell_back=True)
