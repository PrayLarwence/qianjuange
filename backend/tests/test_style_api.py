"""A4 测试：StyleProfile 列表 + 绑定/解绑端点。"""
from __future__ import annotations
import pytest
from app.models import StyleProfile, World


def _seed(db):
    from app.engine.style_seeds import seed_builtin_styles
    seed_builtin_styles(db)


def test_list_style_profiles_returns_8_builtin(client, db):
    _seed(db)
    r = client.get("/api/style_profiles")
    assert r.status_code == 200
    profiles = r.json()["profiles"]
    builtins = [p for p in profiles if p["kind"] == "builtin"]
    assert len(builtins) == 8
    # 每条都该有展示用字段，但没有 spec_text（节省传输）
    for p in builtins:
        assert p["id"].startswith("style_")
        assert p["name"]
        assert "description" in p
        assert "category" in p
        assert "spec_text" not in p
        assert p["frozen"] is True


def test_list_style_profiles_includes_custom(client, db):
    _seed(db)
    db.add(StyleProfile(
        id="style_custom_1", name="我的自定义",
        description="用户自建", kind="custom", category="user",
        spec_text="...", sample_paragraphs=[], frozen=0,
    ))
    db.commit()
    r = client.get("/api/style_profiles")
    profiles = r.json()["profiles"]
    customs = [p for p in profiles if p["kind"] == "custom"]
    assert len(customs) == 1 and customs[0]["id"] == "style_custom_1"
    assert customs[0]["frozen"] is False


def test_get_style_profile_returns_full_spec(client, db):
    _seed(db)
    r = client.get("/api/style_profiles/style_jinyong")
    assert r.status_code == 200
    p = r.json()
    assert p["id"] == "style_jinyong"
    assert p["spec_text"]  # 详情接口才返 spec
    assert isinstance(p["sample_paragraphs"], list)


def test_get_style_profile_404(client, db):
    r = client.get("/api/style_profiles/style_does_not_exist")
    assert r.status_code == 404


def test_patch_world_binds_style(client, db, world_factory):
    _seed(db)
    w, _ = world_factory()
    assert w.style_profile_id is None

    r = client.patch(f"/api/worlds/{w.id}", json={"style_profile_id": "style_jinyong"})
    assert r.status_code == 200, r.text
    assert r.json()["style_profile_id"] == "style_jinyong"

    db.expire_all()
    w2 = db.query(World).filter_by(id=w.id).first()
    assert w2.style_profile_id == "style_jinyong"


def test_patch_world_unbinds_with_empty_string(client, db, world_factory):
    _seed(db)
    w, _ = world_factory()
    w.style_profile_id = "style_jinyong"; db.commit()

    r = client.patch(f"/api/worlds/{w.id}", json={"style_profile_id": ""})
    assert r.status_code == 200
    assert r.json()["style_profile_id"] is None

    db.expire_all()
    w2 = db.query(World).filter_by(id=w.id).first()
    assert w2.style_profile_id is None


def test_patch_world_unknown_style_id_400(client, db, world_factory):
    w, _ = world_factory()
    r = client.patch(f"/api/worlds/{w.id}", json={"style_profile_id": "style_nope"})
    assert r.status_code == 400
    assert "style_profile not found" in r.text


def test_patch_world_omitting_style_keeps_binding(client, db, world_factory):
    """不传 style_profile_id 字段时，已有绑定不变。"""
    _seed(db)
    w, _ = world_factory()
    w.style_profile_id = "style_jinyong"; db.commit()

    r = client.patch(f"/api/worlds/{w.id}", json={"description": "改个简介"})
    assert r.status_code == 200

    db.expire_all()
    w2 = db.query(World).filter_by(id=w.id).first()
    assert w2.style_profile_id == "style_jinyong"
    assert w2.description == "改个简介"


def test_get_world_returns_style_profile_id(client, db, world_factory):
    _seed(db)
    w, _ = world_factory()
    w.style_profile_id = "style_cyberpunk"; db.commit()

    r = client.get(f"/api/worlds/{w.id}")
    assert r.status_code == 200
    assert r.json()["world"]["style_profile_id"] == "style_cyberpunk"
