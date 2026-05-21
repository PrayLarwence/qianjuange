"""P1: 官方模板种子。"""
from __future__ import annotations

from app.models import WorldTemplate
from app.seeds import seed_official_templates, OFFICIAL_TEMPLATES, official_template_names


def test_seed_inserts_all_on_empty(db):
    r = seed_official_templates(db)
    assert r["inserted"] == len(OFFICIAL_TEMPLATES)
    assert r["skipped"] == 0
    rows = db.query(WorldTemplate).filter_by(is_official=1).all()
    assert len(rows) == len(OFFICIAL_TEMPLATES)


def test_seed_idempotent(db):
    seed_official_templates(db)
    r2 = seed_official_templates(db)
    assert r2["inserted"] == 0
    assert r2["skipped"] == len(OFFICIAL_TEMPLATES)
    rows = db.query(WorldTemplate).filter_by(is_official=1).all()
    assert len(rows) == len(OFFICIAL_TEMPLATES)


def test_seed_force_refresh_updates_in_place(db):
    seed_official_templates(db)
    # 假装某个模板被改坏了
    name = next(iter(official_template_names()))
    t = db.query(WorldTemplate).filter_by(name=name, is_official=1).first()
    t.description = "被改坏了"
    db.commit()
    r = seed_official_templates(db, force=True)
    assert r["refreshed"] == len(OFFICIAL_TEMPLATES)
    fresh = db.query(WorldTemplate).filter_by(name=name, is_official=1).first()
    assert fresh.description != "被改坏了"
    # 数量没翻倍
    rows = db.query(WorldTemplate).filter_by(is_official=1).all()
    assert len(rows) == len(OFFICIAL_TEMPLATES)


def test_seed_does_not_touch_user_templates(db):
    user_t = WorldTemplate(
        id="tpl_user_1", name="武林少年闯荡录",  # 与官方同名但 is_official=0
        category="user", description="我自己写的",
        cover_emoji="📖", rules={}, suggested_steps=[],
        seed_entities=[], canonical_outline=[], tags=[],
        author="user", is_official=0,
    )
    db.add(user_t); db.commit()
    seed_official_templates(db)
    # 用户那条没动
    rows = db.query(WorldTemplate).filter_by(name="武林少年闯荡录").all()
    assert len(rows) == 2
    user_kept = [r for r in rows if not r.is_official][0]
    assert user_kept.id == "tpl_user_1"
    assert user_kept.description == "我自己写的"


def test_seed_endpoint(client, db):
    r = client.post("/api/templates/seed_official").json()
    assert r["inserted"] == len(OFFICIAL_TEMPLATES)
    # 列表端点能看到
    lst = client.get("/api/templates").json()
    names = {t["name"] for t in lst["templates"] if t["is_official"]}
    for n in official_template_names():
        assert n in names


def test_seed_endpoint_force(client, db):
    client.post("/api/templates/seed_official")
    r = client.post("/api/templates/seed_official?force=true").json()
    assert r["refreshed"] == len(OFFICIAL_TEMPLATES)


def test_official_templates_have_required_fields(db):
    """每个 spec 必须能造出可实例化的模板。"""
    for spec in OFFICIAL_TEMPLATES:
        assert spec["name"] and len(spec["name"]) <= 30
        assert spec.get("description")
        assert spec.get("seed_directive")  # P1 要求每个都有写好的开场指令
        assert isinstance(spec.get("rules", {}).get("core_rules"), list)
        assert spec["rules"]["core_rules"]  # 至少一条核心规则
        assert spec.get("seed_entities")  # 至少一个角色
        assert isinstance(spec.get("suggested_steps"), list)
        assert spec["suggested_steps"]  # 至少一步建议


def test_seeded_template_can_be_instantiated(client, db):
    """种子完之后，实例化任意一个不报错。"""
    seed_official_templates(db)
    tpl = db.query(WorldTemplate).filter_by(is_official=1).first()
    r = client.post(f"/api/templates/{tpl.id}/instantiate", json={"auto_step": False})
    assert r.status_code == 200
    body = r.json()
    assert body["world_id"]
    assert body["seed_directive"]
