"""桌面壳: 嵌入式启动 backend + PyWebView 窗口指向 127.0.0.1:<auto-port>.

设计:
- 单进程, 后台线程跑 uvicorn.Server.serve() (不走 CLI / 不开 reload)
- 端口让 OS 选: bind ('127.0.0.1', 0), 服务起来后回读真实端口
- 主线程跑 webview, 窗口关闭 → 通知 server.should_exit, 等线程结束后退出进程

为什么不直接用浏览器: 用户要"双击 exe 像桌面应用". WebView2 (Windows 自带) 走系统组件,
打包体积小; pywebview 内部用 pythonnet 调 WebView2.

环境变量:
- NARRATIVE_SANDBOX_HEADLESS=1   不开 webview, 只跑 backend (调试 / 自测用)
- NARRATIVE_SANDBOX_DATA_DIR     强制覆盖数据目录 (见 app/paths.py)

打包 (PyInstaller) 时, 这个文件是入口; 见 build/qianjuange.spec.
"""
from __future__ import annotations

import logging
import os
import signal
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Optional

# 让 backend/app 能 import (开发模式直接跑这个文件时需要)
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def _redirect_std_streams_if_needed() -> Path | None:
    """PyInstaller windowed 模式下 sys.stdout/stderr 是 None, 任何 print/logging 都会崩.
    把它们重定向到 <DATA_DIR>/desktop.log, 顺带留个日志方便排查."""
    if sys.stdout is not None and sys.stderr is not None:
        return None
    try:
        from app.paths import DATA_DIR, ensure_layout
        ensure_layout()
        log_path = DATA_DIR / "desktop.log"
    except Exception:
        # paths 还没就绪 (理论上不会), 落到 exe 同目录 fallback
        base = Path(getattr(sys, "_MEIPASS", HERE))
        log_path = base / "desktop.log"
    f = open(log_path, "a", encoding="utf-8", buffering=1)  # line-buffered
    if sys.stdout is None:
        sys.stdout = f  # type: ignore[assignment]
    if sys.stderr is None:
        sys.stderr = f  # type: ignore[assignment]
    return log_path


_LOG_FILE = _redirect_std_streams_if_needed()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("desktop")
if _LOG_FILE is not None:
    log.info("stdout/stderr redirected to %s", _LOG_FILE)


def _pick_free_port() -> int:
    """让 OS 给一个空闲端口. 这里只是先占位探测, 真正的 port 由 uvicorn 自己 bind."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _BackendThread(threading.Thread):
    """后台跑 uvicorn.Server. host/port 固定 127.0.0.1, port 在 start_and_wait_ready 里回读."""

    def __init__(self) -> None:
        super().__init__(name="uvicorn-backend", daemon=True)
        self.port: Optional[int] = None
        self._server = None  # uvicorn.Server, 启动后赋值
        self._ready = threading.Event()
        self._error: Optional[BaseException] = None

    def run(self) -> None:
        try:
            import uvicorn
            from app.main import app

            port = _pick_free_port()
            config = uvicorn.Config(
                app, host="127.0.0.1", port=port,
                log_level="info", access_log=False, lifespan="on",
            )
            self._server = uvicorn.Server(config)
            self.port = port
            # uvicorn 启动是异步的, 用 startup_complete 当就绪信号
            original_startup = self._server.startup

            async def _wrapped_startup(*a, **kw):  # type: ignore[no-redef]
                await original_startup(*a, **kw)
                self._ready.set()

            self._server.startup = _wrapped_startup  # type: ignore[assignment]
            self._server.run()  # 阻塞直到 should_exit
        except BaseException as e:  # 让主线程能感知
            self._error = e
            self._ready.set()
            log.exception("backend thread crashed")

    def start_and_wait_ready(self, timeout: float = 30.0) -> int:
        self.start()
        if not self._ready.wait(timeout):
            raise RuntimeError(f"backend did not start within {timeout}s")
        if self._error is not None:
            raise self._error
        assert self.port is not None
        return self.port

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True


def _wait_health(port: int, timeout: float = 15.0) -> None:
    """uvicorn lifespan ready 之后再 poll /health 确保路由 + DB 起来."""
    import urllib.request
    deadline = time.monotonic() + timeout
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as resp:
                if resp.status == 200:
                    return
        except Exception as e:
            last_err = e
            time.sleep(0.2)
    raise RuntimeError(f"health check timeout: {last_err}")


def main() -> int:
    headless = os.environ.get("NARRATIVE_SANDBOX_HEADLESS") == "1"

    backend = _BackendThread()
    try:
        port = backend.start_and_wait_ready()
        log.info("backend bound on 127.0.0.1:%d", port)
        _wait_health(port)
        log.info("backend healthy")
    except Exception as e:
        log.error("backend startup failed: %s", e)
        backend.stop()
        backend.join(timeout=5)
        return 2

    # 写运行时 stamp, 方便外部脚本/自测脚本拿到端口
    try:
        from app.paths import DATA_DIR
        stamp = DATA_DIR / ".runtime_port"
        stamp.write_text(str(port), encoding="utf-8")
    except Exception:
        stamp = None  # type: ignore[assignment]
        log.warning("could not write runtime port stamp", exc_info=True)

    def _shutdown_and_cleanup() -> None:
        log.info("shutting down backend")
        backend.stop()
        backend.join(timeout=10)
        if stamp is not None:
            try:
                stamp.unlink(missing_ok=True)
            except Exception:
                pass

    if headless:
        # 等 SIGINT / SIGTERM
        log.info("HEADLESS mode: backend ready at http://127.0.0.1:%d/, press Ctrl+C to stop", port)
        stop_event = threading.Event()
        def _on_signal(_sig, _frame):
            stop_event.set()
        signal.signal(signal.SIGINT, _on_signal)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, _on_signal)
        try:
            while not stop_event.is_set():
                stop_event.wait(0.5)
        finally:
            _shutdown_and_cleanup()
        return 0

    try:
        import webview
    except ImportError:
        log.error("pywebview not installed; run pip install pywebview")
        _shutdown_and_cleanup()
        return 3

    url = f"http://127.0.0.1:{port}/"
    webview.create_window(
        title="千卷阁",
        url=url,
        width=1280, height=820,
        min_size=(960, 640),
        confirm_close=False,
    )
    try:
        webview.start()  # 阻塞至窗口关闭
    finally:
        _shutdown_and_cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
