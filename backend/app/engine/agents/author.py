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
import re
from dataclasses import dataclass
from typing import Optional
from sqlalchemy.orm import Session

from ...models import World, NarrativeLog, Entity, Event, StyleProfile
from ...providers import get_provider_for_role
from ...providers.base import LLMProvider, Message

log = logging.getLogger(__name__)


# 输出长度的健康度阈值。Author 输出过短/过长一般是模型抽风，回落用粗稿。
MIN_OUTPUT_RATIO = 0.4   # 不少于粗稿总长 40%
MAX_OUTPUT_RATIO = 5.0   # 不多于粗稿总长 5 倍
_SHORT_DRAFT_THRESHOLD = 80  # 短粗稿（<80字）允许更高倍率
_SHORT_DRAFT_MAX_RATIO = 8.0
MAX_RECENT_FINAL_CHARS = 2400  # 喂给 Author 的最近定稿历史窗口
MIN_SAMPLE_CHARS = 2000  # 风格样本下限
MAX_SAMPLE_CHARS = 6000  # 风格样本上限（防 prompt 暴涨）
SAMPLE_RATIO = 0.8       # 样本预算 = draft_len * SAMPLE_RATIO，夹在上下限之间
AUTHOR_MAX_TOKENS = 8192  # Author LLM 输出 token 上限
AUTHOR_RETRY = 2  # LLM 调用失败时最多重试次数
MAX_REVISIONS = 2        # 自修循环最多几轮（0=不自修，只写一稿）


@dataclass
class AuthorResult:
    ok: bool
    log_id: Optional[str] = None
    text: str = ""
    reason: str = ""  # 失败 / 跳过原因
    fell_back: bool = False  # True 表示走了"粗稿 promote 为定稿"的回落分支
    llm_calls: int = 0  # 本次 author 阶段实际消耗的 LLM 调用次数


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


_MD_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)


def _strip_markdown_headings(text: str) -> str:
    """Remove markdown heading markers from narration text."""
    return _MD_HEADING_RE.sub("", text)


def _resolve_style(db: Session, world: World) -> Optional[StyleProfile]:
    sid = (world.style_profile_id or "").strip()
    if not sid:
        return None
    return db.query(StyleProfile).filter_by(id=sid).first()


def _default_style():
    """无风格 profile 时的最小替代。启用默认反 AI 规则。"""
    from ..worldgen.style_seeds import DEFAULT_NEGATIVE_RULES

    class _MinimalStyle:
        spec_text = "自然、简洁、有节奏感的叙事文字。避免华丽辞藻堆砌，以白描为主，偶尔点缀一个精准的细节。"
        sample_paragraphs = []
        negative_rules = list(DEFAULT_NEGATIVE_RULES)
    return _MinimalStyle()


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


def _build_negative_section(negative_rules: list | None) -> str:
    """从结构化 negative_rules 构建反提示词 section。只包含 enabled=True 的条目。"""
    rules = negative_rules or []
    enabled = [r for r in rules if isinstance(r, dict) and r.get("enabled", True)]
    if not enabled:
        return ""
    lines = ["# 文本质感要求（反 AI 腔）", "你的输出必须读起来像人类作家写的，不像 AI 生成的。以下是绝对禁止的模式："]
    for r in enabled:
        lines.append(f"- 【{r['label']}】{r['description']}")
    lines.append("")
    lines.append("取而代之：用具体感官细节代替抽象情绪词；让节奏服务于内容；对白要有个人语言习惯；允许留白。")
    lines.append("")
    return "\n".join(lines)


def _build_prompt(
    style: StyleProfile,
    long_memory: str,
    recent_finals: str,
    persona_block: str,
    events_text: str,
    draft_text: str,
    reflection_block: str = "",
) -> tuple[str, str]:
    """返回 (system, user) 两段 prompt。"""
    sample_budget = max(MIN_SAMPLE_CHARS, min(MAX_SAMPLE_CHARS, int(len(draft_text) * SAMPLE_RATIO)))
    sample_text = ""
    samples = style.sample_paragraphs or []
    if isinstance(samples, list) and samples:
        bits = []
        total = 0
        for s in samples:
            if isinstance(s, dict):
                title = s.get("title", "")
                text = s.get("text", "")
                if not text:
                    continue
                fragment = f"### {title}\n{text}" if title else text
            elif isinstance(s, str):
                fragment = s
            else:
                continue
            if total + len(fragment) > sample_budget and bits:
                break
            bits.append(fragment)
            total += len(fragment)
        sample_text = "\n\n".join(bits)

    negative_section = _build_negative_section(style.negative_rules)

    system = f"""你是一名小说家。请按下面的风格规范，把用户给你的"剧情粗稿"改写为小说级正文。

# 风格规范
{style.spec_text or '(无 spec)'}

# 风格示例（最重要的参考——你的输出在句法、词汇、节奏上要与之一致）
{sample_text or '(无样例)'}

{negative_section}
# 改写纪律
1. **不要新增事件和角色**：粗稿里没有的情节事件、没出现的角色，不要凭空加。但你可以——也应该——在微观层面调整表达的颗粒度：
   - 给对白加口癖、废话、打断、犹豫、重复（让人物说话像真人）
   - 删掉过于工整的情绪总结句（"他终于明白了……"这种）
   - 把功能性对白拆成更自然的节奏（一句推进剧情的话可以拆成三句，中间夹杂无意义的动作）
   - 加入不服务剧情的微小动作和感官细节（撕纸、摸杯子、听到远处的声音）
2. **不要改变事件走向**：发生了什么不能改，怎么发生的可以改
3. **可以删减啰嗦**：粗稿往往啰嗦，按风格要求的节奏可以合并/删减
4. **可以重排顺序**：为了节奏可以打乱粗稿内部段落顺序，但要保持因果通顺
5. **必须打破公式化骨架**：粗稿常有"叙述→对白→反应"或"起因→经过→总结"的重复结构。你有权也有义务重组段落形态：
   - 合并多个短段为一个长段（紧张时不给读者喘息）
   - 把一个匀称段拆成一长一短（短段制造停顿）
   - 删掉每段末尾的情绪收束句——让段落断在动作或感官上
   - 让某些段只有对白、某些段只有环境、某些段只有内心——不必每段三层面齐全
   - 如果粗稿所有段落长度相近，你必须制造长短交替
6. **保持人物口吻**：参考下面的角色 persona，对白和心理要符合各自人格

# 对比示例（坏 → 好）
以下展示最常见的 AI 腔问题和修正方向：

❌ 她感到一阵深深的悲伤，眼眶不由自主地湿润了。
✅ 她站了一会儿，手指无意识地攥紧了门把手。
（用具体动作代替情绪标签）

❌ "我们必须立刻行动，"他语气坚定地说，"否则一切都将来不及。"
✅ "走吧。"他没看她。
（对白不必每句都推进剧情、不必每句都配说话方式描写）

❌ 夜风——带着几分凉意的夜风——从半开的窗户灌进来，吹动了桌上那张已经泛黄的信纸。
✅ 风从窗缝进来。桌上的信纸动了一下。
（一个细节就够，不要堆砌修饰）

# 致命 AI 腔特征（出现任何一条就是失败的改写）
你最大的敌人不是"写得不好"，而是"写得像 AI"。以下是最致命的 LLM 指纹，你必须主动消除：
- **破折号癖**：一段里最多 1 个"——"。多余的改用逗号、句号断开，或删掉插入内容。
- **感官细节堆砌**：不要每个动作都配精心设计的感官修饰。"她推开门"不需要变成"被人用手掌稳稳推开的门"。一段最多一个亮点细节，其余白描。
- **信息密度过高的对白**：如果每句对白都在推进剧情或揭示信息，就是假的。允许废话、重复、答非所问。"""

    user_parts = []
    if long_memory:
        user_parts.append(f"# 全书印象\n{long_memory}")
    if recent_finals:
        user_parts.append(f"# 最近章节定稿（你之前的输出，保持风格连贯）\n{recent_finals}")
    if persona_block:
        user_parts.append(f"# 本回合涉及角色\n{persona_block}")
    if reflection_block:
        user_parts.append(reflection_block)
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

    text, reason, init_calls = call_author_llm_once(llm, prep, temperature=0.85)
    if text is None:
        result = write_author_fallback(db, prep, reason=reason)
        result.llm_calls = init_calls
        return result

    from .style_lint import lint_text, format_lint_feedback
    lint_result = lint_text(text)
    lint_calls = 0
    if not lint_result.passed:
        log.info("style_lint failed (score=%d), triggering revision before self-review", lint_result.score)
        feedback = format_lint_feedback(lint_result)
        revised = _revise_with_feedback(llm, text, feedback, prep)
        lint_calls = 1
        if revised:
            text = revised

    has_custom_rules = any(
        r.get("enabled", True) for r in (prep.style.negative_rules or []) if isinstance(r, dict)
    )
    if lint_result.passed and not has_custom_rules:
        rev_calls = 0
    else:
        text, rev_calls = _run_self_revision_loop(llm, text, prep)

    result = write_author_final(db, prep, text)
    result.llm_calls = init_calls + lint_calls + rev_calls
    return result


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
        style = _default_style()

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

    from ..reflection import build_reflection_block
    refl_block = build_reflection_block(db, world.id, "author")

    system, user = _build_prompt(
        style=style,
        long_memory=long_memory,
        recent_finals=recent_finals,
        persona_block=persona_block,
        events_text=events_text,
        draft_text=draft_text,
        reflection_block=refl_block,
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
) -> tuple[Optional[str], str, int]:
    """单次 LLM 调用 + 长度健康度校验（含重试）。

    返回 (text, reason, llm_calls)：
      - 成功：(text, "ok", calls_made)
      - 失败：(None, reason, calls_made)
    无 DB 写入。

    system_prompt_extra: 在共享 system prompt 末尾追加的额外指令（多 author 投票时
    每个 author 用自己的 extra 制造分工/风格差异）。
    """
    system = prep.system_prompt
    if system_prompt_extra and system_prompt_extra.strip():
        system = system + "\n\n# 本 author 的额外指令\n" + system_prompt_extra.strip()

    draft_len = max(1, len(prep.draft_text))
    max_tok = max(AUTHOR_MAX_TOKENS, int(draft_len * 1.5))

    last_reason = ""
    calls_made = 0
    for attempt in range(1 + AUTHOR_RETRY):
        calls_made += 1
        try:
            resp = llm.chat(
                system=system,
                messages=[Message(role="user", content=prep.user_prompt)],
                tools=[],
                max_tokens=max_tok,
                temperature=temperature,
                timeout=120.0,
            )
        except Exception as e:
            last_reason = f"llm error: {e}"
            log.warning("author LLM call failed (attempt %d/%d): %s", attempt + 1, 1 + AUTHOR_RETRY, e)
            continue

        text = (resp.text or "").strip()
        if not text:
            last_reason = "empty output"
            continue

        ratio = len(text) / draft_len
        max_ratio = _SHORT_DRAFT_MAX_RATIO if draft_len < _SHORT_DRAFT_THRESHOLD else MAX_OUTPUT_RATIO
        if ratio < MIN_OUTPUT_RATIO or ratio > max_ratio:
            last_reason = f"length anomaly (ratio={ratio:.2f})"
            log.info("author output length suspicious (ratio=%.2f, attempt %d); rejecting", ratio, attempt + 1)
            continue
        return text, "ok", calls_made

    return None, last_reason, calls_made


_SELF_REVIEW_SYSTEM = """你是一名严格的文学编辑。你会收到一段小说正文和一组质量规则。
你的任务：
1. 逐条检查规则，找出正文中违反的地方（引用原文片段）
2. 额外检查以下 AI 文字指纹（即使不在规则列表里也必须检查）：
   - 每个动作都配感官修饰（细节堆砌）
   - 每句对白都在推进剧情（缺乏废话和自然节奏）
3. 如果没有明显违反，回复"PASS"（仅这四个字母，不要多写）
4. 如果有违反，列出问题（每条一行，格式："- 【规则名】：引用片段 → 问题说明"），然后空一行写"需要修改"

只做诊断，不要改写正文。"""

_REVISE_SYSTEM = """你是一名小说家。你刚写了一稿，编辑给了修改意见。
请根据编辑意见修改你的正文，直接输出修改后的完整正文。
不要解释你改了什么，不要写元话语，不要用 markdown 标题。"""


def _self_review(
    llm: LLMProvider,
    text: str,
    prep: _AuthorPrep,
) -> Optional[str]:
    """让 LLM 自审一稿，返回诊断意见。返回 None 表示通过（PASS）或调用失败。"""
    rules = prep.style.negative_rules or []
    enabled = [r for r in rules if isinstance(r, dict) and r.get("enabled", True)]

    rules_parts = []
    if enabled:
        rules_parts.append("\n".join(f"- 【{r['label']}】{r['description']}" for r in enabled))
    rules_parts.append(
        '- 【感官堆砌】每个动作都配精心设计的感官修饰\n'
        '- 【对白过密】每句对白都在推进剧情，缺乏自然废话'
    )
    rules_text = "\n".join(rules_parts)
    user_msg = f"# 质量规则\n{rules_text}\n\n# 待审正文\n{text}"

    try:
        resp = llm.chat(
            system=_SELF_REVIEW_SYSTEM,
            messages=[Message(role="user", content=user_msg)],
            tools=[],
            max_tokens=1024,
            temperature=0.3,
            timeout=45.0,
        )
    except Exception as e:
        log.debug("author self-review call failed: %s", e)
        return None

    feedback = (resp.text or "").strip()
    if not feedback or feedback.upper().startswith("PASS") or "需要修改" not in feedback:
        return None
    return feedback


def _revise_with_feedback(
    llm: LLMProvider,
    text: str,
    feedback: str,
    prep: _AuthorPrep,
    temperature: float = 0.7,
) -> Optional[str]:
    """根据自审意见改稿。返回改后文本，失败返回 None。"""
    user_msg = f"# 你的上一稿\n{text}\n\n# 编辑意见\n{feedback}\n\n请输出修改后的完整正文。"
    draft_len = max(1, len(prep.draft_text))
    max_tok = max(AUTHOR_MAX_TOKENS, int(draft_len * 1.5))
    try:
        resp = llm.chat(
            system=_REVISE_SYSTEM,
            messages=[Message(role="user", content=user_msg)],
            tools=[],
            max_tokens=max_tok,
            temperature=temperature,
            timeout=120.0,
        )
    except Exception as e:
        log.debug("author revision call failed: %s", e)
        return None

    revised = (resp.text or "").strip()
    if not revised:
        return None

    ratio = len(revised) / draft_len
    max_ratio = _SHORT_DRAFT_MAX_RATIO if draft_len < _SHORT_DRAFT_THRESHOLD else MAX_OUTPUT_RATIO
    if ratio < MIN_OUTPUT_RATIO or ratio > max_ratio:
        log.info("author revision length suspicious (ratio=%.2f); keeping previous", ratio)
        return None
    return revised


def _run_self_revision_loop(
    llm: LLMProvider,
    text: str,
    prep: _AuthorPrep,
    max_revisions: int = MAX_REVISIONS,
) -> tuple[str, int]:
    """写→审→改循环。返回 (最终文本, LLM调用次数)。"""
    current = text
    calls = 0
    for i in range(max_revisions):
        calls += 1  # _self_review
        feedback = _self_review(llm, current, prep)
        if feedback is None:
            log.debug("author self-review pass at revision %d", i)
            break
        log.info("author self-review round %d found issues, revising", i + 1)
        calls += 1  # _revise_with_feedback
        revised = _revise_with_feedback(llm, current, feedback, prep)
        if revised is None:
            break
        current = revised
    return current, calls


def write_author_final(db: Session, prep: _AuthorPrep, text: str) -> AuthorResult:
    """把成功输出落库为 author_final。"""
    text = _strip_markdown_headings(text)
    final = NarrativeLog(
        id=_new_id(), branch_id=prep.drafts[0].branch_id, tick=prep.drafts[0].tick,
        role="author_final", text=text, revision_index=0,
        parent_log_id=prep.drafts[0].id,
    )
    db.add(final); db.commit()
    return AuthorResult(ok=True, log_id=final.id, text=text, fell_back=False)


def write_author_fallback(db: Session, prep: _AuthorPrep, *, reason: str) -> AuthorResult:
    """LLM 失败时不再 promote 粗稿为 author_final，避免事件流泄漏到手稿。"""
    log.warning("author fallback: %s (tick=%d, draft_len=%d)",
                reason, prep.drafts[0].tick, len(prep.draft_text))
    return AuthorResult(ok=True, log_id=None, text=prep.draft_text,
                        reason=reason, fell_back=True)
