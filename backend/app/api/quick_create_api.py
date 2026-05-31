"""快速创建世界 API。

一个端点搞定：用户给 genre + 一段话描述，后端用 LLM 生成大纲和角色，
自动绑定匹配的风格档案，返回可以直接推演的 world_id。
"""
from __future__ import annotations
import json
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..models import get_db, World, Branch, Entity, StyleProfile
from ..providers import get_provider
from ..providers.base import LLMResponse, Message
from ._common import _new_id

log = logging.getLogger(__name__)
router = APIRouter()

GENRE_STYLE_MAP = {
    "文学": "style_serious_lit",
    "网文": "style_webnovel",
    "武侠": "style_jinyong",
    "仙侠": "style_xianxia",
    "奇幻": "style_western_fantasy",
    "科幻": "style_hard_scifi",
    "赛博": "style_cyberpunk",
    "悬疑": "style_mystery",
}

_SYSTEM = """你是一个小说世界构建助手。用户会给你一个类型标签和一段简短描述，
你需要生成一个完整的世界设定，包括大纲和主要角色。

输出严格 JSON，格式如下（不要输出其他内容）：
{
  "name": "世界名称（如果用户没给就根据描述起一个）",
  "outline": "3-5 段的故事大纲，包含开端、发展方向、核心冲突",
  "characters": [
    {
      "name": "角色名",
      "summary": "一句话介绍",
      "persona": {
        "drives": ["核心驱动力1", "核心驱动力2"],
        "voice": "说话风格描述",
        "blindspots": ["认知盲区"]
      }
    }
  ]
}

要求：
- 角色 3-5 个，有主角有配角有对手
- 大纲要有明确的核心冲突和悬念
- persona 要具体到能指导 AI 写对白的程度
- 如果用户描述很短，你自由发挥，但要有趣
- 禁止使用以下 AI 高频意象作为核心设定：镜子/倒影/碎片/回声/迷宫/面具/棋局/沙漏/钟表塔。如果用户明确要求则例外
- 世界设定要具体、有物质感，不要抽象隐喻化"""


class QuickCreateRequest(BaseModel):
    genre: str
    description: str = ""
    name: str = ""


@router.post("/worlds/quick_create")
def quick_create(payload: QuickCreateRequest, db: Session = Depends(get_db)):
    genre = payload.genre.strip()
    if genre not in GENRE_STYLE_MAP:
        raise HTTPException(400, f"不支持的类型：{genre}，可选：{', '.join(GENRE_STYLE_MAP.keys())}")

    style_id = GENRE_STYLE_MAP[genre]
    style = db.query(StyleProfile).filter_by(id=style_id).first()
    if not style:
        from ..engine.worldgen.style_seeds import seed_builtin_styles
        seed_builtin_styles(db)

    user_msg = f"类型：{genre}\n描述：{payload.description or '（自由发挥）'}"
    if payload.name:
        user_msg += f"\n世界名称：{payload.name}"

    try:
        llm = get_provider()
    except Exception as e:
        raise HTTPException(503, f"LLM 不可用：{e}")
    if llm is None:
        raise HTTPException(503, "未配置 LLM provider")

    text = ""
    for attempt in range(3):
        try:
            resp: LLMResponse = llm.chat(
                system=_SYSTEM,
                messages=[Message(role="user", content=user_msg)],
                tools=[],
                max_tokens=2048,
                temperature=0.9,
                timeout=60.0,
            )
        except Exception as e:
            log.exception("quick_create LLM call failed (attempt %d)", attempt + 1)
            if attempt == 2:
                raise HTTPException(502, f"LLM 调用失败：{e}")
            continue

        text = (resp.text or "").strip()
        if text:
            break
    else:
        raise HTTPException(502, "LLM 返回空响应，请重试")
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        log.warning("quick_create: LLM output not valid JSON: %s", text[:200])
        raise HTTPException(502, "LLM 输出格式异常，请重试")

    world_name = payload.name or data.get("name", f"{genre}世界")
    outline = data.get("outline", "")
    characters = data.get("characters", [])

    world = World(
        id=_new_id("w"),
        name=world_name,
        description=payload.description,
        outline=outline,
        style_profile_id=style_id,
        current_tick=0,
    )
    db.add(world)
    db.flush()

    main = Branch(
        id=_new_id("br"),
        world_id=world.id,
        name="main",
        description="主世界线",
        parent_branch_id=None,
        diverged_at_tick=0,
    )
    db.add(main)
    db.flush()
    world.active_branch_id = main.id

    entity_ids = []
    for ch in characters[:8]:
        if not isinstance(ch, dict) or not ch.get("name"):
            continue
        eid = _new_id("ent")
        entity = Entity(
            id=eid,
            branch_id=main.id,
            type="character",
            name=ch["name"],
            summary=ch.get("summary", ""),
            persona=ch.get("persona", {}),
        )
        db.add(entity)
        entity_ids.append(eid)

    db.commit()

    return {
        "id": world.id,
        "name": world_name,
        "active_branch_id": main.id,
        "style_profile_id": style_id,
        "characters": len(entity_ids),
        "has_outline": bool(outline),
    }
