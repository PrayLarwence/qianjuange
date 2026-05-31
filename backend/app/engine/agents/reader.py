"""Reader Agent — 全局连续性守护者。

职责：
1. 每章结束后读新章正文 + 旧状态，更新角色状态表/伏笔追踪/摘要链
2. 产出下一章的 continuity brief（~800 tokens）给 Chapter AI
3. 验证新章是否踩了禁区，不通过时在 brief 里带修补指令

设计原则：
- Reader 持有大上下文（全文摘要链），但只产出小 brief
- 验证和 brief 产出合并为一次 LLM 调用
- 状态持久化到 reader_states 表
"""
from __future__ import annotations
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from ...models import (
    World, Entity, Event, NarrativeLog, PlotThread,
    ChapterMarker, ReaderState,
)
from ...providers import get_provider_for_role
from ...providers.base import LLMProvider, Message
from ..core.executor import active_branch_id

log = logging.getLogger(__name__)


_READER_SYSTEM = """你是一个小说连续性审查员（Reader）。你的任务是：

1. 阅读最新一章的正文
2. 更新你维护的状态表（角色状态、伏笔、禁区）
3. 验证新章是否违反了已有设定
4. 为下一章产出 continuity brief

输出严格 JSON，格式如下：

{
  "validation": {
    "passed": true/false,
    "issues": [
      {"paragraph": "问题段落的前20字...", "problem": "具体问题", "fix_hint": "修补建议"}
    ]
  },
  "updated_characters": [
    {
      "name": "角色名",
      "location": "当前位置",
      "emotion": "当前情绪状态",
      "status": "存活/受伤/失踪等",
      "inventory": ["持有物品"],
      "notes": "其他重要状态变化"
    }
  ],
  "updated_foreshadowing": [
    {"id": "fs_xxx", "description": "伏笔描述", "planted_chapter": 3, "resolved": false}
  ],
  "updated_prohibitions": [
    {"description": "禁区描述", "until_chapter": null}
  ],
  "chapter_summary": "本章50字以内摘要",
  "next_brief": {
    "plot_advance": "下一章要推进的主线节点",
    "character_positions": "已出场角色的当前状态/位置/情绪（简述）",
    "foreshadowing_to_resolve": "需要回收的伏笔（如有）",
    "continuation_point": "与本章的衔接点（最后一个场景/对白/动作）",
    "prohibitions": "不能违反的设定/不能提前揭示的信息"
  }
}

规则：
- validation.passed=false 时必须给出 issues
- 角色状态只列本章有变化的角色
- 伏笔列表是增量更新：新增的标 resolved=false，本章兑现的标 resolved=true
- next_brief 每个字段控制在 2-3 句话以内
- chapter_summary 不超过 50 字"""


def _new_id(prefix: str = "rs") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def get_or_create_reader_state(db: Session, world: World) -> ReaderState:
    branch_id = active_branch_id(world)
    state = db.query(ReaderState).filter_by(branch_id=branch_id).first()
    if state is None:
        state = ReaderState(
            id=_new_id(),
            branch_id=branch_id,
            world_id=world.id,
            character_states=[],
            plot_threads=[],
            chapter_summaries=[],
            foreshadowing=[],
            prohibitions=[],
            last_brief="",
            last_chapter_tick=0,
        )
        db.add(state)
        db.flush()
    return state


def _build_reader_context(
    db: Session, world: World, state: ReaderState, new_chapter_text: str,
) -> str:
    """构建 Reader 的 user prompt：旧状态 + 新章正文。"""
    branch_id = active_branch_id(world)

    parts = []

    # 摘要链（之前所有章节的摘要）
    if state.chapter_summaries:
        parts.append("# 已有章节摘要")
        for cs in state.chapter_summaries[-10:]:  # 最多保留最近 10 章
            parts.append(f"- 第{cs['chapter']}章 (tick {cs.get('tick_range','?')}): {cs['summary']}")

    # 当前角色状态
    if state.character_states:
        parts.append("\n# 当前角色状态")
        for ch in state.character_states:
            line = f"- {ch['name']}: {ch.get('location','?')} | {ch.get('emotion','?')} | {ch.get('status','正常')}"
            if ch.get('inventory'):
                line += f" | 持有: {', '.join(ch['inventory'])}"
            parts.append(line)

    # 未解伏笔
    open_fs = [f for f in (state.foreshadowing or []) if not f.get("resolved")]
    if open_fs:
        parts.append("\n# 未解伏笔")
        for f in open_fs:
            parts.append(f"- [{f['id']}] {f['description']} (第{f.get('planted_chapter','?')}章埋下)")

    # 当前禁区
    if state.prohibitions:
        parts.append("\n# 当前禁区")
        for p in state.prohibitions:
            parts.append(f"- ⚠️ {p['description']}")

    # 世界大纲（精简）
    if world.outline:
        parts.append(f"\n# 世界大纲\n{world.outline[:500]}")

    # 新章正文
    parts.append(f"\n# 新章正文（本章 tick={world.current_tick}）")
    parts.append(new_chapter_text)

    return "\n".join(parts)


def run_reader_review(
    db: Session,
    world: World,
    new_chapter_text: str,
    chapter_number: int = 0,
    *,
    provider: Optional[LLMProvider] = None,
) -> dict:
    """章结束后调用：验证 + 更新状态 + 产出下一章 brief。

    返回:
      {
        "passed": bool,
        "issues": [...],
        "brief": str,  # 格式化的 continuity brief 文本
        "llm_calls": int,
      }
    """
    state = get_or_create_reader_state(db, world)

    if not new_chapter_text.strip():
        return {"passed": True, "issues": [], "brief": state.last_brief or "", "llm_calls": 0}

    llm = provider or get_provider_for_role(world, "reader")
    if llm is None:
        log.warning("reader: no provider available")
        return {"passed": True, "issues": [], "brief": "", "llm_calls": 0}

    user_prompt = _build_reader_context(db, world, state, new_chapter_text)

    try:
        resp = llm.chat(
            system=_READER_SYSTEM,
            messages=[Message(role="user", content=user_prompt)],
            tools=[],
            max_tokens=2048,
            temperature=0.3,
            timeout=60.0,
        )
    except Exception as e:
        log.exception("reader LLM call failed")
        return {"passed": True, "issues": [], "brief": state.last_brief or "", "llm_calls": 1}

    text = (resp.text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        log.warning("reader: LLM output not valid JSON, len=%d", len(text))
        return {"passed": True, "issues": [], "brief": state.last_brief or "", "llm_calls": 1}

    # 更新状态
    validation = data.get("validation", {})
    passed = validation.get("passed", True)
    issues = validation.get("issues", [])

    # 更新角色状态（增量合并）
    updated_chars = data.get("updated_characters", [])
    if updated_chars:
        existing = {ch["name"]: ch for ch in (state.character_states or [])}
        for ch in updated_chars:
            existing[ch["name"]] = ch
        state.character_states = list(existing.values())

    # 更新伏笔
    updated_fs = data.get("updated_foreshadowing", [])
    if updated_fs:
        existing_fs = {f["id"]: f for f in (state.foreshadowing or [])}
        for f in updated_fs:
            if not f.get("id"):
                f["id"] = _new_id("fs")
            existing_fs[f["id"]] = f
        state.foreshadowing = list(existing_fs.values())

    # 更新禁区
    updated_prohibitions = data.get("updated_prohibitions", [])
    if updated_prohibitions:
        state.prohibitions = updated_prohibitions

    # 追加章节摘要
    chapter_summary = data.get("chapter_summary", "")
    if chapter_summary:
        state.chapter_summaries = (state.chapter_summaries or []) + [{
            "chapter": chapter_number or len(state.chapter_summaries or []) + 1,
            "tick_range": f"{state.last_chapter_tick + 1}-{world.current_tick}",
            "summary": chapter_summary,
        }]

    # 格式化 brief
    next_brief_data = data.get("next_brief", {})
    brief_text = _format_brief(next_brief_data, state)
    state.last_brief = brief_text
    state.last_chapter_tick = world.current_tick
    state.updated_at = datetime.utcnow()

    db.flush()

    return {
        "passed": passed,
        "issues": issues,
        "brief": brief_text,
        "llm_calls": 1,
    }


def _format_brief(brief_data: dict, state: ReaderState) -> str:
    """将 Reader 产出的 brief 数据格式化为 Chapter AI 可直接使用的文本。"""
    parts = []

    if brief_data.get("character_positions"):
        parts.append(f"【角色状态】{brief_data['character_positions']}")

    if brief_data.get("foreshadowing_to_resolve"):
        parts.append(f"【待回收伏笔】{brief_data['foreshadowing_to_resolve']}")

    if brief_data.get("prohibitions"):
        parts.append(f"【禁区】{brief_data['prohibitions']}")

    if brief_data.get("continuation_point"):
        parts.append(f"【衔接点】{brief_data['continuation_point']}")

    if brief_data.get("plot_advance"):
        parts.append(f"【本章目标】{brief_data['plot_advance']}")

    return "\n".join(parts)


def get_current_brief(db: Session, world: World) -> str:
    """获取当前 Reader 状态中的 brief，供 Chapter AI 使用。"""
    state = db.query(ReaderState).filter_by(
        branch_id=active_branch_id(world)
    ).first()
    if state and state.last_brief:
        return state.last_brief
    return ""


def build_slim_context(db: Session, world: World) -> str:
    """构建精简上下文（替代 build_state_snapshot 的巨型 JSON）。

    输入给 Director 的上下文从 28k 降到 4-6k：
    - Reader brief (~800 tokens)
    - 上章结尾 (~500 tokens)
    - 世界大纲精简版 (~300 tokens)
    - 当前角色列表（仅名字+一句话状态）(~200 tokens)
    """
    branch_id = active_branch_id(world)
    parts = []

    # Reader brief
    brief = get_current_brief(db, world)
    if brief:
        parts.append(f"# 连续性简报\n{brief}")

    # 上章结尾（最近的 author_final 的最后 500 字）
    last_final = (
        db.query(NarrativeLog)
        .filter(
            NarrativeLog.branch_id == branch_id,
            NarrativeLog.role == "author_final",
        )
        .order_by(NarrativeLog.tick.desc(), NarrativeLog.created_at.desc())
        .first()
    )
    if last_final and last_final.text:
        tail = last_final.text[-500:]
        parts.append(f"# 上章结尾\n...{tail}")

    # 世界大纲（精简）
    if world.outline:
        parts.append(f"# 世界大纲\n{world.outline[:400]}")

    # 角色列表（精简）
    entities = (
        db.query(Entity)
        .filter_by(branch_id=branch_id, type="character")
        .filter(Entity.alive == 1)
        .limit(15)
        .all()
    )
    if entities:
        parts.append("# 当前角色")
        state = db.query(ReaderState).filter_by(branch_id=branch_id).first()
        char_map = {}
        if state and state.character_states:
            char_map = {ch["name"]: ch for ch in state.character_states}
        for e in entities:
            cs = char_map.get(e.name)
            if cs:
                line = f"- {e.name}: {cs.get('location','?')} | {cs.get('emotion','?')} | {cs.get('status','正常')}"
            else:
                line = f"- {e.name}: {e.summary[:40] if e.summary else '(无描述)'}"
            parts.append(line)

    # 未解伏笔（精简）
    open_threads = (
        db.query(PlotThread)
        .filter_by(branch_id=branch_id, status="open")
        .order_by(PlotThread.opened_tick)
        .limit(5)
        .all()
    )
    if open_threads:
        parts.append("# 未解线索")
        for t in open_threads:
            parts.append(f"- {t.title}")

    return "\n\n".join(parts)


_PATCH_SYSTEM = """你是一个小说文本修补助手。你会收到：
1. 一段完整的章节正文
2. 一组需要修补的问题（每个问题包含问题段落定位、问题描述、修补建议）

你的任务是只修改有问题的段落，保持其他段落完全不变。

输出格式：直接输出修补后的完整章节正文。不要加任何解释或标记。"""


def run_patch(
    db: Session,
    world: World,
    original_text: str,
    issues: list[dict],
    *,
    provider: Optional[LLMProvider] = None,
) -> dict:
    """定点修补：只改 Reader 标记的问题段落，不重写全章。

    返回:
      {"patched": bool, "text": str, "llm_calls": int}
    """
    if not issues:
        return {"patched": False, "text": original_text, "llm_calls": 0}

    llm = provider or get_provider_for_role(world, "reader")
    if llm is None:
        return {"patched": False, "text": original_text, "llm_calls": 0}

    issues_text = "\n".join(
        f"- 段落定位：「{iss.get('paragraph', '?')}」\n"
        f"  问题：{iss.get('problem', '?')}\n"
        f"  修补建议：{iss.get('fix_hint', '按设定修正')}"
        for iss in issues
    )

    user_prompt = f"# 原文\n{original_text}\n\n# 需要修补的问题\n{issues_text}"

    try:
        resp = llm.chat(
            system=_PATCH_SYSTEM,
            messages=[Message(role="user", content=user_prompt)],
            tools=[],
            max_tokens=4096,
            temperature=0.3,
            timeout=60.0,
        )
    except Exception as e:
        log.exception("patch LLM call failed")
        return {"patched": False, "text": original_text, "llm_calls": 1}

    patched_text = (resp.text or "").strip()
    if not patched_text or len(patched_text) < len(original_text) * 0.5:
        log.warning("patch: output too short or empty, keeping original")
        return {"patched": False, "text": original_text, "llm_calls": 1}

    return {"patched": True, "text": patched_text, "llm_calls": 1}
