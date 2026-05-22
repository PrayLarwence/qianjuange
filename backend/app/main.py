from __future__ import annotations
import os
import sys
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from dotenv import load_dotenv

load_dotenv()

from .models import init_db
from .api.routes import router as api_router
from .api.map_routes import router as map_router
from .api.dialogue_routes import router as dialogue_router
from .api.lore_routes import router as lore_router
from .api.stats_routes import router as stats_router
from .api.storyboard_aux_routes import router as storyboard_aux_router
from .providers import load_config


def _resolve_static_roots() -> tuple[Path | None, Path | None]:
    """开发模式: 仓库 ./frontend & ./frontend-next/dist; 打包模式: PyInstaller _MEIPASS/static."""
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", "."))
        dist = meipass / "static"
        return None, dist if dist.exists() else None
    root = Path(__file__).resolve().parents[2]
    legacy = root / "frontend"
    dist = root / "frontend-next" / "dist"
    return (legacy if legacy.exists() else None), (dist if dist.exists() else None)


FRONTEND_DIR, DIST_DIR = _resolve_static_roots()

app = FastAPI(title="千卷阁", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup():
    init_db()
    try:
        from .models import SessionLocal
        from .seeds import seed_official_templates
        db = SessionLocal()
        try:
            seed_official_templates(db, force=False)
        finally:
            db.close()
    except Exception as e:
        # 种子失败不应阻塞启动
        import logging
        logging.getLogger(__name__).warning("seed_official_templates skipped: %s", e)


app.include_router(api_router, prefix="/api")
app.include_router(map_router, prefix="/api")
app.include_router(dialogue_router, prefix="/api")
app.include_router(lore_router, prefix="/api")
app.include_router(stats_router, prefix="/api")
app.include_router(storyboard_aux_router, prefix="/api")


@app.get("/health")
def health():
    cfg = load_config()
    return {"ok": True, "provider": cfg.get("active", "claude")}


if FRONTEND_DIR is not None:
    # 旧前端：挂到 /legacy，并保留 /static 以兼容旧 index.html 内部的绝对路径引用
    app.mount("/legacy", StaticFiles(directory=FRONTEND_DIR, html=True), name="legacy")
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

if DIST_DIR is not None:
    # 新前端：Vite 构建产物挂到 /assets，其余路径走 SPA fallback
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    @app.get("/favicon.ico")
    def favicon_dist():
        return FileResponse(DIST_DIR / "favicon.ico")

    @app.get("/")
    def index():
        return FileResponse(DIST_DIR / "index.html")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        return FileResponse(DIST_DIR / "index.html")
elif FRONTEND_DIR is not None:
    # 没构建新版时，根路径回退到旧版
    @app.get("/")
    def index():
        return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/favicon.ico")
def favicon():
    # 仅当上面两个 favicon_dist / index 都没注册时兜底 (理论上不会到这里)
    return Response(status_code=204)
