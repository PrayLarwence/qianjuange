from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "world.db"

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def init_db() -> None:
    from . import world  # noqa: F401  ensure models are registered
    Base.metadata.create_all(bind=engine)
    _migrate()
    _seed_builtin_styles()


def _seed_builtin_styles() -> None:
    """启动时 upsert 8 个内置 StyleProfile。"""
    from ..engine.style_seeds import seed_builtin_styles
    db = SessionLocal()
    try:
        seed_builtin_styles(db)
    except Exception:
        db.rollback()
    finally:
        db.close()


def _migrate() -> None:
    from sqlalchemy import text
    with engine.begin() as conn:
        try:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            conn.exec_driver_sql("PRAGMA busy_timeout=5000")
        except Exception:
            pass
        cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(events)").fetchall()}
        if "deleted" not in cols:
            conn.exec_driver_sql("ALTER TABLE events ADD COLUMN deleted INTEGER DEFAULT 0")
        try:
            ecols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(entities)").fetchall()}
            if ecols and "map_x" not in ecols:
                conn.exec_driver_sql("ALTER TABLE entities ADD COLUMN map_x INTEGER")
            if ecols and "map_y" not in ecols:
                conn.exec_driver_sql("ALTER TABLE entities ADD COLUMN map_y INTEGER")
            if ecols and "target_x" not in ecols:
                conn.exec_driver_sql("ALTER TABLE entities ADD COLUMN target_x INTEGER")
            if ecols and "target_y" not in ecols:
                conn.exec_driver_sql("ALTER TABLE entities ADD COLUMN target_y INTEGER")
            if ecols and "move_speed" not in ecols:
                conn.exec_driver_sql("ALTER TABLE entities ADD COLUMN move_speed REAL DEFAULT 1.0")
            if ecols and "sim_state" not in ecols:
                conn.exec_driver_sql("ALTER TABLE entities ADD COLUMN sim_state TEXT DEFAULT '{}'")
            if ecols and "persona" not in ecols:
                conn.exec_driver_sql("ALTER TABLE entities ADD COLUMN persona TEXT DEFAULT '{}'")
            if ecols and "memories" not in ecols:
                conn.exec_driver_sql("ALTER TABLE entities ADD COLUMN memories TEXT DEFAULT '[]'")
            if ecols and "tags" not in ecols:
                conn.exec_driver_sql("ALTER TABLE entities ADD COLUMN tags TEXT DEFAULT '[]'")
            if ecols and "pinned" not in ecols:
                conn.exec_driver_sql("ALTER TABLE entities ADD COLUMN pinned INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            tcols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(world_templates)").fetchall()}
            if tcols:
                if "canonical_outline" not in tcols:
                    conn.exec_driver_sql("ALTER TABLE world_templates ADD COLUMN canonical_outline TEXT DEFAULT '[]'")
                if "series" not in tcols:
                    conn.exec_driver_sql("ALTER TABLE world_templates ADD COLUMN series VARCHAR DEFAULT ''")
                if "series_order" not in tcols:
                    conn.exec_driver_sql("ALTER TABLE world_templates ADD COLUMN series_order INTEGER DEFAULT 0")
                if "max_steps_hint" not in tcols:
                    conn.exec_driver_sql("ALTER TABLE world_templates ADD COLUMN max_steps_hint INTEGER DEFAULT 30")
        except Exception:
            pass
        try:
            wcols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(worlds)").fetchall()}
            if wcols and "template_id" not in wcols:
                conn.exec_driver_sql("ALTER TABLE worlds ADD COLUMN template_id VARCHAR")
            if wcols and "outline_progress" not in wcols:
                conn.exec_driver_sql("ALTER TABLE worlds ADD COLUMN outline_progress TEXT DEFAULT '{}'")
            if wcols and "max_tick" not in wcols:
                conn.exec_driver_sql("ALTER TABLE worlds ADD COLUMN max_tick INTEGER DEFAULT 0")
            if wcols and "map_w" not in wcols:
                conn.exec_driver_sql("ALTER TABLE worlds ADD COLUMN map_w INTEGER DEFAULT 0")
            if wcols and "map_h" not in wcols:
                conn.exec_driver_sql("ALTER TABLE worlds ADD COLUMN map_h INTEGER DEFAULT 0")
            if wcols and "map_seed" not in wcols:
                conn.exec_driver_sql("ALTER TABLE worlds ADD COLUMN map_seed INTEGER DEFAULT 0")
            if wcols and "map_meta" not in wcols:
                conn.exec_driver_sql("ALTER TABLE worlds ADD COLUMN map_meta TEXT DEFAULT '{}'")
            if wcols and "outline" not in wcols:
                conn.exec_driver_sql("ALTER TABLE worlds ADD COLUMN outline TEXT DEFAULT ''")
            # 阶段 0：多 agent 管线相关字段
            if wcols and "style_profile_id" not in wcols:
                conn.exec_driver_sql("ALTER TABLE worlds ADD COLUMN style_profile_id VARCHAR")
            if wcols and "embedding_provider" not in wcols:
                conn.exec_driver_sql("ALTER TABLE worlds ADD COLUMN embedding_provider VARCHAR DEFAULT ''")
            if wcols and "author_model_override" not in wcols:
                conn.exec_driver_sql("ALTER TABLE worlds ADD COLUMN author_model_override VARCHAR DEFAULT ''")
            if wcols and "editor_model_override" not in wcols:
                conn.exec_driver_sql("ALTER TABLE worlds ADD COLUMN editor_model_override VARCHAR DEFAULT ''")
            if wcols and "reader_model_override" not in wcols:
                conn.exec_driver_sql("ALTER TABLE worlds ADD COLUMN reader_model_override VARCHAR DEFAULT ''")
            if wcols and "manuscript_chunks" not in wcols:
                conn.exec_driver_sql("ALTER TABLE worlds ADD COLUMN manuscript_chunks TEXT DEFAULT '[]'")
            if wcols and "manuscript_draft_events" not in wcols:
                conn.exec_driver_sql("ALTER TABLE worlds ADD COLUMN manuscript_draft_events TEXT DEFAULT '[]'")
            if wcols and "agent_pipeline" not in wcols:
                conn.exec_driver_sql("ALTER TABLE worlds ADD COLUMN agent_pipeline TEXT")
        except Exception:
            pass
        # 阶段 0：NarrativeLog 加多 agent 字段
        try:
            ncols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(narrative_logs)").fetchall()}
            if ncols and "revision_index" not in ncols:
                conn.exec_driver_sql("ALTER TABLE narrative_logs ADD COLUMN revision_index INTEGER DEFAULT 0")
            if ncols and "parent_log_id" not in ncols:
                conn.exec_driver_sql("ALTER TABLE narrative_logs ADD COLUMN parent_log_id VARCHAR")
            # 现有记录的 role 保持不动（兼容老的 'narrator'/'system'）；新管线写入会用
            # 'director_draft' / 'author_final' / 'editor_critique' / 'reader_feedback'。
            # 显式记录的索引 sqlalchemy create_all 已建。
        except Exception:
            pass
        # B1: ChapterMarker 加 summary（章节凝练）
        try:
            cmcols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(chapter_markers)").fetchall()}
            if cmcols and "summary" not in cmcols:
                conn.exec_driver_sql("ALTER TABLE chapter_markers ADD COLUMN summary TEXT DEFAULT ''")
        except Exception:
            pass
        # A2: IssuePatch 加 original_snapshot（apply 时存改前文本，用于 undo）
        try:
            ipcols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(issue_patches)").fetchall()}
            if ipcols and "original_snapshot" not in ipcols:
                conn.exec_driver_sql("ALTER TABLE issue_patches ADD COLUMN original_snapshot TEXT DEFAULT ''")
        except Exception:
            pass
        # manuscript_chunks JSON → 独立表
        try:
            existing = conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='manuscript_chunks'"
            ).fetchone()
            if not existing:
                conn.exec_driver_sql("""
                    CREATE TABLE manuscript_chunks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        world_id VARCHAR NOT NULL,
                        chapter_index INTEGER NOT NULL,
                        title VARCHAR DEFAULT '',
                        text TEXT DEFAULT ''
                    )
                """)
                conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_manuscript_chunks_world ON manuscript_chunks (world_id)")
                # 从旧 JSON 迁移
                rows = conn.exec_driver_sql("SELECT id, manuscript_chunks FROM worlds WHERE manuscript_chunks IS NOT NULL AND manuscript_chunks != '[]'").fetchall()
                import json
                for world_id, raw in rows:
                    try:
                        chunks = json.loads(raw) if isinstance(raw, str) else (raw or [])
                        for i, c in enumerate(chunks):
                            conn.exec_driver_sql(
                                "INSERT INTO manuscript_chunks (world_id, chapter_index, title, text) VALUES (?, ?, ?, ?)",
                                (world_id, i + 1, str(c.get("title") or "")[:500], str(c.get("text") or ""))
                            )
                    except Exception:
                        pass
        except Exception:
            pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
