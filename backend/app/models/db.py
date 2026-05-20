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
        except Exception:
            pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
