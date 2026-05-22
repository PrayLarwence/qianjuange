"""数据目录解析: 开发模式用仓库内 data/, 打包模式用用户目录.

优先级:
1. 环境变量 NARRATIVE_SANDBOX_DATA_DIR (CI / 运维强制覆盖)
2. 仓库根 ./data 已存在 → 视为开发模式, 直接用
3. 否则按平台落到用户数据目录:
   - Windows: %APPDATA%/Qianjuange
   - macOS:   ~/Library/Application Support/Qianjuange
   - Linux:   ${XDG_DATA_HOME:-~/.local/share}/qianjuange

历史目录 (NarrativeSandbox / narrative-sandbox) 存在时, 首次启动自动迁移过来,
保证老用户升级无感.

所有读写文件的模块 *都* 应当从这里 import, 不要再写 parents[N]/'data'.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_APP_NAME = "Qianjuange"
_APP_NAME_LINUX = "qianjuange"
_LEGACY_NAMES = ("NarrativeSandbox",)
_LEGACY_NAMES_LINUX = ("narrative-sandbox",)


def _is_frozen() -> bool:
    """PyInstaller / py2exe / cx_Freeze 等都设置 sys.frozen."""
    return bool(getattr(sys, "frozen", False))


def _platform_user_data_root() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base)
        return Path.home() / "AppData" / "Roaming"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg)
    return Path.home() / ".local" / "share"


def _platform_user_data_dir() -> Path:
    root = _platform_user_data_root()
    name = _APP_NAME_LINUX if sys.platform not in ("win32", "darwin") else _APP_NAME
    new = root / name
    if new.exists():
        return new
    # 一次性迁移老目录
    legacy_names = _LEGACY_NAMES_LINUX if sys.platform not in ("win32", "darwin") else _LEGACY_NAMES
    for legacy in legacy_names:
        old = root / legacy
        if old.is_dir():
            try:
                shutil.move(str(old), str(new))
                break
            except Exception:
                # 迁移失败不致命: 退到 new (可能为空), 让首启重新建表
                new.mkdir(parents=True, exist_ok=True)
                break
    return new


def _resolve_repo_data_dir() -> Path | None:
    """仓库 data/ 目录: 仅当存在并且不是 frozen 时使用."""
    if _is_frozen():
        return None
    here = Path(__file__).resolve()
    # backend/app/paths.py → parents[2] 是仓库根
    repo_data = here.parents[2] / "data"
    if repo_data.is_dir():
        return repo_data
    return None


def _resolve_data_dir() -> Path:
    override = os.environ.get("NARRATIVE_SANDBOX_DATA_DIR")
    if override:
        p = Path(override).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        return p
    repo_dir = _resolve_repo_data_dir()
    if repo_dir is not None:
        return repo_dir
    p = _platform_user_data_dir()
    p.mkdir(parents=True, exist_ok=True)
    return p


DATA_DIR: Path = _resolve_data_dir()

DB_PATH: Path = DATA_DIR / "world.db"
LLM_CONFIG_PATH: Path = DATA_DIR / "llm_config.json"
AGENT_PIPELINE_DEFAULT_PATH: Path = DATA_DIR / "agent_pipeline_default.json"
MAPS_DIR: Path = DATA_DIR / "maps"


def ensure_layout() -> None:
    """显式建出常用子目录, 让首次启动不留空洞."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MAPS_DIR.mkdir(parents=True, exist_ok=True)


__all__ = [
    "DATA_DIR",
    "DB_PATH",
    "LLM_CONFIG_PATH",
    "AGENT_PIPELINE_DEFAULT_PATH",
    "MAPS_DIR",
    "ensure_layout",
]
