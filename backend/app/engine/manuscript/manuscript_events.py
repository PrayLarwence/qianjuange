"""从已切分好的章节里抽事件，作为时间轴草稿。

调用前提：world 已经走过 V1 manuscript_ingest（chunks 已存）。

策略：
- 章节按批（默认 10 章/批）合并，单批一次 LLM 调用拿 events JSON
- 每个事件带 chapter_index、tick（按章顺序自增）、participant_names、location_name
- 把 name 解析回已存在的实体 ID；解析不到的填到 unresolved 字段，用户审阅时知情
- 失败的批次跳过 + warning，不阻塞其他批

输出仅写入 world.manuscript_draft_events，不写 events 表 —— 用户审阅完才落库。
"""
from __future__ import annotations
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ...providers import LLMProvider, Message, get_provider

log = logging.getLogger(__name__)

CHAPTERS_PER_BATCH = 10
MAX_EVENTS_PER_CHAPTER = 6
MAX_TOKENS = 4000
PER_BATCH_CHARS = 30_000


@dataclass
class DraftEvent:
    chapter_index: int
    chapter_title: str
    title: str
    description: str
    participant_names: list[str]
    participant_ids: list[str]      # 解析成功的
    unresolved_names: list[str]     # 解析失败的
    location_name: str
    location_id: str | None
    tick: int                       # 由调用方分配
    causes: list[int] = field(default_factory=list)  # 上游事件的 tick 列表
    source_context: str = ""  # 原文段落片段（审阅时对照用）

    def to_dict(self) -> dict:
        return {
            "chapter_index":     self.chapter_index,
            "chapter_title":     self.chapter_title,
            "title":             self.title,
            "description":       self.description,
            "participant_names": self.participant_names,
            "participant_ids":   self.participant_ids,
            "unresolved_names":  self.unresolved_names,
            "location_name":     self.location_name,
            "location_id":       self.location_id,
            "tick":              self.tick,
            "causes":            list(self.causes),
            "source_context":    self.source_context,
        }


@dataclass
class ExtractResult:
    events: list[DraftEvent] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)



def _chapter_preview(text: str, max_chars: int = 200) -> str:
    """截取章节开头作为审阅对照文本。"""
    if not text: return ""
    t = text.strip()[:max_chars]
    if len(text.strip()) > max_chars: t += "…"
    return t

SYSTEM_PROMPT = """你是文学作品分析师。我会给你一部小说的若干连续章节，请抽出每章发生的关键事件。

输出严格为 JSON 对象，不要任何解释、不要 markdown 代码块包裹：

{
  "events": [
    {
      "chapter_index": 3,
      "title": "8 字以内的事件标题",
      "description": "20-80 字的事件描述：谁做了什么 / 发生了什么",
      "participants": ["人名1", "人名2"],
      "location": "地点名（章里没明说就留空字符串）"
    }
  ]
}

规则：
- 每章 1-6 个事件，按章内时间顺序排
- chapter_index 必须用我标记的「第 N 段」中的 N
- 事件 = 推动故事的具体动作 / 转折 / 揭示。心理描写、场景铺垫不算
- participants 写的人名必须与原文一致；NPC 群体（如「卫兵们」）也算
- location 用具体地名，不要写「房间里」这种泛指
- 不存在的章节、原文里没发生的事，绝对不要编"""


def _build_user_prompt(batch: list[tuple[int, str, str]]) -> str:
    """batch: [(chapter_index, chapter_title, chapter_text)]"""
    parts: list[str] = []
    total_chars = 0
    for idx, title, text in batch:
        head = f"\n### 第 {idx} 段：{title}\n"
        body = text
        remain = PER_BATCH_CHARS - total_chars - len(head)
        if remain <= 200:
            parts.append("\n[…批次内剩余章节因长度限制被截断…]")
            break
        if len(body) > remain:
            body = body[:remain].rstrip() + "\n[…本章因长度限制被截断…]"
        parts.append(head + body)
        total_chars += len(head) + len(body)
    return "".join(parts)


def extract_events(
    *,
    chunks: list[dict],
    name_to_entity_id: dict[str, str],
    location_name_to_id: dict[str, str],
    llm: Optional[LLMProvider] = None,
    on_progress: Callable[[str, int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    chapter_indices: list[int] | None = None,
    on_batch_complete: Callable[[list[DraftEvent]], None] | None = None,
) -> ExtractResult:
    """chunks: [{title, text}] 顺序对应章节 1..N。

    chapter_indices: 1-based 章节号集合；为 None 抽全部，否则只抽这些章节。
    on_batch_complete: 每完成一批就回调一次（增量持久化用）。
    """
    result = ExtractResult()
    if not chunks:
        result.warnings.append("无章节数据")
        return result

    if llm is None:
        try:
            llm = get_provider()
        except Exception as e:
            result.warnings.append(f"未配置 LLM：{e}")
            return result

    name_lookup = _build_name_lookup(name_to_entity_id)
    loc_lookup = _build_name_lookup(location_name_to_id)

    selected: set[int] | None = None
    if chapter_indices is not None:
        selected = {int(i) for i in chapter_indices if 1 <= int(i) <= len(chunks)}
        if not selected:
            result.warnings.append("章节范围为空")
            return result

    items: list[tuple[int, str, str]] = []
    for i, c in enumerate(chunks):
        idx = i + 1
        if selected is not None and idx not in selected:
            continue
        items.append((idx, str(c.get("title") or "")[:120], str(c.get("text") or "")))

    batches: list[list[tuple[int, str, str]]] = [
        items[i:i + CHAPTERS_PER_BATCH] for i in range(0, len(items), CHAPTERS_PER_BATCH)
    ]
    if not batches:
        return result

    next_tick = 1
    for bi, batch in enumerate(batches):
        if cancel_check and cancel_check():
            result.warnings.append("已被取消")
            break
        first_idx = batch[0][0]
        last_idx = batch[-1][0]
        if on_progress:
            on_progress(f"抽取第 {first_idx}-{last_idx} 章", bi, len(batches))

        try:
            resp = llm.chat(
                system=SYSTEM_PROMPT,
                messages=[Message(role="user", content=_build_user_prompt(batch))],
                tools=[],
                max_tokens=MAX_TOKENS,
                temperature=0.3,
                timeout=180.0,
            )
        except Exception as e:
            log.exception("event extract batch %d failed", bi)
            result.warnings.append(f"第 {first_idx}-{last_idx} 章 LLM 调用失败：{e}")
            continue

        parsed = _parse_json_object(resp.text or "")
        if not parsed:
            result.warnings.append(f"第 {first_idx}-{last_idx} 章 LLM 输出非法 JSON")
            continue

        raw_events = parsed.get("events") or []
        if not isinstance(raw_events, list):
            result.warnings.append(f"第 {first_idx}-{last_idx} 章：events 不是数组")
            continue

        # 章号 → 该章已加事件数（限制每章最多 MAX_EVENTS_PER_CHAPTER）
        per_chapter_count: dict[int, int] = {}
        # 按章序聚拢，再按 chapter_index 升序写出
        bucket: dict[int, list[DraftEvent]] = {}
        chapter_titles = {idx: title for idx, title, _ in batch}
        chapter_texts = {idx: text for idx, _, text in batch}

        for raw in raw_events:
            if not isinstance(raw, dict):
                continue
            try:
                ch = int(raw.get("chapter_index"))
            except Exception:
                continue
            if ch not in chapter_titles:
                continue
            if per_chapter_count.get(ch, 0) >= MAX_EVENTS_PER_CHAPTER:
                continue
            per_chapter_count[ch] = per_chapter_count.get(ch, 0) + 1

            title = (raw.get("title") or "").strip()[:80]
            description = (raw.get("description") or "").strip()[:500]
            if not title and not description:
                continue

            participants_raw = raw.get("participants") or []
            participants_names: list[str] = []
            participant_ids: list[str] = []
            unresolved: list[str] = []
            seen_pids: set[str] = set()
            seen_names: set[str] = set()
            if isinstance(participants_raw, list):
                for n in participants_raw:
                    if not isinstance(n, str):
                        continue
                    nm = n.strip()
                    if not nm or nm in seen_names:
                        continue
                    seen_names.add(nm)
                    participants_names.append(nm[:80])
                    eid = name_lookup.get(_norm(nm))
                    if eid and eid not in seen_pids:
                        participant_ids.append(eid)
                        seen_pids.add(eid)
                    elif not eid:
                        unresolved.append(nm[:80])

            location_name = (raw.get("location") or "").strip()[:80]
            location_id = loc_lookup.get(_norm(location_name)) if location_name else None

            bucket.setdefault(ch, []).append(DraftEvent(
                chapter_index=ch,
                chapter_title=chapter_titles[ch],
                title=title or description[:20],
                description=description,
                participant_names=participants_names,
                participant_ids=participant_ids,
                unresolved_names=unresolved,
                location_name=location_name,
                location_id=location_id,
                tick=0,
                source_context=_chapter_preview(chapter_texts.get(ch, "")),
            ))

        batch_events: list[DraftEvent] = []
        for ch in sorted(bucket.keys()):
            for ev in bucket[ch]:
                ev.tick = next_tick
                next_tick += 1
                result.events.append(ev)
                batch_events.append(ev)
        if on_batch_complete and batch_events:
            try:
                on_batch_complete(batch_events)
            except Exception:
                log.exception("on_batch_complete callback failed")

    if on_progress:
        on_progress(f"完成，共 {len(result.events)} 个事件", len(batches), len(batches))
    return result


def _norm(name: str) -> str:
    return re.sub(r"\s+", "", (name or "")).lower()


CAUSAL_SYSTEM_PROMPT = """你是叙事分析师。我会给你一份事件清单（每个事件有 tick 编号、章节、标题、描述），请找出其中存在「因果」关系的事件对。

输出严格为 JSON 对象，不要任何解释、不要 markdown 代码块包裹：

{
  "links": [
    {"cause": 3, "effect": 7, "why": "10 字内的因果说明"}
  ]
}

规则：
- cause 和 effect 都用我提供的 tick 编号
- cause 的 tick 必须 < effect 的 tick
- 只挑剧情上「因为 A 才有了 B」的强因果关系，不要写「时间上 A 先于 B」这种弱关联
- 一个 effect 可以有多个 cause；同一对 (cause, effect) 不要重复
- 宁缺毋滥：清单里如果没有清晰因果就返回空数组
- why 字段写「A 导致 B」式短句，不超过 30 字
"""

CAUSAL_BATCH_EVENTS = 60     # 每批最多看 60 个事件
CAUSAL_LOOKBACK_TICKS = 80    # 因果只在 80 个 tick 内寻找


def extract_causal_links(
    *,
    events: list[DraftEvent],
    llm: Optional[LLMProvider] = None,
    on_progress: Callable[[str, int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[list[tuple[int, int, str]], list[str]]:
    """从已抽好的 draft 事件里挑因果对。

    返回 (links, warnings)，links = [(cause_tick, effect_tick, why), ...]。
    采用滑动窗口分批：每批 CAUSAL_BATCH_EVENTS 个事件，避免单次上下文过长。
    """
    warnings: list[str] = []
    if len(events) < 2:
        return [], warnings

    if llm is None:
        try:
            llm = get_provider()
        except Exception as e:
            warnings.append(f"未配置 LLM，跳过因果链抽取：{e}")
            return [], warnings

    sorted_events = sorted(events, key=lambda e: e.tick)

    # 滑动窗口：每批 CAUSAL_BATCH_EVENTS 个，相邻批重叠一半保证跨批因果不漏
    step = max(1, CAUSAL_BATCH_EVENTS // 2)
    batches: list[list[DraftEvent]] = []
    for i in range(0, len(sorted_events), step):
        b = sorted_events[i:i + CAUSAL_BATCH_EVENTS]
        if len(b) < 2:
            continue
        batches.append(b)
        if i + CAUSAL_BATCH_EVENTS >= len(sorted_events):
            break

    seen: set[tuple[int, int]] = set()
    links: list[tuple[int, int, str]] = []

    for bi, batch in enumerate(batches):
        if cancel_check and cancel_check():
            warnings.append("因果链抽取被取消")
            break
        if on_progress:
            try:
                on_progress(
                    f"分析因果 {batch[0].tick}-{batch[-1].tick}",
                    bi, len(batches),
                )
            except Exception:
                pass

        lines = [f"事件清单（共 {len(batch)} 个）："]
        for ev in batch:
            desc = (ev.description or "")[:120]
            lines.append(f"- tick {ev.tick} · 第{ev.chapter_index}章 · 「{ev.title}」 {desc}")
        prompt = "\n".join(lines)

        try:
            resp = llm.chat(
                system=CAUSAL_SYSTEM_PROMPT,
                messages=[Message(role="user", content=prompt)],
                tools=[],
                max_tokens=2000,
                temperature=0.2,
                timeout=180.0,
            )
        except Exception as e:
            log.exception("causal extract batch %d failed", bi)
            warnings.append(f"因果链批 {bi + 1} LLM 调用失败：{e}")
            continue

        parsed = _parse_json_object(resp.text or "")
        if not parsed:
            warnings.append(f"因果链批 {bi + 1} JSON 解析失败")
            continue

        valid_ticks = {ev.tick for ev in batch}
        raw = parsed.get("links") or []
        if not isinstance(raw, list):
            continue

        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                c = int(item.get("cause"))
                ef = int(item.get("effect"))
            except Exception:
                continue
            if c not in valid_ticks or ef not in valid_ticks:
                continue
            if c >= ef:
                continue
            if ef - c > CAUSAL_LOOKBACK_TICKS:
                continue
            key = (c, ef)
            if key in seen:
                continue
            seen.add(key)
            why = (item.get("why") or "")[:80]
            links.append((c, ef, why))

    if on_progress:
        on_progress(f"因果链 {len(links)} 条", len(batches), len(batches))
    return links, warnings


def _build_name_lookup(mapping: dict[str, str]) -> dict[str, str]:
    """name → id，键统一去空白小写，方便容错匹配。"""
    out: dict[str, str] = {}
    for name, ent_id in mapping.items():
        if not name or not ent_id:
            continue
        out[_norm(name)] = ent_id
    return out


def _parse_json_object(text: str) -> dict | None:
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        s = s.lstrip("`")
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip().rstrip("`").strip()
    start = s.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(s)):
            if s[i] == "{": depth += 1
            elif s[i] == "}":
                depth -= 1
                if depth == 0:
                    candidate = s[start:i + 1]
                    try:
                        return json.loads(candidate)
                    except Exception:
                        break
        start = s.find("{", start + 1)
    return None
