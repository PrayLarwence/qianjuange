# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for 千卷阁 (Qianjuange) 桌面版.

构建步骤 (在仓库根目录下):
    cd frontend-next && npm run build      # 先出 dist/
    cd ..
    .venv-build\\Scripts\\pyinstaller --noconfirm build/qianjuange.spec

产物:
    dist/Qianjuange/Qianjuange.exe   (单目录形态, 启动更快)

打包内容:
    - backend/app/**             业务代码
    - backend/desktop_launcher.py 入口
    - frontend-next/dist/**      → 解到 _MEIPASS/static (main.py 已按这个位置查找)
    - 关键 hidden imports        uvicorn loop/protocol 子模块, dotenv 等

用户数据 (db, maps, llm_config, jobs) 不打进 exe; 由 app/paths.py 在
首次启动时落到 %APPDATA%\\Qianjuange\\ (老 NarrativeSandbox 目录会自动迁移).
"""
from pathlib import Path

# spec 执行时 cwd = 调用 pyinstaller 的目录, 不是 spec 所在目录.
# 用 SPECPATH (PyInstaller 注入的全局) 锚定项目根.
ROOT = Path(SPECPATH).resolve().parent  # noqa: F821
BACKEND = ROOT / "backend"
DIST_FRONTEND = ROOT / "frontend-next" / "dist"
ICON = ROOT / "build" / "assets" / "icon.ico"

if not DIST_FRONTEND.exists():
    raise SystemExit(
        f"[spec] frontend dist not found at {DIST_FRONTEND}; "
        "run 'npm run build' in frontend-next first."
    )

datas = [
    (str(DIST_FRONTEND), "static"),  # _MEIPASS/static/{index.html, assets/...}
    (str(ICON), "assets"),            # _MEIPASS/assets/icon.ico (webview 窗口图标用)
]

hiddenimports = [
    # uvicorn 的 worker 通过字符串 import, PyInstaller 静态分析会漏
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "uvicorn.logging",
    # dotenv / sqlalchemy 方言
    "dotenv",
    "sqlalchemy.dialects.sqlite",
    # pywebview Windows 后端
    "webview.platforms.winforms",
]


a = Analysis(
    [str(BACKEND / "desktop_launcher.py")],
    pathex=[str(BACKEND)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "test", "unittest", "pytest", "pytest_asyncio",
        "matplotlib", "IPython", "jedi",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Qianjuange",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,        # 桌面 app, 不带控制台窗口. 调试时临时改 True 看 uvicorn / pywebview 日志.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON),       # exe 文件图标 (任务栏 / 资源管理器)
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Qianjuange",
)
