from __future__ import annotations
import json
from typing import Optional
from sqlalchemy.orm import Session
from ..models import World, WorldTemplate, Entity, Event, CausalLink, NarrativeLog, PlotThread


from .executor import active_branch_id


def _entity_full(e: Entity) -> dict:
    """Full entity dict — for API consumers (frontend, export)."""
    return {
        "id": e.id,
        "type": e.type,
        "name": e.name,
        "summary": e.summary,
        "attributes": e.attributes or {},
        "state": e.state or {},
        "location_id": e.location_id,
        "map_x": e.map_x,
        "map_y": e.map_y,
        "target_x": e.target_x,
        "target_y": e.target_y,
        "move_speed": e.move_speed,
        "sim_state": e.sim_state or {},
        "persona": e.persona or {},
        "memories": e.memories or [],
    }


MEMORY_PER_CHAR_LIMIT = 8


def _entity_for_prompt(e: dict, recent_event_ids: Optional[set[str]] = None) -> dict:
    """Compact entity dict — drop empty/null fields to save tokens.

    Takes a dict (from _entity_full) so the same data feeds both API and prompt.
    """
    out: dict = {
        "id": e["id"],
        "type": e["type"],
        "name": e["name"],
    }
    if e.get("summary"):
        out["summary"] = e["summary"]
    if e.get("attributes"):
        out["attributes"] = e["attributes"]
    if e.get("state"):
        out["state"] = e["state"]
    # persona — only for characters, only non-empty fields, so token cost stays low.
    if e.get("type") == "character":
        p = e.get("persona") or {}
        kept = {}
        if p.get("drives"): kept["drives"] = p["drives"]
        if p.get("voice"):  kept["voice"] = p["voice"]
        if p.get("knowledge_blindspots"): kept["knowledge_blindspots"] = p["knowledge_blindspots"]
        if kept:
            out["persona"] = kept
        # Long-term memory — keep only what isn't already in recent_events,
        # so this section is purely additive context (older recall, not duplication).
        mems = e.get("memories") or []
        if mems and recent_event_ids is not None:
            seen_evids: set[str] = set()
            kept_mems: list[dict] = []
            for m in reversed(mems):  # newest first
                if not isinstance(m, dict):
                    continue
                evid = m.get("event_id")
                if evid in recent_event_ids:
                    continue  # already shown in recent_events
                if evid and evid in seen_evids:
                    continue  # dedupe across multiple memory entries for same event
                if evid:
                    seen_evids.add(evid)
                kept_mems.append({
                    "tick": m.get("tick"),
                    "summary": m.get("summary", ""),
                    "certainty": m.get("certainty", "experienced"),
                })
                if len(kept_mems) >= MEMORY_PER_CHAR_LIMIT:
                    break
            if kept_mems:
                out["memories"] = list(reversed(kept_mems))  # back to chronological order
    if e.get("location_id"):
        out["location_id"] = e["location_id"]
    mx, my = e.get("map_x"), e.get("map_y")
    if mx is not None and my is not None:
        out["pos"] = [mx, my]
    tx, ty = e.get("target_x"), e.get("target_y")
    if tx is not None and ty is not None:
        out["target"] = [tx, ty]
        if e.get("move_speed"):
            out["speed"] = e["move_speed"]
    sim = e.get("sim_state") or {}
    status = sim.get("status")
    if status and status != "idle":
        out["status"] = status
        if sim.get("blocked_reason"):
            out["blocked"] = sim["blocked_reason"]
    return out


def _build_map_summary(world_id: str, entities: list[Entity]) -> Optional[dict]:
    """Quick map overview — only included when a map exists."""
    try:
        from . import worldgen
    except Exception:
        return None
    try:
        data = worldgen.load(world_id)
    except Exception:
        return None
    if data is None:
        return None
    w = int(data.get("width", 0))
    h = int(data.get("map_h", 0))
    if w <= 0 or h <= 0:
        return None

    summary: dict = {
        "width": w,
        "height": h,
        "terrain_codes": worldgen.TERRAIN_LABELS,
    }

    # Terrain at each pinned entity, so the LLM sees what they're standing on.
    eff = None
    try:
        eff = worldgen.effective_terrain(data)
    except Exception:
        eff = data.get("terrain")
    if eff is not None:
        positions = []
        for e in entities:
            if e.map_x is None or e.map_y is None:
                continue
            x, y = int(e.map_x), int(e.map_y)
            if not (0 <= x < w and 0 <= y < h):
                continue
            try:
                t = int(eff[y, x])
            except Exception:
                continue
            positions.append({
                "id": e.id,
                "name": e.name,
                "pos": [x, y],
                "terrain": worldgen.TERRAIN_LABELS.get(t, str(t)),
            })
        if positions:
            summary["entities_on_map"] = positions
    return summary


def _load_outline_block(db: Session, world: World) -> Optional[dict]:
    """Pull canonical_outline + outline_progress for prompt rendering.

    Returns None when the world has no template-driven outline. The block
    includes the full beat list, current target index, completed indices,
    and convenience pointers to next/upcoming beats so the LLM doesn't
    have to compute them.
    """
    if not world.template_id:
        return None
    t = db.query(WorldTemplate).filter_by(id=world.template_id).first()
    if t is None:
        return None
    outline = list(t.canonical_outline or [])
    if not outline:
        return None

    progress = world.outline_progress or {}
    current_index = int(progress.get("current_index", 0) or 0)
    completed = sorted({int(i) for i in (progress.get("completed") or [])
                        if isinstance(i, (int, float))})

    beats = []
    for i, b in enumerate(outline):
        beat_text = ""
        if isinstance(b, dict):
            beat_text = (b.get("beat") or b.get("title") or b.get("description") or "").strip()
        elif isinstance(b, str):
            beat_text = b.strip()
        beats.append({"index": i, "beat": beat_text})

    n = len(beats)
    current_index = max(0, min(current_index, n))  # clamp
    return {
        "beats": beats,
        "current_index": current_index,
        "completed": completed,
        "current_beat": beats[current_index] if current_index < n else None,
        "upcoming": beats[current_index:current_index + 3],
        "all_done": current_index >= n,
    }


def build_state_snapshot(db: Session, world: World, max_events: int = 30, max_entities: int = 80) -> dict:
    branch_id = active_branch_id(world)
    entities = db.query(Entity).filter_by(branch_id=branch_id, alive=1).limit(max_entities).all()
    events = (
        db.query(Event)
        .filter_by(branch_id=branch_id, deleted=0)
        .order_by(Event.tick.desc(), Event.created_at.desc())
        .limit(max_events)
        .all()
    )
    event_ids = {e.id for e in events}
    links = db.query(CausalLink).filter_by(branch_id=branch_id).all()
    links_visible = [l for l in links if l.cause_event_id in event_ids or l.effect_event_id in event_ids]
    recent_narration = (
        db.query(NarrativeLog)
        .filter_by(branch_id=branch_id)
        .order_by(NarrativeLog.tick.desc(), NarrativeLog.created_at.desc())
        .limit(5)
        .all()
    )
    snapshot: dict = {
        "world": {
            "id": world.id,
            "name": world.name,
            "description": world.description,
            "outline": world.outline or "",
            "current_tick": world.current_tick,
            "branch_id": branch_id,
            "rules": world.rules or {},
        },
        "entities": [_entity_full(e) for e in entities],
        "recent_events": [
            {
                "id": e.id,
                "tick": e.tick,
                "title": e.title,
                "description": e.description,
                "participants": e.participants or [],
                "location_id": e.location_id,
                "consequences": e.consequences or [],
            }
            for e in reversed(events)
        ],
        "causal_links": [
            {
                "cause": l.cause_event_id,
                "effect": l.effect_event_id,
                "description": l.description,
                "weight": l.weight,
            }
            for l in links_visible
        ],
        "recent_narration": [n.text for n in reversed(recent_narration)],
    }
    map_summary = _build_map_summary(world.id, entities)
    if map_summary is not None:
        snapshot["map"] = map_summary
    outline_block = _load_outline_block(db, world)
    if outline_block is not None:
        snapshot["outline_progress"] = outline_block
    open_threads = (
        db.query(PlotThread)
        .filter_by(branch_id=branch_id, status="open")
        .order_by(PlotThread.opened_tick)
        .all()
    )
    if open_threads:
        snapshot["open_plot_threads"] = [
            {
                "id": t.id,
                "title": t.title,
                "summary": t.summary,
                "opened_tick": t.opened_tick,
                "age_ticks": max(0, world.current_tick - (t.opened_tick or 0)),
                "related_entity_ids": t.related_entity_ids or [],
            }
            for t in open_threads
        ]
    pacing = _compute_pacing_budget(outline_block, len(open_threads))
    if pacing is not None:
        snapshot["pacing_budget"] = pacing
    return snapshot


def _compute_pacing_budget(outline_block: Optional[dict], open_thread_count: int) -> Optional[dict]:
    """Derive a pacing/budget summary for the LLM.

    Logic: when outline_block is present, use beat progress as the time axis.
    The 'tightness' compares remaining beats against open threads — if there
    are more open threads than remaining beats, every remaining beat needs to
    carry thread closure on top of plot advancement.

    Returns None when there's no outline to anchor budget to (no template).
    """
    if outline_block is None:
        if open_thread_count > 0:
            return {
                "level": "untimed",
                "open_threads": open_thread_count,
                "advice": "没有大纲框定结尾，注意不要无限累积钩子。",
            }
        return None

    n = len(outline_block.get("beats") or [])
    cur = int(outline_block.get("current_index") or 0)
    remaining_beats = max(0, n - cur)
    progress_pct = int(round(cur * 100 / n)) if n > 0 else 0

    if outline_block.get("all_done"):
        if open_thread_count > 0:
            level = "endgame"
            advice = (f"大纲已 all_done，但还有 {open_thread_count} 条钩子未收。"
                      "本轮必须用收尾事件兑现这些钩子并 close_plot_thread——"
                      "不要再开新钩子，不要拖延。")
        else:
            level = "done"
            advice = "大纲已 all_done 且无未收钩子，可以从容写收束章节或开放结局。"
    elif remaining_beats <= open_thread_count:
        level = "critical"
        advice = (f"剩 {remaining_beats} 拍要兑现 {open_thread_count} 条钩子——节奏紧迫。"
                  "本轮**优先**用 close_plot_thread 收钩子，**禁止**开新钩子，"
                  "事件设计上应让多条线同步收尾（一个事件兑现多条钩子最理想）。")
    elif progress_pct >= 60 and open_thread_count >= 3:
        level = "tight"
        advice = (f"已推进 {progress_pct}%，还有 {open_thread_count} 条钩子悬着——"
                  "进入收尾阶段。本轮如果有钩子接近兑现条件就主动收，"
                  "新增钩子要克制（仅当大纲明示新伏笔时才开）。")
    elif progress_pct < 30 and open_thread_count == 0:
        level = "early_empty"
        advice = (f"剧情才推进 {progress_pct}%，目前一条钩子也没埋。"
                  "如果接下来的事件里有自然的悬念点（誓言、谜团、未履承诺），"
                  "用 open_plot_thread 显式登记，让故事有线索网。")
    else:
        level = "comfortable"
        advice = f"剧情进度 {progress_pct}%，{open_thread_count} 条钩子在线，节奏宽裕。"

    return {
        "level": level,
        "progress_pct": progress_pct,
        "remaining_beats": remaining_beats,
        "open_threads": open_thread_count,
        "advice": advice,
    }


def _persona_quickref(entities: list[dict]) -> str:
    """A high-attention block listing every character's persona.

    The LLM tends to skim the entities JSON and miss persona buried inside.
    Pulling drives/voice/blindspots up here as a 'cheat sheet' makes them
    show up at top-of-prompt where attention is highest.
    """
    rows = []
    for e in entities:
        if e.get("type") != "character":
            continue
        p = e.get("persona") or {}
        drives = p.get("drives") or []
        voice = (p.get("voice") or "").strip()
        blind = p.get("knowledge_blindspots") or []
        if not (drives or voice or blind):
            continue
        bits = [f"**{e['name']}**（{e['id']}）"]
        if drives: bits.append(f"drives: {', '.join(drives)}")
        if voice:  bits.append(f"voice: {voice}")
        if blind:  bits.append(f"blindspots: {', '.join(blind)}")
        rows.append("- " + "  |  ".join(bits))
    if not rows:
        return ""
    return "\n".join([
        "\n## 角色人格速查（推演时必须遵守 —— 每个事件的言行都要符合当事人的 drives 和 voice，盲区不许使用）",
        *rows,
    ])


def _render_outline_progress(op: dict) -> str:
    """Render the outline progress block as a high-priority prompt section.

    The director needs to know two things:
      1. The full beat list (so it sees where the story is going)
      2. WHICH beat is the current one (so it knows what to push toward this turn)
    """
    beats = op.get("beats") or []
    if not beats:
        return ""

    n = len(beats)
    current_index = op.get("current_index", 0)
    completed = set(op.get("completed") or [])

    lines = ["\n## 剧情进度（结构化大纲，必须按节拍推进）"]

    if op.get("all_done"):
        lines.append(f"全部 {n} 个节拍均已标记完成。可在大纲框架内自由收束剩余支线。")
    else:
        cur = op.get("current_beat") or {}
        cur_text = cur.get("beat") or "（节拍内容为空）"
        lines.append(f"**当前应推进的节拍 #{current_index}：{cur_text}**")
        lines.append("→ 这一回合的事件应当朝这个节拍推进；如果剧情已经满足这个节拍，请生成完成它的事件。")

        upcoming = (op.get("upcoming") or [])[1:]  # skip current
        if upcoming:
            lines.append("\n**接下来 1-2 个节拍（尚未启动，先别越过当前节拍）：**")
            for b in upcoming:
                lines.append(f"  - #{b['index']}  {b['beat']}")

    lines.append(f"\n**完整节拍清单（共 {n} 个）：**")
    for b in beats:
        idx = b["index"]
        if idx in completed:
            mark = "[已完成]"
        elif idx == current_index:
            mark = "[当前]"
        elif idx < current_index:
            mark = "[已跳过]"
        else:
            mark = "[未开始]"
        lines.append(f"  {mark} #{idx}  {b['beat']}")

    return "\n".join(lines)


def state_as_prompt(snapshot: dict) -> str:
    parts = [
        "## 世界状态",
        f"{snapshot['world']['name']} — {snapshot['world']['description']}",
        f"当前 tick: {snapshot['world']['current_tick']}",
    ]
    outline = (snapshot["world"].get("outline") or "").strip()
    if outline:
        parts.append("\n## 世界全貌大纲（必须完整遵循；若提及经典原作则按原作还原，否则按此大纲推演）")
        parts.append(outline)
    op_block = snapshot.get("outline_progress")
    if op_block:
        rendered = _render_outline_progress(op_block)
        if rendered:
            parts.append(rendered)
    if "map" in snapshot:
        m = snapshot["map"]
        parts.append(f"\n## 地图  {m['width']}×{m['height']}")
        parts.append(f"地形编码: {json.dumps(m['terrain_codes'], ensure_ascii=False)}")
        if m.get("entities_on_map"):
            parts.append("当前位于地图上的实体:")
            parts.append(json.dumps(m["entities_on_map"], ensure_ascii=False, indent=2))
    quickref = _persona_quickref(snapshot["entities"])
    if quickref:
        parts.append(quickref)
    recent_event_ids = {ev.get("id") for ev in snapshot.get("recent_events", []) if ev.get("id")}
    parts.append(f"\n## 实体（{len(snapshot['entities'])}）")
    parts.append(json.dumps(
        [_entity_for_prompt(e, recent_event_ids=recent_event_ids) for e in snapshot["entities"]],
        ensure_ascii=False, indent=2,
    ))
    parts.append(f"\n## 近期事件（{len(snapshot['recent_events'])}，按时间升序）")
    parts.append(json.dumps(snapshot["recent_events"], ensure_ascii=False, indent=2))
    parts.append("\n## 因果链")
    parts.append(json.dumps(snapshot["causal_links"], ensure_ascii=False, indent=2))
    if snapshot.get("open_plot_threads"):
        threads = snapshot["open_plot_threads"]
        parts.append(f"\n## 未收的剧情钩子（{len(threads)}）")
        parts.append("这些是你之前埋下、还没兑现的线。每条都是叙事债务，越久不收越显眼。在剩余节奏里要么收，要么明确开放结局。")
        for t in threads:
            age = t.get("age_ticks", 0)
            stale = "（拖了 {} tick 了）".format(age) if age >= 5 else ""
            parts.append(f"- [{t['id']}] {t['title']}{stale}")
            parts.append(f"  {t['summary']}")
    pacing = snapshot.get("pacing_budget")
    if pacing is not None:
        level = pacing.get("level", "")
        emoji = {
            "comfortable": "🟢", "tight": "🟡", "critical": "🔴",
            "endgame": "🔴", "done": "✅", "early_empty": "💡", "untimed": "⚠️",
        }.get(level, "•")
        parts.append(f"\n## 节奏与预算 {emoji}")
        meta_bits = []
        if "progress_pct" in pacing:
            meta_bits.append(f"进度 {pacing['progress_pct']}%")
        if "remaining_beats" in pacing:
            meta_bits.append(f"剩 {pacing['remaining_beats']} 拍")
        meta_bits.append(f"未收钩子 {pacing.get('open_threads', 0)} 条")
        parts.append("状态：" + "  |  ".join(meta_bits))
        parts.append(pacing.get("advice", ""))
    parts.append("\n## 最近叙事")
    parts.append("\n---\n".join(snapshot["recent_narration"]))
    return "\n".join(parts)
