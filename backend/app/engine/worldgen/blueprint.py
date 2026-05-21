"""Map blueprint: text → structured layout.

Given a world's description + outline, ask the LLM to emit a list of
named regions and landmarks. Downstream, worldgen consumes the blueprint
to override fbm noise into a meaningful layout, and landmarks are
materialized as location entities pinned on the map.

The LLM expresses the blueprint by calling tool functions repeatedly:
  - define_region(name, terrain, cx, cy, radius, note)
  - define_landmark(name, kind, x, y, note)
  - finish_blueprint()

We deliberately mirror the existing run_step tool-call loop instead of
parsing free-form JSON: tool-args go through a JSONSchema layer that
catches malformed output before it touches the renderer.
"""

from __future__ import annotations
import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from ...models import World
from ...providers import LLMProvider, Message, ToolSpec


log = logging.getLogger(__name__)


# Terrain kinds the LLM is allowed to specify (string → terrain code).
ALLOWED_TERRAIN = {
    "ocean":    1,
    "coast":    2,
    "beach":    3,
    "plain":    4,
    "hill":     5,
    "mountain": 6,
    "peak":     7,
}

# Landmark kinds carry no terrain semantics — they're labels for
# location entities pinned on the map.
ALLOWED_LANDMARK_KINDS = {
    "city", "town", "village", "fortress", "temple",
    "ruin", "camp", "harbor", "mine", "forest", "lake",
    "river_mouth", "pass", "bridge", "landmark",
}


SYSTEM_PROMPT = """你是一个地图蓝图设计师。基于给定的世界描述与全貌大纲，规划一张方形栅格地图的布局。

调用以下工具来表达你的设计：
  - define_region(name, terrain, cx, cy, radius, note)
      在地图上划一个圆形区域，强制其地形为指定类型。
      terrain ∈ {ocean, coast, beach, plain, hill, mountain, peak}
      cx, cy 为圆心栅格坐标（0 ≤ cx < width, 0 ≤ cy < height）
      radius 为圆半径（栅格数）
      note 为简短说明（"梁山泊主峰"、"汴京东郊平原"）

  - define_landmark(name, kind, x, y, note)
      在 (x, y) 钉一个命名地点。kind 必须是：
      city / town / village / fortress / temple / ruin / camp / harbor /
      mine / forest / lake / river_mouth / pass / bridge / landmark
      地标会自动建为地图上的 location 实体。
      地标坐标须落在合理地形上（村庄不能放海里）。

  - finish_blueprint()
      所有区域和地标都设计完后调用。

设计原则：
1. 严格服从大纲。大纲点名了原作（《水浒传》《指环王》等）的地名，应当忠实还原其相对位置（梁山泊 ≠ 东京汴梁）。
2. 区域不要互相完全覆盖。先大后小：先海/陆框架，再山脉，再小区域。
3. 地标要落在它对应的地形上：村庄/城市落平原或丘陵；山寨落山地；港口落海滨。
4. 一张图通常 3-8 个 region + 5-15 个 landmark，不要过密。
5. 地图坐标系：左上 (0,0)，向右 x 增，向下 y 增。
6. 不要输出大段思考独白，用工具调用说话。完成后必须调用 finish_blueprint。
"""


TOOL_SPECS = [
    ToolSpec(
        name="define_region",
        description="划一片圆形区域，强制其地形",
        parameters={
            "type": "object",
            "properties": {
                "name":    {"type": "string"},
                "terrain": {"type": "string", "enum": list(ALLOWED_TERRAIN.keys())},
                "cx":      {"type": "integer"},
                "cy":      {"type": "integer"},
                "radius":  {"type": "integer", "minimum": 1},
                "note":    {"type": "string"},
            },
            "required": ["name", "terrain", "cx", "cy", "radius"],
        },
    ),
    ToolSpec(
        name="define_landmark",
        description="在地图上钉一个命名地点",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "kind": {"type": "string", "enum": sorted(ALLOWED_LANDMARK_KINDS)},
                "x":    {"type": "integer"},
                "y":    {"type": "integer"},
                "note": {"type": "string"},
            },
            "required": ["name", "kind", "x", "y"],
        },
    ),
    ToolSpec(
        name="finish_blueprint",
        description="确认设计完成",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
]


MAX_HOPS = 12


def generate_blueprint(
    db: Session,
    world: World,
    width: int,
    height: int,
    provider: LLMProvider,
    extra_directive: Optional[str] = None,
) -> dict:
    """Run the LLM to produce a blueprint.

    Returns:
        {
          "ok": bool,
          "regions":   [{name, terrain, cx, cy, radius, note}, ...],
          "landmarks": [{name, kind, x, y, note}, ...],
          "hops": int,
          "errors": [str, ...],   # validation failures (rejected calls)
        }
    """
    user_prompt = _build_user_prompt(world, width, height, extra_directive)
    messages: list[Message] = [Message(role="user", content=user_prompt)]
    regions: list[dict] = []
    landmarks: list[dict] = []
    errors: list[str] = []
    finished = False

    for hop in range(MAX_HOPS):
        resp = provider.chat(
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=TOOL_SPECS,
            max_tokens=2048,
            temperature=0.5,
        )
        messages.append(Message(
            role="assistant",
            content=resp.text or "",
            tool_calls=list(resp.tool_calls or []),
        ))
        if not resp.tool_calls:
            # No more tool use — treat as implicit finish.
            break
        for tc in resp.tool_calls:
            ok, result_or_err = _apply_call(
                tc.name, tc.arguments or {},
                width, height, regions, landmarks,
            )
            messages.append(Message(
                role="tool",
                content=json.dumps(
                    {"ok": ok, **({"result": result_or_err} if ok else {"error": result_or_err})},
                    ensure_ascii=False,
                ),
                tool_call_id=tc.id,
                tool_name=tc.name,
            ))
            if not ok:
                errors.append(f"{tc.name}: {result_or_err}")
            if tc.name == "finish_blueprint":
                finished = True
        if finished:
            break

    return {
        "ok": True,
        "regions": regions,
        "landmarks": landmarks,
        "hops": hop + 1,
        "errors": errors,
        "finished": finished,
    }


def _build_user_prompt(world: World, width: int, height: int,
                       extra: Optional[str]) -> str:
    parts = [
        f"## 世界",
        f"名字：{world.name}",
    ]
    if world.description:
        parts.append(f"描述：{world.description}")
    outline = (world.outline or "").strip()
    if outline:
        parts.append(f"\n## 全貌大纲\n{outline}")
    parts.append(f"\n## 地图尺寸\nwidth = {width}, height = {height}")
    parts.append(
        f"\n## 地形标签参考（仅供你理解，区域 terrain 仍用英文 key）\n"
        + ", ".join(f"{k}={TERRAIN_LABELS.get(v, '?')}" for k, v in ALLOWED_TERRAIN.items())
    )
    if extra:
        parts.append(f"\n## 用户附加要求\n{extra}")
    parts.append(
        "\n请基于上述信息，规划地图布局。"
        "通过依次调用 define_region / define_landmark 描绘世界，"
        "完成后调用 finish_blueprint。"
    )
    return "\n".join(parts)


def _apply_call(
    name: str, args: dict,
    width: int, height: int,
    regions: list[dict], landmarks: list[dict],
) -> tuple[bool, str | dict]:
    if name == "define_region":
        try:
            n = (args.get("name") or "").strip()
            t = (args.get("terrain") or "").strip().lower()
            cx, cy, r = int(args["cx"]), int(args["cy"]), int(args["radius"])
        except (KeyError, ValueError, TypeError):
            return False, "missing or invalid region args"
        if not n:
            return False, "region name required"
        if t not in ALLOWED_TERRAIN:
            return False, f"unknown terrain '{t}'; allowed: {sorted(ALLOWED_TERRAIN.keys())}"
        if not (0 <= cx < width and 0 <= cy < height):
            return False, f"center ({cx},{cy}) out of {width}x{height}"
        if r < 1 or r > max(width, height):
            return False, f"radius {r} out of range"
        entry = {
            "name": n, "terrain": t, "cx": cx, "cy": cy, "radius": r,
            "note": (args.get("note") or "").strip(),
        }
        regions.append(entry)
        return True, entry

    if name == "define_landmark":
        try:
            n = (args.get("name") or "").strip()
            k = (args.get("kind") or "").strip().lower()
            x, y = int(args["x"]), int(args["y"])
        except (KeyError, ValueError, TypeError):
            return False, "missing or invalid landmark args"
        if not n:
            return False, "landmark name required"
        if k not in ALLOWED_LANDMARK_KINDS:
            return False, f"unknown kind '{k}'; allowed: {sorted(ALLOWED_LANDMARK_KINDS)}"
        if not (0 <= x < width and 0 <= y < height):
            return False, f"({x},{y}) out of {width}x{height}"
        entry = {
            "name": n, "kind": k, "x": x, "y": y,
            "note": (args.get("note") or "").strip(),
        }
        landmarks.append(entry)
        return True, entry

    if name == "finish_blueprint":
        return True, {"finished": True}

    return False, f"unknown tool '{name}'"
