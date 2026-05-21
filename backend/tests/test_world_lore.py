"""B3: WorldLore CRUD + prompt 注入函数。"""
from __future__ import annotations
import uuid

from app.models import WorldLore
from app.engine.core.tools import build_world_lore_block


# ---------- CRUD ----------

def test_lore_crud_full_cycle(client, world_factory):
    w, _ = world_factory()
    # 初始空
    assert client.get(f"/api/worlds/{w.id}/lore").json()["lore"] == []

    created = client.post(f"/api/worlds/{w.id}/lore", json={
        "title": "魔法不能伤神", "content": "凡人魔法对神格无效。",
        "category": "taboo", "priority": 5, "pinned": True,
    }).json()
    assert created["title"] == "魔法不能伤神"
    assert created["category"] == "taboo"
    assert created["priority"] == 5
    assert created["pinned"] is True
    lore_id = created["id"]

    # PATCH
    patched = client.patch(f"/api/lore/{lore_id}", json={"priority": 10, "pinned": False}).json()
    assert patched["priority"] == 10
    assert patched["pinned"] is False

    # 列表读得到
    rows = client.get(f"/api/worlds/{w.id}/lore").json()["lore"]
    assert len(rows) == 1 and rows[0]["priority"] == 10

    # DELETE
    assert client.delete(f"/api/lore/{lore_id}").json()["ok"] is True
    assert client.get(f"/api/worlds/{w.id}/lore").json()["lore"] == []


def test_lore_create_rejects_empty_title(client, world_factory):
    w, _ = world_factory()
    r = client.post(f"/api/worlds/{w.id}/lore", json={"title": "  "})
    assert r.status_code == 400


def test_lore_patch_rejects_empty_title(client, db, world_factory):
    w, _ = world_factory()
    row = WorldLore(id=f"lore_{uuid.uuid4().hex[:8]}", world_id=w.id, title="原标题", content="x")
    db.add(row); db.commit()
    r = client.patch(f"/api/lore/{row.id}", json={"title": "   "})
    assert r.status_code == 400


def test_lore_list_sorted_by_pinned_then_priority(client, db, world_factory):
    w, _ = world_factory()
    def add(title, priority, pinned=False):
        db.add(WorldLore(
            id=f"lore_{uuid.uuid4().hex[:8]}", world_id=w.id,
            title=title, content="x", priority=priority, pinned=1 if pinned else 0,
        ))
    add("p低", 1)
    add("p高", 10)
    add("置顶低优先级", 0, pinned=True)
    db.commit()

    titles = [r["title"] for r in client.get(f"/api/worlds/{w.id}/lore").json()["lore"]]
    assert titles == ["置顶低优先级", "p高", "p低"]


def test_lore_404_on_missing(client):
    assert client.patch("/api/lore/nope", json={"title": "x"}).status_code == 404
    assert client.delete("/api/lore/nope").status_code == 404


# ---------- build_world_lore_block ----------

def _seed(db, world_id, title, content="x", category="setting", priority=0, pinned=False):
    row = WorldLore(
        id=f"lore_{uuid.uuid4().hex[:8]}", world_id=world_id,
        title=title, content=content, category=category,
        priority=priority, pinned=1 if pinned else 0,
    )
    db.add(row); db.flush()
    return row


def test_block_empty_when_no_lore(db, world_factory):
    w, _ = world_factory()
    assert build_world_lore_block(db, w) == ""


def test_block_renders_categories_and_priority_order(db, world_factory):
    w, _ = world_factory()
    _seed(db, w.id, "宋代背景", content="北宋汴梁。", category="setting", priority=1)
    _seed(db, w.id, "魔法基本面", content="灵气来自地脉。", category="magic", priority=10)
    db.commit()

    text = build_world_lore_block(db, w)
    assert "# 世界设定（不可违背）" in text
    assert "## [背景] 宋代背景" in text
    assert "## [规则] 魔法基本面" in text
    # priority 高的"魔法基本面"应排在"宋代背景"前
    assert text.index("魔法基本面") < text.index("宋代背景")


def test_block_pinned_always_renders_even_over_cap(db, world_factory):
    """pinned 即使超字符上限也保留；非 pinned 超限丢弃。"""
    w, _ = world_factory()
    big = "啊" * 5000           # 单条已超 _LORE_CHAR_CAP=4000
    _seed(db, w.id, "巨长非置顶", content=big, priority=10)
    _seed(db, w.id, "短置顶", content="一句话。", priority=0, pinned=True)
    db.commit()

    text = build_world_lore_block(db, w)
    # 短置顶必在
    assert "短置顶" in text
    # 巨长非置顶被丢弃（避免 prompt 暴涨）
    assert "巨长非置顶" not in text


def test_block_skips_empty_titles(db, world_factory):
    w, _ = world_factory()
    _seed(db, w.id, "", content="无标题")  # 应跳过
    _seed(db, w.id, "有题", content="ok")
    db.commit()

    text = build_world_lore_block(db, w)
    assert "有题" in text
    assert "无标题" not in text
