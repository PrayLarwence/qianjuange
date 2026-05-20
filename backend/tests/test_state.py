"""引擎纯函数测试 —— 不依赖 DB / LLM。"""
from __future__ import annotations

from app.engine.state import _entity_for_prompt


def test_prompt_drops_empty_summary():
    full = {"id": "e1", "type": "character", "name": "周浩然",
            "summary": "", "attributes": {}}
    out = _entity_for_prompt(full)
    assert "summary" not in out
    assert "attributes" not in out
    assert out["name"] == "周浩然"
    assert out["type"] == "character"


def test_prompt_keeps_meaningful_fields():
    full = {"id": "e1", "type": "character", "name": "吴用",
            "summary": "智多星", "attributes": {"iq": 99}, "state": {"alive": 1}}
    out = _entity_for_prompt(full)
    assert out["summary"] == "智多星"
    assert out["attributes"] == {"iq": 99}
    assert out["state"] == {"alive": 1}


def test_prompt_position_packed_into_pos():
    full = {"id": "e1", "type": "character", "name": "x",
            "map_x": 10, "map_y": 20}
    out = _entity_for_prompt(full)
    assert out["pos"] == [10, 20]
    assert "map_x" not in out and "map_y" not in out


def test_prompt_target_with_speed():
    full = {"id": "e1", "type": "character", "name": "x",
            "target_x": 5, "target_y": 6, "move_speed": 2.5}
    out = _entity_for_prompt(full)
    assert out["target"] == [5, 6]
    assert out["speed"] == 2.5


def test_prompt_partial_position_dropped():
    """只有 x 没有 y 时不应输出 pos —— 防止脏数据漏出。"""
    full = {"id": "e1", "type": "character", "name": "x", "map_x": 10}
    out = _entity_for_prompt(full)
    assert "pos" not in out


def test_prompt_status_idle_dropped():
    full = {"id": "e1", "type": "character", "name": "x",
            "sim_state": {"status": "idle"}}
    out = _entity_for_prompt(full)
    assert "status" not in out


def test_prompt_status_blocked_kept():
    full = {"id": "e1", "type": "character", "name": "x",
            "sim_state": {"status": "moving", "blocked_reason": "山"}}
    out = _entity_for_prompt(full)
    assert out["status"] == "moving"
    assert out["blocked"] == "山"


def test_build_state_snapshot_minimal(db, world_factory):
    """落库一个空世界后，build_state_snapshot 应给出合法 shape。"""
    from app.engine.state import build_state_snapshot
    w, _ = world_factory(name="空世界")
    snap = build_state_snapshot(db, w)
    assert snap["world"]["id"] == w.id
    assert snap["world"]["current_tick"] == 0
    assert snap["entities"] == []
    assert snap["recent_events"] == []
    assert snap["causal_links"] == []


def test_build_state_snapshot_with_entity(db, world_factory):
    from app.engine.state import build_state_snapshot
    from app.models import Entity
    w, br = world_factory(name="有人世界")
    db.add(Entity(id="e1", branch_id=br.id, type="character",
                  name="主角", summary="少侠",
                  attributes={}, state={}, alive=1, created_at_tick=0))
    db.commit()
    snap = build_state_snapshot(db, w)
    assert len(snap["entities"]) == 1
    assert snap["entities"][0]["name"] == "主角"


def test_build_state_snapshot_skips_dead(db, world_factory):
    from app.engine.state import build_state_snapshot
    from app.models import Entity
    w, br = world_factory()
    db.add(Entity(id="dead", branch_id=br.id, type="character",
                  name="阵亡者", summary="", attributes={}, state={},
                  alive=0, created_at_tick=0))
    db.add(Entity(id="alive", branch_id=br.id, type="character",
                  name="幸存者", summary="", attributes={}, state={},
                  alive=1, created_at_tick=0))
    db.commit()
    snap = build_state_snapshot(db, w)
    names = {e["name"] for e in snap["entities"]}
    assert "幸存者" in names
    assert "阵亡者" not in names


# ---- persona 进 prompt ----

def test_prompt_includes_character_persona():
    full = {
        "id": "e1", "type": "character", "name": "林冲",
        "persona": {
            "drives": ["雪冤", "保家小"],
            "voice": "沉默克制，话不多",
            "knowledge_blindspots": ["高俅的真实背景"],
        },
    }
    out = _entity_for_prompt(full)
    assert "persona" in out
    assert out["persona"]["drives"] == ["雪冤", "保家小"]
    assert out["persona"]["voice"] == "沉默克制，话不多"
    assert out["persona"]["knowledge_blindspots"] == ["高俅的真实背景"]


def test_prompt_skips_persona_for_non_character():
    """location / item 等非角色不需要 persona，省 token。"""
    full = {
        "id": "loc1", "type": "location", "name": "梁山",
        "persona": {"drives": ["???"]},
    }
    out = _entity_for_prompt(full)
    assert "persona" not in out


def test_prompt_skips_empty_persona():
    full = {"id": "e1", "type": "character", "name": "甲",
            "persona": {}}
    out = _entity_for_prompt(full)
    assert "persona" not in out


def test_prompt_drops_empty_persona_subfields():
    """drives 为空数组、voice 为空串都应被丢掉，只保留有内容的子字段。"""
    full = {"id": "e1", "type": "character", "name": "甲",
            "persona": {"drives": [], "voice": "", "knowledge_blindspots": ["盲A"]}}
    out = _entity_for_prompt(full)
    assert out["persona"] == {"knowledge_blindspots": ["盲A"]}


# ---- state_as_prompt 速查章节 ----

def test_state_as_prompt_emits_persona_quickref():
    """有 persona 的角色应出现在'角色人格速查'独立章节里。"""
    from app.engine.state import state_as_prompt
    snap = {
        "world": {"name": "测试世界", "description": "", "current_tick": 0,
                  "outline": "", "rules": {}},
        "entities": [
            {"id": "e1", "type": "character", "name": "林冲",
             "persona": {"drives": ["雪冤"], "voice": "沉默"}},
            {"id": "e2", "type": "character", "name": "高俅",
             "persona": {}},  # 应被跳过
            {"id": "loc1", "type": "location", "name": "东京"},
        ],
        "recent_events": [], "causal_links": [], "recent_narration": [],
    }
    out = state_as_prompt(snap)
    assert "角色人格速查" in out
    assert "林冲" in out
    assert "雪冤" in out
    assert "沉默" in out
    # 高俅没填 persona，不应在速查段落里出现
    quickref_section = out.split("角色人格速查")[1].split("\n##")[0]
    assert "高俅" not in quickref_section


def test_state_as_prompt_no_quickref_when_no_persona():
    """全部角色都没 persona 时，速查章节不应出现。"""
    from app.engine.state import state_as_prompt
    snap = {
        "world": {"name": "x", "description": "", "current_tick": 0,
                  "outline": "", "rules": {}},
        "entities": [
            {"id": "e1", "type": "character", "name": "甲", "persona": {}},
        ],
        "recent_events": [], "causal_links": [], "recent_narration": [],
    }
    out = state_as_prompt(snap)
    assert "角色人格速查" not in out


# ---- outline_progress 进 prompt ----

def test_load_outline_block_no_template(db, world_factory):
    """没绑定模板的世界返回 None，prompt 不会出现剧情进度章节。"""
    from app.engine.state import _load_outline_block, build_state_snapshot, state_as_prompt
    w, _ = world_factory()
    assert _load_outline_block(db, w) is None
    snap = build_state_snapshot(db, w)
    assert "outline_progress" not in snap
    assert "剧情进度" not in state_as_prompt(snap)


def test_load_outline_block_with_template_and_progress(db, world_factory):
    """绑模板 + 有进度时正常返回，含 current_beat / upcoming / completed。"""
    from app.engine.state import _load_outline_block
    from app.models import WorldTemplate
    import uuid
    t = WorldTemplate(
        id=f"t_{uuid.uuid4().hex[:8]}", name="测试模板", description="",
        canonical_outline=[
            {"beat": "开学"},
            {"beat": "分院"},
            {"beat": "魁地奇试训"},
            {"beat": "期末"},
        ],
    )
    db.add(t); db.commit()
    w, _ = world_factory()
    w.template_id = t.id
    w.outline_progress = {"current_index": 1, "completed": [0]}
    db.commit()

    block = _load_outline_block(db, w)
    assert block is not None
    assert block["current_index"] == 1
    assert block["completed"] == [0]
    assert block["current_beat"]["beat"] == "分院"
    # upcoming 含当前及后续 2 条
    upcoming = block["upcoming"]
    assert len(upcoming) == 3
    assert upcoming[0]["beat"] == "分院"
    assert upcoming[1]["beat"] == "魁地奇试训"
    assert block["all_done"] is False


def test_load_outline_block_clamp_overflow(db, world_factory):
    """current_index 超出范围时应 clamp 到末尾，all_done=True。"""
    from app.engine.state import _load_outline_block
    from app.models import WorldTemplate
    import uuid
    t = WorldTemplate(id=f"t_{uuid.uuid4().hex[:8]}", name="x", description="",
                      canonical_outline=[{"beat": "唯一"}])
    db.add(t); db.commit()
    w, _ = world_factory()
    w.template_id = t.id
    w.outline_progress = {"current_index": 99, "completed": [0]}
    db.commit()
    block = _load_outline_block(db, w)
    assert block["all_done"] is True
    assert block["current_beat"] is None


def test_load_outline_block_empty_outline(db, world_factory):
    """模板存在但 canonical_outline 空 → 返回 None。"""
    from app.engine.state import _load_outline_block
    from app.models import WorldTemplate
    import uuid
    t = WorldTemplate(id=f"t_{uuid.uuid4().hex[:8]}", name="x", description="",
                      canonical_outline=[])
    db.add(t); db.commit()
    w, _ = world_factory()
    w.template_id = t.id
    db.commit()
    assert _load_outline_block(db, w) is None


def test_load_outline_block_accepts_string_beats(db, world_factory):
    """outline 里允许是字符串 list 而不是 dict list。"""
    from app.engine.state import _load_outline_block
    from app.models import WorldTemplate
    import uuid
    t = WorldTemplate(id=f"t_{uuid.uuid4().hex[:8]}", name="x", description="",
                      canonical_outline=["第一拍", "第二拍"])
    db.add(t); db.commit()
    w, _ = world_factory()
    w.template_id = t.id
    db.commit()
    block = _load_outline_block(db, w)
    assert block["beats"][0]["beat"] == "第一拍"
    assert block["beats"][1]["beat"] == "第二拍"


def test_state_as_prompt_renders_outline_progress():
    """剧情进度章节渲染时应高亮当前节拍并标注完成/当前/未开始。"""
    from app.engine.state import state_as_prompt
    snap = {
        "world": {"name": "x", "description": "", "current_tick": 0,
                  "outline": "", "rules": {}},
        "entities": [],
        "recent_events": [], "causal_links": [], "recent_narration": [],
        "outline_progress": {
            "beats": [
                {"index": 0, "beat": "开学"},
                {"index": 1, "beat": "分院"},
                {"index": 2, "beat": "期末"},
            ],
            "current_index": 1,
            "completed": [0],
            "current_beat": {"index": 1, "beat": "分院"},
            "upcoming": [
                {"index": 1, "beat": "分院"},
                {"index": 2, "beat": "期末"},
            ],
            "all_done": False,
        },
    }
    out = state_as_prompt(snap)
    assert "剧情进度" in out
    assert "当前应推进的节拍 #1" in out
    assert "分院" in out
    assert "[已完成]" in out
    assert "[当前]" in out
    assert "[未开始]" in out


def test_state_as_prompt_renders_all_done():
    """全部完成时章节应说明，并不再显示 current_beat。"""
    from app.engine.state import state_as_prompt
    snap = {
        "world": {"name": "x", "description": "", "current_tick": 0,
                  "outline": "", "rules": {}},
        "entities": [],
        "recent_events": [], "causal_links": [], "recent_narration": [],
        "outline_progress": {
            "beats": [{"index": 0, "beat": "唯一"}],
            "current_index": 1,
            "completed": [0],
            "current_beat": None,
            "upcoming": [],
            "all_done": True,
        },
    }
    out = state_as_prompt(snap)
    assert "剧情进度" in out
    assert "均已标记完成" in out
    assert "当前应推进的节拍" not in out
