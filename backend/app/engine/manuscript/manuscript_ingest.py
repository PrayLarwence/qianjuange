"""从用户提供的小说手稿反向构建一个世界骨架。

输入：原始小说文本（中文为主，纯文本或 Markdown）。
输出：章节大纲、角色名册、势力 / 地点列表、世界设定描述。

不抽具体事件 / 时间轴 —— 那是 V2 的活。这里只搭骨架，让用户可以在已有作品上继续推演。

调用 LLM 一次（或在文本过长时按段切分多次合并）。失败时降级为只切章节、空 cast。
"""
from __future__ import annotations
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from ...providers import LLMProvider, Message, get_provider

log = logging.getLogger(__name__)

# 单批 LLM 调用最多塞这么多字（中文≈1-1.5 token/字）
PER_BATCH_CHARS = 60_000
# 每批章节数；> 这个就跨批
CHAPTERS_PER_BATCH = 30
MAX_TOKENS = 6000
MAX_CAST = 24
MAX_LOCATIONS = 16
MAX_FACTIONS = 12
MAX_OUTLINE = 200
MAX_ALIASES_PER_CAST = 6

# 章节切分的优先级
_CHAPTER_PATTERNS = [
    re.compile(r"^\s*第\s*[一二三四五六七八九十百千万零〇0-9]+\s*[章回卷部节]\s*[：:\s]?.*$", re.MULTILINE),
    re.compile(r"^\s*[Cc]hapter\s+\d+\b.*$", re.MULTILINE),
    re.compile(r"^\s*#{1,3}\s+.+$", re.MULTILINE),
]
# 至少要有这么多章才算"分章成功"；不够就走按字数切
_MIN_CHAPTERS_FOR_CHAPTER_MODE = 3
# 按字数切分时每段最大字数
_CHUNK_CHARS = 5_000


@dataclass
class Chunk:
    title: str
    text: str


@dataclass
class IngestResult:
    chunks: list[Chunk] = field(default_factory=list)
    outline: list[dict] = field(default_factory=list)   # [{index, title, summary}]
    cast: list[dict] = field(default_factory=list)      # [{name, role, summary, tags}]
    locations: list[dict] = field(default_factory=list) # [{name, summary}]
    factions: list[dict] = field(default_factory=list)  # [{name, summary}]
    setting: str = ""
    warnings: list[str] = field(default_factory=list)


def split_into_chapters(text: str, *, max_chunks: int = MAX_OUTLINE) -> list[Chunk]:
    """按常见章节标题切分。找不到标题就按 3+ 空行切。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    matches: list[tuple[int, int, str]] = []  # (start, end, title)
    for pat in _CHAPTER_PATTERNS:
        ms = list(pat.finditer(text))
        if len(ms) >= _MIN_CHAPTERS_FOR_CHAPTER_MODE:
            for m in ms:
                title = m.group(0).strip()[:120]
                if re.search(r'[）\)]', title):
                    continue
                matches.append((m.start(), m.end(), title))
            break

    chunks: list[Chunk] = []
    if matches:
        matches.sort(key=lambda x: x[0])
        for i, (start, end, title) in enumerate(matches):
            body_start = end
            body_end = matches[i + 1][0] if i + 1 < len(matches) else len(text)
            body = text[body_start:body_end].strip()
            if body or i == 0:
                chunks.append(Chunk(title=title[:120], text=body))
    else:
        # 无明显章节 —— 按 3 行以上空行切
        parts = re.split(r"\n\s*\n\s*\n+", text.strip())
        for i, p in enumerate(parts):
            p = p.strip()
            if not p:
                continue
            first_line = p.split("\n", 1)[0].strip()
            title = first_line[:60] if len(first_line) <= 60 else f"片段 {i + 1}"
            chunks.append(Chunk(title=title, text=p))

    if len(chunks) < _MIN_CHAPTERS_FOR_CHAPTER_MODE and len(text) > _CHUNK_CHARS * 2:
        chunks = _chunk_by_length(text, _CHUNK_CHARS, max_chunks)

    if len(chunks) > max_chunks:
        chunks = chunks[:max_chunks]
    return chunks



def _chunk_by_length(text: str, chunk_chars: int, max_chunks: int) -> list[Chunk]:
    """按字数切分，在段落边界断开。"""
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_len = 0
    idx = 0

    def flush():
        nonlocal idx
        if buf:
            idx += 1
            preview = buf[0][:40]
            chunks.append(Chunk(
                title=f"片段 {idx}：{preview}" if len(buf[0])>40 else f"片段 {idx}：{preview}",
                text="\n".join(buf)))
            buf.clear()
            nonlocal buf_len
            buf_len = 0

    for p in paragraphs:
        if buf_len + len(p) > chunk_chars and buf:
            flush()
        buf.append(p)
        buf_len += len(p)

    flush()
    return chunks[-max_chunks:] if max_chunks > 0 else chunks



SYSTEM_PROMPT = """你是文学作品分析师。我会给你一部小说的若干章节（可能是全书也可能是其中一段），请反推作者构造的世界骨架。

输出严格为一个 JSON 对象，不要任何解释、不要 markdown 代码块包裹。结构：

{
  "setting": "200 字以内的世界设定速写：时空背景、核心规则、整体氛围",
  "outline": [
    {"index": 1, "title": "章节标题", "summary": "30-80 字的章节概要，只写发生了什么"}
  ],
  "cast": [
    {
      "name": "角色的标准称呼（取最常用的全名或本名）",
      "aliases": ["小李", "李队长", "老李"],   // 同一人在原文里出现的所有别名 / 称呼 / 昵称（不含 name 本身）；没有就 []
      "role": "主角 | 配角 | 反派 | 龙套",
      "summary": "30-80 字：身份、性格、在故事里的核心定位",
      "tags": ["我方", "敌人", "宠物", "导师", ...]   // 0-4 个，故事内功能性标签
    }
  ],
  "locations": [{"name": "地名", "summary": "20-50 字描述"}],
  "factions":  [{"name": "势力名", "summary": "20-50 字描述"}]
}

规则：
- 只写文中明确出现或强烈暗示的内容，绝不杜撰
- name 必须用原文用词，不要翻译或同义改写
- aliases 必须穷举：原文里凡是指代同一人的「另一种叫法」都要列出（例如「李明 / 小李 / 李队长 / 老李」要选一个做 name，其余全进 aliases）。这个字段决定后续事件抽取能不能正确归并人物，请尽量完整
- cast 按重要性排序，主角放最前；最多 24 人；龙套不要进
- outline 一章一条，按出现顺序，章节 index 用我标在每段开头的「第 N 段」编号
- 如果某项信息原文不足，对应数组留空。宁缺毋滥
"""


def _user_prompt(world_name: str, chunks: list[Chunk], chunk_offset: int) -> str:
    """chunk_offset: 这批 chunks 在全书里的起始章节（0-based）。
    传给 LLM 的 index 用绝对编号，方便跨批合并 outline。"""
    parts = [f"## 作品名：{world_name}", "", "下面是按章节分好的原文（可能已截断）："]
    total = 0
    for i, c in enumerate(chunks):
        absolute_idx = chunk_offset + i + 1
        head = f"\n### 第 {absolute_idx} 段：{c.title}\n"
        body = c.text
        remain = PER_BATCH_CHARS - total - len(head)
        if remain <= 100:
            parts.append("\n[…后续章节因长度限制被截断…]")
            break
        if len(body) > remain:
            body = body[:remain].rstrip() + "\n[…本章因长度限制被截断…]"
        parts.append(head + body)
        total += len(head) + len(body)
    return "\n".join(parts)


def _make_batches(chunks: list[Chunk]) -> list[tuple[int, list[Chunk]]]:
    """把 chunks 按 PER_BATCH_CHARS / CHAPTERS_PER_BATCH 双约束切成批。
    返回 [(offset, chunks), ...]，offset 是该批起始章节 0-based 偏移。"""
    out: list[tuple[int, list[Chunk]]] = []
    i = 0
    n = len(chunks)
    while i < n:
        cur: list[Chunk] = []
        cur_chars = 0
        j = i
        while j < n and len(cur) < CHAPTERS_PER_BATCH:
            c = chunks[j]
            head_chars = len(c.title) + 30
            body_chars = len(c.text)
            if cur and cur_chars + head_chars + body_chars > PER_BATCH_CHARS:
                break
            cur.append(c)
            cur_chars += head_chars + body_chars
            j += 1
        if not cur:
            cur = [chunks[i]]
            j = i + 1
        out.append((i, cur))
        i = j
    return out


def ingest_manuscript(
    *,
    world_name: str,
    text: str,
    llm: Optional[LLMProvider] = None,
    on_progress: Optional[Any] = None,
) -> IngestResult:
    result = IngestResult()
    if not text or not text.strip():
        result.warnings.append("手稿为空")
        return result

    result.chunks = split_into_chapters(text)
    if not result.chunks:
        result.warnings.append("无法切分章节")
        return result

    # 先把 outline 用章节标题填上，保证 LLM 失败也有骨架
    result.outline = [
        {"index": i + 1, "title": c.title, "summary": ""}
        for i, c in enumerate(result.chunks)
    ]

    if llm is None:
        try:
            llm = get_provider()
        except Exception as e:
            result.warnings.append(f"未配置 LLM：{e}（已生成空骨架，章节标题已保留）")
            return result

    batches = _make_batches(result.chunks)
    if len(batches) > 1:
        result.warnings.append(f"原文较长，分 {len(batches)} 批 LLM 分析")

    cast_acc: dict[str, dict] = {}      # 标准 name → cast dict
    cast_alias_owner: dict[str, str] = {}  # 别名（含本名）→ 标准 name
    locations_acc: dict[str, dict] = {}
    factions_acc: dict[str, dict] = {}
    setting_parts: list[str] = []

    for bi, (offset, batch) in enumerate(batches):
        if on_progress:
            try:
                on_progress(f"分析批次 {bi + 1}/{len(batches)}（第 {offset + 1}-{offset + len(batch)} 章）", bi, len(batches))
            except Exception:
                pass

        user_prompt = _user_prompt(world_name, batch, offset)

        try:
            resp = llm.chat(
                system=SYSTEM_PROMPT,
                messages=[Message(role="user", content=user_prompt)],
                tools=[],
                max_tokens=MAX_TOKENS,
                temperature=0.3,
                timeout=240.0,
            )
        except Exception as e:
            log.exception("manuscript ingest llm call failed at batch %d", bi)
            result.warnings.append(f"第 {bi + 1} 批 LLM 调用失败：{e}")
            continue

        parsed = _parse_json_object(resp.text or "")
        if not parsed:
            result.warnings.append(f"第 {bi + 1} 批 LLM 输出无法解析")
            continue

        seg_setting = (parsed.get("setting") or "").strip()
        if seg_setting:
            setting_parts.append(seg_setting)

        # outline：合并到 result.outline 里对应 absolute index
        llm_outline = parsed.get("outline") or []
        if isinstance(llm_outline, list):
            for item in llm_outline:
                if not isinstance(item, dict):
                    continue
                idx = int(item.get("index") or 0)
                summ = (item.get("summary") or "").strip()
                if 1 <= idx <= len(result.outline) and summ and not result.outline[idx - 1]["summary"]:
                    result.outline[idx - 1]["summary"] = summ[:300]

        # cast：按 name 合并 + alias 归属（早出现的优先做标准名）
        for item in _normalize_cast(parsed.get("cast")):
            name = item["name"]
            aliases = item.get("aliases") or []

            existing_owner = cast_alias_owner.get(name)
            owner = existing_owner or name
            if owner not in cast_acc:
                cast_acc[owner] = {**item, "name": owner, "aliases": list(aliases)}
                cast_alias_owner[owner] = owner
            else:
                target = cast_acc[owner]
                if not target.get("summary") and item.get("summary"):
                    target["summary"] = item["summary"]
                if not target.get("role") and item.get("role"):
                    target["role"] = item["role"]
                for t in item.get("tags") or []:
                    if t not in (target.get("tags") or []):
                        target.setdefault("tags", []).append(t)
                        if len(target["tags"]) >= 5:
                            break
            for a in aliases:
                if a and a != owner:
                    cast_alias_owner.setdefault(a, owner)
                    if a not in cast_acc[owner]["aliases"]:
                        cast_acc[owner]["aliases"].append(a)

        for item in _normalize_named_list(parsed.get("locations"), MAX_LOCATIONS):
            locations_acc.setdefault(item["name"], item)
        for item in _normalize_named_list(parsed.get("factions"), MAX_FACTIONS):
            factions_acc.setdefault(item["name"], item)

    if setting_parts:
        result.setting = setting_parts[0][:1000]

    cast_list = list(cast_acc.values())[:MAX_CAST]
    for c in cast_list:
        c["aliases"] = (c.get("aliases") or [])[:MAX_ALIASES_PER_CAST]
    result.cast = cast_list
    result.locations = list(locations_acc.values())[:MAX_LOCATIONS]
    result.factions = list(factions_acc.values())[:MAX_FACTIONS]

    return result


def _normalize_cast(raw: Any) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    seen_names: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = (item.get("name") or "").strip()
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        role = (item.get("role") or "").strip()
        summary = (item.get("summary") or "").strip()[:400]

        aliases_raw = item.get("aliases") or []
        aliases: list[str] = []
        seen_aliases: set[str] = {name}
        if isinstance(aliases_raw, list):
            for a in aliases_raw:
                if not isinstance(a, str):
                    continue
                v = a.strip()[:80]
                if not v or v in seen_aliases:
                    continue
                seen_aliases.add(v)
                aliases.append(v)
                if len(aliases) >= MAX_ALIASES_PER_CAST:
                    break

        tags_raw = item.get("tags") or []
        tags: list[str] = []
        seen_tags: set[str] = set()
        if role:
            t = role[:32]
            tags.append(t)
            seen_tags.add(t)
        if isinstance(tags_raw, list):
            for t in tags_raw:
                if not isinstance(t, str):
                    continue
                v = t.strip()[:32]
                if not v or v in seen_tags:
                    continue
                seen_tags.add(v)
                tags.append(v)
                if len(tags) >= 5:
                    break
        out.append({"name": name[:80], "role": role[:32], "summary": summary, "tags": tags, "aliases": aliases})
        if len(out) >= MAX_CAST:
            break
    return out


def _normalize_named_list(raw: Any, max_n: int) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        if isinstance(item, str):
            name = item.strip()
            summary = ""
        elif isinstance(item, dict):
            name = (item.get("name") or "").strip()
            summary = (item.get("summary") or "").strip()[:300]
        else:
            continue
        if not name or name in seen:
            continue
        seen.add(name)
        out.append({"name": name[:80], "summary": summary})
        if len(out) >= max_n:
            break
    return out


def _parse_json_object(text: str) -> Optional[dict]:
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
            if s[i] == "{":
                depth += 1
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


def render_outline_text(outline: list[dict]) -> str:
    """大纲数组 → 写入 World.outline 的纯文本。"""
    lines: list[str] = []
    for o in outline:
        idx = o.get("index", 0)
        title = (o.get("title") or "").strip()
        summary = (o.get("summary") or "").strip()
        head = f"{idx}. {title}" if title else f"{idx}."
        if summary:
            lines.append(f"{head}\n   {summary}")
        else:
            lines.append(head)
    return "\n".join(lines)
