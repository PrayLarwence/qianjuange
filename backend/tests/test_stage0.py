"""阶段 0 地基测试：schema 完整性 + StyleProfile seed + per-role provider +
草稿清理 + EmbeddingProvider 抽象 + EntitySnapshot/EmbeddingChunk 建表正确。
"""
from __future__ import annotations
import pytest
from app.models import (
    World, NarrativeLog, StyleProfile, EntitySnapshot, EmbeddingChunk, ChapterSummary,
)


# ===== Schema 完整性 =====

def test_world_has_new_columns(db, world_factory):
    """阶段 0 在 World 加了 5 列，create_all 能正确建出。"""
    w, _ = world_factory()
    # 默认空字符串
    assert w.embedding_provider == "" or w.embedding_provider is None
    assert w.author_model_override == "" or w.author_model_override is None
    assert w.editor_model_override == "" or w.editor_model_override is None
    assert w.reader_model_override == "" or w.reader_model_override is None
    assert w.style_profile_id is None
    # 写入读出
    w.author_model_override = "deepseek:deepseek-reasoner"
    w.embedding_provider = "local_bge"
    db.commit()
    w2 = db.query(World).filter_by(id=w.id).first()
    assert w2.author_model_override == "deepseek:deepseek-reasoner"
    assert w2.embedding_provider == "local_bge"


def test_narrative_log_new_fields(db, world_factory):
    w, br = world_factory()
    log = NarrativeLog(
        id="nl_1", branch_id=br.id, tick=1, role="director_draft",
        text="粗稿", revision_index=0, parent_log_id=None,
    )
    db.add(log)
    final = NarrativeLog(
        id="nl_2", branch_id=br.id, tick=1, role="author_final",
        text="定稿", revision_index=0, parent_log_id="nl_1",
    )
    db.add(final); db.commit()

    saved = db.query(NarrativeLog).filter_by(id="nl_2").first()
    assert saved.role == "author_final"
    assert saved.parent_log_id == "nl_1"
    assert saved.revision_index == 0


# ===== StyleProfile seed =====

def test_seed_builtin_styles_inserts_eight(db):
    from app.engine.worldgen.style_seeds import seed_builtin_styles, BUILTIN_PROFILES
    n = seed_builtin_styles(db)
    assert n == len(BUILTIN_PROFILES) == 8
    rows = db.query(StyleProfile).filter_by(kind="builtin").all()
    assert len(rows) == 8
    names = {r.name for r in rows}
    expected = {"现代严肃文学", "网文爽文", "金庸武侠风", "东方玄幻古风",
                "西式奇幻", "硬科幻", "赛博朋克", "悬疑推理"}
    assert names == expected
    # 每条都该 frozen=1 + 有 spec_text + 有 sample_paragraphs
    for r in rows:
        assert r.frozen == 1
        assert r.spec_text and len(r.spec_text) > 100
        assert isinstance(r.sample_paragraphs, list) and len(r.sample_paragraphs) >= 1


def test_seed_builtin_styles_idempotent(db):
    """重复调用应 upsert，不重复插入。"""
    from app.engine.worldgen.style_seeds import seed_builtin_styles
    seed_builtin_styles(db)
    seed_builtin_styles(db)  # 第二次
    seed_builtin_styles(db)  # 第三次
    rows = db.query(StyleProfile).filter_by(kind="builtin").all()
    assert len(rows) == 8


def test_seed_updates_existing_spec(db):
    """已有 builtin 时再 seed 应更新 spec_text，不创建副本。"""
    from app.engine.worldgen.style_seeds import seed_builtin_styles
    seed_builtin_styles(db)
    # 篡改一条
    one = db.query(StyleProfile).filter_by(id="style_jinyong").first()
    one.spec_text = "被改坏了"
    db.commit()
    seed_builtin_styles(db)
    refreshed = db.query(StyleProfile).filter_by(id="style_jinyong").first()
    assert refreshed.spec_text != "被改坏了"
    assert "金庸" in refreshed.spec_text or "武侠" in refreshed.spec_text


# ===== Per-role LLM provider =====

def test_get_provider_for_role_falls_back_when_empty(monkeypatch):
    """override 为空时回落主 provider。"""
    from app.providers import get_provider_for_role
    sentinel = object()
    monkeypatch.setattr("app.providers.get_provider", lambda: sentinel)

    class W: pass
    w = W()
    w.author_model_override = ""
    w.editor_model_override = None
    assert get_provider_for_role(w, "author") is sentinel
    assert get_provider_for_role(w, "editor") is sentinel
    assert get_provider_for_role(None, "author") is sentinel


def test_get_provider_for_role_parses_provider_colon_model(monkeypatch):
    """'provider:model' 切到指定 provider + model。"""
    from app.providers import get_provider_for_role

    captured = {}
    class FakeCls:
        def __init__(self, **kw): captured.update(kw)
    monkeypatch.setattr("app.providers.PROVIDER_CLASSES", {"deepseek": FakeCls})
    monkeypatch.setattr("app.providers.load_config",
                        lambda: {"active": "deepseek",
                                 "providers": {"deepseek": {"api_key": "k", "base_url": "u"}}})

    class W:
        author_model_override = "deepseek:deepseek-reasoner"
    get_provider_for_role(W(), "author")
    assert captured["model"] == "deepseek-reasoner"
    assert captured["api_key"] == "k"
    assert captured["base_url"] == "u"


def test_get_provider_for_role_bare_model_uses_active(monkeypatch):
    """没冒号的 override 当作主 provider 下的 model 名。"""
    from app.providers import get_provider_for_role

    captured = {}
    class FakeCls:
        def __init__(self, **kw): captured.update(kw)
    monkeypatch.setattr("app.providers.PROVIDER_CLASSES", {"deepseek": FakeCls})
    monkeypatch.setattr("app.providers.load_config",
                        lambda: {"active": "deepseek",
                                 "providers": {"deepseek": {"api_key": "k"}}})

    class W:
        editor_model_override = "deepseek-chat"
    get_provider_for_role(W(), "editor")
    assert captured["model"] == "deepseek-chat"


def test_get_provider_for_role_unknown_provider_falls_back(monkeypatch):
    """override 引用了不存在的 provider 时回落，不让世界崩。"""
    from app.providers import get_provider_for_role
    sentinel = object()
    monkeypatch.setattr("app.providers.get_provider", lambda: sentinel)
    monkeypatch.setattr("app.providers.PROVIDER_CLASSES", {"deepseek": object})

    class W:
        author_model_override = "nope:whatever"
    assert get_provider_for_role(W(), "author") is sentinel


# ===== 草稿清理 =====

def _add_draft(db, branch_id, tick, idx=0, role="director_draft"):
    import uuid
    log = NarrativeLog(
        id=f"nl_{uuid.uuid4().hex[:8]}", branch_id=branch_id, tick=tick,
        role=role, text=f"draft tick={tick} idx={idx}", revision_index=idx,
    )
    db.add(log); db.flush()
    return log


def test_cleanup_keeps_recent_three_distinct_ticks(db, world_factory):
    from app.engine.narrative.draft_cleanup import cleanup_old_drafts
    _, br = world_factory()
    for t in [1, 2, 3, 4, 5]:
        _add_draft(db, br.id, t)
    db.commit()
    deleted = cleanup_old_drafts(db, br.id, retention=3)
    assert deleted == 2
    remaining = db.query(NarrativeLog).filter_by(
        branch_id=br.id, role="director_draft").all()
    ticks = sorted(r.tick for r in remaining)
    assert ticks == [3, 4, 5]


def test_cleanup_groups_by_tick_not_count(db, world_factory):
    """同一 tick 多条草稿都该保留——按 distinct tick 数算 retention。"""
    from app.engine.narrative.draft_cleanup import cleanup_old_drafts
    _, br = world_factory()
    # tick 1 有 3 条草稿；tick 2/3/4 各 1 条
    for i in range(3):
        _add_draft(db, br.id, 1, idx=i)
    for t in [2, 3, 4]:
        _add_draft(db, br.id, t)
    db.commit()
    deleted = cleanup_old_drafts(db, br.id, retention=3)
    # tick 1 的 3 条全删（因为只保留最新 3 个 distinct tick：2,3,4）
    assert deleted == 3
    remaining = db.query(NarrativeLog).filter_by(
        branch_id=br.id, role="director_draft").all()
    assert {r.tick for r in remaining} == {2, 3, 4}


def test_cleanup_noop_when_under_retention(db, world_factory):
    from app.engine.narrative.draft_cleanup import cleanup_old_drafts
    _, br = world_factory()
    for t in [1, 2]:
        _add_draft(db, br.id, t)
    db.commit()
    deleted = cleanup_old_drafts(db, br.id, retention=3)
    assert deleted == 0


def test_cleanup_does_not_touch_other_roles(db, world_factory):
    """清理 director_draft 时不能误删 author_final。"""
    from app.engine.narrative.draft_cleanup import cleanup_old_drafts
    _, br = world_factory()
    for t in [1, 2, 3, 4, 5]:
        _add_draft(db, br.id, t, role="director_draft")
        _add_draft(db, br.id, t, role="author_final")
    db.commit()
    cleanup_old_drafts(db, br.id, retention=2)
    finals = db.query(NarrativeLog).filter_by(
        branch_id=br.id, role="author_final").all()
    assert len(finals) == 5  # 定稿一条没动


def test_cleanup_reader_feedback_keeps_latest_one(db, world_factory):
    from app.engine.narrative.draft_cleanup import cleanup_old_reader_feedback
    _, br = world_factory()
    for t in [1, 2, 3]:
        _add_draft(db, br.id, t, role="reader_feedback")
    db.commit()
    deleted = cleanup_old_reader_feedback(db, br.id, retention=1)
    assert deleted == 2
    remaining = db.query(NarrativeLog).filter_by(
        branch_id=br.id, role="reader_feedback").all()
    assert len(remaining) == 1
    assert remaining[0].tick == 3


# ===== EmbeddingProvider 抽象 =====

def test_embedding_registry_lists_three_stubs():
    from app.engine.embedding import AVAILABLE_PROVIDERS, get_provider
    assert set(AVAILABLE_PROVIDERS) == {"local_bge", "zhipu", "siliconflow"}
    for name in AVAILABLE_PROVIDERS:
        p = get_provider(name)
        assert p.name == name
        assert p.dim > 0
        # 阶段 0 stub 必抛 NotImplementedError
        with pytest.raises(NotImplementedError):
            p.embed(["test"])


def test_embedding_null_provider_when_unset():
    from app.engine.embedding import get_provider, NullProvider
    assert isinstance(get_provider(""), NullProvider)
    assert isinstance(get_provider(None), NullProvider)
    assert isinstance(get_provider("nope"), NullProvider)
    p = get_provider("")
    # 空列表静默返回，避免无谓的崩溃
    assert p.embed([]) == []
    # 非空但未配置应明确报错
    with pytest.raises(RuntimeError):
        p.embed(["text"])


def test_embedding_health_check_returns_dict():
    from app.engine.embedding import get_provider, AVAILABLE_PROVIDERS
    for name in AVAILABLE_PROVIDERS:
        h = get_provider(name).health_check()
        assert isinstance(h, dict)
        assert "ok" in h


# ===== EntitySnapshot / EmbeddingChunk / ChapterSummary 建表正确 =====

def test_entity_snapshot_writeable(db, world_factory):
    from app.models import Entity
    import uuid
    _, br = world_factory()
    e = Entity(id="e_x", branch_id=br.id, type="character", name="林冲",
               attributes={}, state={}, persona={"trait": "忍"}, memories=[])
    db.add(e); db.commit()
    snap = EntitySnapshot(
        id=f"es_{uuid.uuid4().hex[:8]}", entity_id=e.id, branch_id=br.id,
        tick=10, persona_snapshot={"trait": "忍"},
        attributes_snapshot={"job": "教头"}, state_snapshot={},
        summary_snapshot="八十万禁军教头",
    )
    db.add(snap); db.commit()
    saved = db.query(EntitySnapshot).filter_by(entity_id=e.id).first()
    assert saved.persona_snapshot["trait"] == "忍"
    assert saved.summary_snapshot.startswith("八十万")


def test_embedding_chunk_writeable(db, world_factory):
    import uuid, json
    w, br = world_factory()
    chunk = EmbeddingChunk(
        id=f"ec_{uuid.uuid4().hex[:8]}", world_id=w.id, branch_id=br.id,
        tick=5, text="一段被向量化的小说原文",
        embedding=json.dumps([0.1, 0.2, 0.3]),
        embedding_model="bge-small-zh-v1.5", dim=512,
    )
    db.add(chunk); db.commit()
    saved = db.query(EmbeddingChunk).filter_by(world_id=w.id).first()
    assert saved.text.startswith("一段")
    assert json.loads(saved.embedding) == [0.1, 0.2, 0.3]
    assert saved.dim == 512


def test_chapter_summary_writeable(db, world_factory):
    import uuid
    from app.models import ChapterMarker
    _, br = world_factory()
    cm = ChapterMarker(id="cm_1", branch_id=br.id, tick=10, title="楔子", note="")
    db.add(cm); db.commit()
    cs = ChapterSummary(
        id=f"cs_{uuid.uuid4().hex[:8]}", chapter_marker_id=cm.id, branch_id=br.id,
        summary="林冲被陷害，发配沧州。", key_event_ids=["e1", "e2"], word_count=15,
        model_used="deepseek-chat",
    )
    db.add(cs); db.commit()
    saved = db.query(ChapterSummary).filter_by(chapter_marker_id="cm_1").first()
    assert saved.summary.startswith("林冲")
    assert saved.key_event_ids == ["e1", "e2"]
