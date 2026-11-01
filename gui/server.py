from __future__ import annotations

import argparse
import ctypes
import hmac
import json
import logging
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import quote
from urllib.request import urlopen

from flask import Flask, Response, abort, jsonify, request, send_file, send_from_directory
from waitress.server import create_server

from rewards_bot.config import ConfigError
from rewards_bot.logging_setup import setup_logging
from rewards_bot.paths import PROJECT_ROOT, RESOURCE_ROOT
from rewards_bot.points import read_points_summary
from rewards_bot.tasks_catalog import catalog_payload, points_forecast

from .power_mode import detect_safe_background_apps
from .services import Runtime, now_iso
from .settings_store import SettingsError, SettingsStore
from .tray import TrayActions, TrayController

APP_NAME = "Rewards Pilot"
VERSION = "1.0.1"
TOKEN_HEADER = "X-App-Token"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


def _ensure_queries_file() -> None:
    """onefile 打包后，把内置搜索词表补到 exe 所在目录。"""
    target = PROJECT_ROOT / "queries.txt"
    source = RESOURCE_ROOT / "queries.txt"
    if target.exists() or not source.exists() or source.resolve() == target.resolve():
        return
    try:
        shutil.copyfile(source, target)
    except OSError:
        logging.getLogger("rewards_bot.gui").warning("无法写入搜索词表：%s", target)


def find_free_port(preferred: int = 8765) -> int:
    # 不要设置 SO_REUSEADDR：Windows 上它会允许两个进程同时监听同一端口，
    # 导致浏览器被路由到别的本地服务。
    for port in range(preferred, preferred + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def create_app(runtime: Runtime, token: str) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.json.ensure_ascii = False
    dist = (RESOURCE_ROOT / "web" / "dist").resolve()
    app.extensions["runtime"] = runtime
    app.extensions["token"] = token
    app.extensions["dist"] = dist
    stop_event = threading.Event()
    app.extensions["stop_event"] = stop_event
    selftest_lock = threading.Lock()
    log = logging.getLogger("rewards_bot.gui.http")

    def error(message: str, status: int = 400):
        return jsonify({"ok": False, "error": message}), status

    def index_response() -> Response:
        index_path = dist / "index.html"
        if not index_path.exists():
            return Response(
                _fallback_page(),
                status=503,
                content_type="text/html; charset=utf-8",
            )
        html = index_path.read_text(encoding="utf-8")
        inject = (
            "<script>window.__APP_TOKEN__="
            + json.dumps(token)
            + ";window.__APP_VERSION__="
            + json.dumps(VERSION)
            + ";</script>"
        )
        if "</head>" in html:
            html = html.replace("</head>", inject + "</head>", 1)
        else:
            html = inject + html
        return Response(
            html,
            content_type="text/html; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )

    @app.before_request
    def guard():
        host = (request.host or "").split(":", 1)[0].lower()
        if host not in {"127.0.0.1", "localhost"}:
            return error("主机不被允许。", 403)
        if request.path.startswith("/api/"):
            if request.path == "/api/health":
                return None
            supplied = request.headers.get(TOKEN_HEADER) or request.args.get("token") or ""
            if not hmac.compare_digest(str(supplied), token):
                return error("界面令牌无效，请从应用窗口重新打开。", 401)
        return None

    @app.after_request
    def security_headers(response: Response) -> Response:
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if response.mimetype == "text/html":
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data:; "
                "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
                "font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
            )
        return response

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True, "app": APP_NAME, "version": VERSION})

    @app.get("/api/state")
    def state():
        try:
            cfg = runtime.store.load()
        except Exception as exc:
            return error(f"配置读取失败：{exc}", 500)
        return jsonify(
            {
                "ok": True,
                "version": VERSION,
                "app": {
                    "name": APP_NAME,
                    "config_path": str(cfg.path),
                    "frozen": bool(getattr(sys, "frozen", False)),
                    "server_time": now_iso(),
                },
                "summary": {
                    "mode": cfg.general.mode,
                    "run_at": cfg.general.run_at,
                    "timezone": cfg.general.timezone,
                    "headless": cfg.general.headless,
                    "catch_up": cfg.general.catch_up,
                    "auto_exit_after_run": cfg.general.auto_exit_after_run,
                    "browser_channel": cfg.general.browser_channel,
                    "auto_claim": cfg.basic.auto_claim,
                    "search_enabled": cfg.basic.search_enabled,
                    "task_types": list(cfg.basic.task_types),
                    "task_type_count": len(cfg.basic.task_types),
                    "points_forecast": points_forecast(
                        cfg.basic.task_types,
                        search_enabled=cfg.basic.search_enabled,
                        search_count=cfg.basic.search_count,
                        auto_claim=cfg.basic.auto_claim,
                    ),
                    "api_key_set": bool(cfg.advanced.api_key),
                    "model": cfg.advanced.model,
                },
                "points": read_points_summary(
                    cfg.general.state_dir, cfg.general.timezone
                ),
                "job": runtime.job.snapshot(),
                "login": runtime.login.snapshot(),
                "scheduler": runtime.scheduler.snapshot(),
                "power": runtime.power.snapshot(),
                "onboarding": runtime.onboarding.snapshot(),
            }
        )

    @app.get("/api/power/apps")
    def power_apps():
        try:
            apps = detect_safe_background_apps()
        except Exception as exc:
            log.exception("扫描后台应用失败")
            return error(f"扫描后台应用失败：{exc}", 500)
        return jsonify(
            {
                "ok": True,
                "apps": apps,
                "supported": runtime.power.snapshot().get("supported", False),
            }
        )

    @app.post("/api/power/activate")
    def power_activate():
        payload = request.get_json(silent=True) or {}
        close_apps = payload.get("close_apps") if isinstance(payload, dict) else None
        if close_apps is None:
            close_apps = []
        if not isinstance(close_apps, list) or not all(
            isinstance(item, str) for item in close_apps
        ):
            return error("close_apps 必须是字符串数组。")
        if len(close_apps) > 30:
            return error("一次最多选择 30 个后台应用。")
        try:
            state = runtime.power.activate(close_apps)
        except RuntimeError as exc:
            return error(str(exc), 409)
        except Exception as exc:
            log.exception("开启低功耗模式失败")
            return error(f"开启低功耗模式失败：{str(exc)[:300]}", 500)
        log.info("低功耗挂机已开启。")
        return jsonify({"ok": True, "power": state, "message": state["last_message"]})

    @app.post("/api/power/deactivate")
    def power_deactivate():
        try:
            state = runtime.power.deactivate()
        except Exception as exc:
            log.exception("关闭低功耗模式失败")
            return error(f"关闭低功耗模式失败：{str(exc)[:300]}", 500)
        log.info("低功耗挂机已关闭。")
        return jsonify({"ok": True, "power": state, "message": state["last_message"]})

    @app.get("/api/logs")
    def logs():
        try:
            after = max(0, int(request.args.get("after", "0")))
            limit = max(1, min(800, int(request.args.get("limit", "300"))))
        except ValueError:
            return error("日志参数无效。")
        items, last_seq = runtime.log_buffer.since(after, limit)
        return jsonify({"ok": True, "items": items, "last_seq": last_seq})

    @app.get("/api/settings")
    def get_settings():
        try:
            cfg = runtime.store.load()
        except Exception as exc:
            return error(f"配置读取失败：{exc}", 500)
        return jsonify(
            {
                "ok": True,
                "settings": runtime.store.public(cfg),
                "task_catalog": catalog_payload(),
                "autostart": runtime.autostart.snapshot(),
            }
        )

    @app.put("/api/settings")
    @app.post("/api/settings")
    def save_settings():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return error("设置内容必须是 JSON 对象。")
        try:
            cfg = runtime.store.update(payload)
        except (SettingsError, ConfigError) as exc:
            return error(str(exc), 400)
        except Exception as exc:
            log.exception("保存设置失败")
            return error(f"保存设置失败：{exc}", 500)
        startup_warning: str | None = None
        try:
            startup_ok, startup_message = runtime.autostart.sync(
                cfg.general.auto_exit_after_run
            )
            if startup_ok:
                log.info("%s", startup_message)
            else:
                startup_warning = startup_message
                log.warning("%s", startup_message)
        except Exception as exc:
            startup_warning = f"开机启动登记失败：{str(exc)[:240]}"
            log.exception("同步开机启动失败")
        runtime.scheduler.restart()
        log.info("界面已保存设置。")
        payload = {
            "ok": True,
            "settings": runtime.store.public(cfg),
            "task_catalog": catalog_payload(),
            "autostart": runtime.autostart.snapshot(),
        }
        if startup_warning:
            payload["warning"] = startup_warning
        return jsonify(payload)

    @app.get("/api/onboarding")
    def onboarding_status():
        return jsonify({"ok": True, "onboarding": runtime.onboarding.snapshot()})

    @app.post("/api/onboarding/complete")
    def onboarding_complete():
        payload = request.get_json(silent=True) or {}
        action = payload.get("action", "completed") if isinstance(payload, dict) else "completed"
        if action not in {"completed", "skipped"}:
            return error("初始化教程状态无效。")
        try:
            state = runtime.onboarding.complete(action)
        except ValueError as exc:
            return error(str(exc))
        except Exception as exc:
            log.exception("保存初始化教程状态失败")
            return error(f"保存初始化教程状态失败：{str(exc)[:240]}", 500)
        return jsonify(
            {
                "ok": True,
                "onboarding": state,
                "message": "初始化教程状态已保存。",
            }
        )

    @app.post("/api/run")
    def run():
        payload = request.get_json(silent=True) or {}
        mode = payload.get("mode") if isinstance(payload, dict) else None
        if mode is not None and mode not in {"basic", "advanced"}:
            return error("运行模式无效。")
        ok, message = runtime.job.start(mode=mode, trigger="manual")
        if not ok:
            return error(message, 409)
        return jsonify({"ok": True, "message": message, "job": runtime.job.snapshot()}), 202

    @app.post("/api/login/start")
    def login_start():
        ok, message = runtime.login.start()
        if not ok:
            return error(message, 409)
        return jsonify({"ok": True, "message": message, "login": runtime.login.snapshot()}), 202

    @app.post("/api/login/finish")
    def login_finish():
        ok, message = runtime.login.finish()
        if not ok:
            return error(message, 409)
        return jsonify({"ok": True, "message": message, "login": runtime.login.snapshot()}), 202

    @app.post("/api/login/cancel")
    def login_cancel():
        runtime.login.cancel()
        return jsonify({"ok": True, "login": runtime.login.snapshot()})

    @app.post("/api/scheduler/start")
    def scheduler_start():
        payload = request.get_json(silent=True) or {}
        catch_up = payload.get("catch_up") if isinstance(payload, dict) else None
        if catch_up is not None and not isinstance(catch_up, bool):
            return error("catch_up 必须是布尔值。")
        ok, message = runtime.scheduler.start(catch_up=catch_up)
        if not ok:
            return error(message, 409)
        return jsonify({"ok": True, "message": message, "scheduler": runtime.scheduler.snapshot()})

    @app.post("/api/scheduler/stop")
    def scheduler_stop():
        ok, message = runtime.scheduler.stop()
        if not ok:
            return error(message, 409)
        return jsonify({"ok": True, "message": message, "scheduler": runtime.scheduler.snapshot()})

    @app.post("/api/selftest")
    def selftest():
        if runtime.job.running:
            return error("任务运行中，暂时不能执行环境自检。", 409)
        if runtime.login.active:
            return error("登录窗口打开中，暂时不能执行环境自检。", 409)
        if not selftest_lock.acquire(blocking=False):
            return error("自检正在进行。", 409)
        started = time.monotonic()
        try:
            cfg = runtime.store.load()
            from playwright.sync_api import sync_playwright

            kwargs: dict = {"headless": True, "timeout": 30_000}
            if cfg.general.browser_channel:
                kwargs["channel"] = cfg.general.browser_channel
            with sync_playwright() as p:
                browser = p.chromium.launch(**kwargs)
                try:
                    page = browser.new_page()
                    page.goto("about:blank", timeout=15_000)
                    value = page.evaluate("2 + 2")
                finally:
                    browser.close()
            if value != 4:
                raise RuntimeError("浏览器脚本计算结果异常。")
            elapsed = int((time.monotonic() - started) * 1000)
            log.info("环境自检通过，用时 %s ms。", elapsed)
            return jsonify(
                {
                    "ok": True,
                    "message": "Edge / Playwright 启动正常，任务环境可用。",
                    "ms": elapsed,
                    "channel": cfg.general.browser_channel or "bundled-chromium",
                }
            )
        except Exception as exc:
            elapsed = int((time.monotonic() - started) * 1000)
            log.exception("环境自检失败")
            hint = ""
            if "Executable doesn't exist" in str(exc) or "channel" in str(exc).lower():
                hint = " 请确认已安装 Microsoft Edge，或在 config.toml 中设置 browser_channel = \"msedge\"。"
            return jsonify(
                {
                    "ok": False,
                    "message": f"{str(exc)[:400]}{hint}",
                    "ms": elapsed,
                }
            ), 500
        finally:
            selftest_lock.release()

    @app.get("/api/screenshots")
    def screenshots():
        try:
            cfg = runtime.store.load()
        except Exception:
            return jsonify({"ok": True, "groups": []})
        root = (cfg.general.state_dir / "screenshots").resolve()
        groups = []
        if root.is_dir():
            try:
                dirs = sorted(
                    [item for item in root.iterdir() if item.is_dir()],
                    key=lambda item: item.name,
                    reverse=True,
                )[:4]
            except OSError:
                dirs = []
            for folder in dirs:
                files = []
                try:
                    candidates = sorted(
                        [item for item in folder.glob("*.png") if item.is_file()],
                        key=lambda item: item.stat().st_mtime,
                        reverse=True,
                    )[:40]
                except OSError:
                    candidates = []
                for file in candidates:
                    try:
                        stat = file.stat()
                    except OSError:
                        continue
                    files.append(
                        {
                            "name": file.name,
                            "url": "/api/screenshots/"
                            + quote(folder.name)
                            + "/"
                            + quote(file.name),
                            "size": stat.st_size,
                            "mtime": datetime.fromtimestamp(stat.st_mtime)
                            .astimezone()
                            .isoformat(timespec="seconds"),
                        }
                    )
                if files:
                    groups.append({"run": folder.name, "files": files})
        return jsonify({"ok": True, "groups": groups})

    @app.get("/api/screenshots/<run_id>/<name>")
    def screenshot_file(run_id: str, name: str):
        if not _SAFE_NAME.match(run_id) or not _SAFE_NAME.match(name) or not name.endswith(".png"):
            abort(404)
        try:
            cfg = runtime.store.load()
        except Exception:
            abort(404)
        root = (cfg.general.state_dir / "screenshots").resolve()
        path = (root / run_id / name).resolve()
        if root not in path.parents or not path.is_file():
            abort(404)
        return send_file(
            path,
            mimetype="image/png",
            max_age=30,
            download_name=name,
            conditional=True,
        )

    @app.post("/api/shutdown")
    def shutdown():
        ok, message = request_shutdown()
        if not ok:
            return error(message, 409)
        return jsonify({"ok": True, "message": message})

    def request_shutdown(reason: str = "界面请求退出应用。") -> tuple[bool, str]:
        if runtime.job.running:
            return False, "任务仍在运行，请等待结束再退出。"
        log.info(reason)
        runtime.login.cancel()
        runtime.scheduler.stop()
        threading.Timer(0.8, stop_event.set).start()
        return True, "应用正在退出。"

    app.extensions["request_shutdown"] = request_shutdown

    @app.get("/")
    def index():
        return index_response()

    @app.get("/<path:path>")
    def static_or_index(path: str):
        if path.startswith("api/"):
            abort(404)
        if dist.is_dir():
            candidate = (dist / path).resolve()
            if dist in candidate.parents and candidate.is_file():
                return send_from_directory(str(dist), path)
        return index_response()

    @app.errorhandler(404)
    def not_found(_exc):
        if request.path.startswith("/api/"):
            return error("接口不存在。", 404)
        return index_response()

    return app


def _fallback_page() -> str:
    return """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rewards Pilot</title>
<style>
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#070b14;color:#e7eefc;
font-family:'Segoe UI','Microsoft YaHei UI',sans-serif}
.card{max-width:620px;padding:40px;border-radius:28px;background:rgba(255,255,255,.05);
border:1px solid rgba(255,255,255,.12)}
h1{margin:0 0 12px;font-size:32px}p{color:#9fb0cc;line-height:1.8}
code{background:rgba(255,255,255,.08);padding:3px 8px;border-radius:8px}
</style></head><body><div class="card">
<h1>界面资源尚未构建</h1>
<p>请先在 <code>web</code> 目录运行 <code>npm install &amp;&amp; npm run build</code>，
或使用已经打包好的 RewardsPilot.exe。</p>
<p>后端服务已经启动。构建完成后刷新本页即可。</p>
</div></body></html>"""


def _find_edge() -> Path | None:
    candidates: list[Path] = []
    for env_name in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        base = os.environ.get(env_name)
        if base:
            candidates.append(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    found = shutil.which("msedge")
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def launch_ui_window(url: str, state_dir: Path) -> subprocess.Popen | None:
    edge = _find_edge()
    if edge is None:
        webbrowser.open(url)
        return None
    profile = state_dir / "ui-profile"
    profile.mkdir(parents=True, exist_ok=True)
    args = [
        str(edge),
        f"--app={url}",
        f"--user-data-dir={profile}",
        "--window-size=1460,980",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-mode",
        "--disable-features=Translate",
    ]
    try:
        return subprocess.Popen(args, close_fds=True)
    except Exception:
        webbrowser.open(url)
        return None


def _ui_window_handles(marker: str = "Rewards Pilot") -> set[int]:
    """返回标题包含 marker 的可见窗口句柄。

    Edge 的 --app 窗口会先经历进程交接，不能只靠启动时的子进程判断关闭，
    因此这里直接按窗口标题跟踪。
    """
    if os.name != "nt":
        return set()
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    handles: set[int] = set()
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [enum_proc, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL

    def callback(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                if marker.lower() in buffer.value.lower():
                    handles.add(int(hwnd))
        return True

    user32.EnumWindows(enum_proc(callback), 0)
    return handles


def _window_visible(hwnd: int) -> bool:
    if os.name != "nt":
        return True
    try:
        return bool(ctypes.windll.user32.IsWindowVisible(hwnd))
    except Exception:
        return False


def _focus_window(hwnd: int) -> bool:
    if os.name != "nt" or not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def _close_window(hwnd: int) -> None:
    if os.name != "nt" or not hwnd:
        return
    try:
        ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
    except Exception:
        logging.getLogger("rewards_bot.gui").debug("关闭控制台窗口失败", exc_info=True)


class ConsoleWindowManager:
    """打开、聚焦并跟踪本地控制台窗口。"""

    def __init__(
        self,
        url: str,
        runtime: Runtime,
        stop_event: threading.Event,
        state_dir: Path,
        *,
        exit_on_close: bool = True,
    ) -> None:
        self.url = url
        self.runtime = runtime
        self.stop_event = stop_event
        self.state_dir = state_dir
        self.exit_on_close = exit_on_close
        self.log = logging.getLogger("rewards_bot.gui")
        self._lock = threading.Lock()
        self._opening = False
        self._handle: int | None = None
        self._handles: set[int] = set()

    def open(self) -> None:
        with self._lock:
            handles = _ui_window_handles()
            if handles:
                hwnd = min(handles)
                self._handle = hwnd
                self._handles.add(hwnd)
                self._opening = False
                focus = True
            elif self._opening:
                return
            else:
                self._opening = True
                hwnd = 0
                focus = False
        if focus:
            if _focus_window(hwnd):
                self.log.info("控制台窗口已置于前台。")
            return
        self.log.info("正在打开控制台窗口…")
        threading.Thread(
            target=self._open_async,
            name="rewards-gui-launcher",
            daemon=True,
        ).start()

    def _open_async(self) -> None:
        started = False
        try:
            started = _open_when_ready(
                self.url,
                self.runtime,
                self.stop_event,
                self.state_dir,
                exit_on_close=self.exit_on_close,
                manager=self,
            )
        except Exception:
            self.log.exception("打开控制台窗口失败")
        if not started:
            self.mark_launch_failed()

    def mark_opened(self, hwnd: int) -> None:
        with self._lock:
            self._handle = hwnd
            self._handles.add(hwnd)
            self._opening = False

    def mark_launch_failed(self) -> None:
        with self._lock:
            self._opening = False

    def mark_closed(self, hwnd: int) -> None:
        with self._lock:
            self._handles.discard(hwnd)
            if self._handle == hwnd:
                self._handle = None

    def close_all(self) -> None:
        """只关闭本实例打开或聚焦过的控制台窗口，不碰其他浏览器窗口。"""

        with self._lock:
            tracked = set(self._handles)
            self._handles.clear()
            self._handle = None
        for hwnd in _ui_window_handles() & tracked:
            _close_window(hwnd)


def _watch_ui(
    runtime: Runtime,
    stop_event: threading.Event,
    windows_before: set[int],
    *,
    exit_on_close: bool = True,
    manager: ConsoleWindowManager | None = None,
) -> None:
    log = logging.getLogger("rewards_bot.gui")
    deadline = time.monotonic() + 45
    hwnd: int | None = None
    while time.monotonic() < deadline and not stop_event.is_set():
        new_handles = _ui_window_handles() - windows_before
        if new_handles:
            hwnd = min(new_handles)
            break
        time.sleep(0.5)
    if hwnd is None:
        if manager is not None:
            manager.mark_launch_failed()
        log.warning("未能跟踪到 UI 窗口，后端继续运行；可在界面或托盘退出。")
        return
    if manager is not None:
        manager.mark_opened(hwnd)
    try:
        from rewards_bot.window_branding import brand_app_window

        brand_app_window(hwnd)
    except Exception as exc:
        log.debug("设置应用窗口图标失败：%s", exc)
    if not _focus_window(hwnd):
        log.debug("控制台窗口已打开，但未能置于前台。")
    if exit_on_close:
        log.info("UI 窗口已就绪，关闭窗口将结束后端。")
    else:
        log.info("UI 窗口已就绪，关闭后可单击托盘图标重新打开。")
    while not stop_event.is_set():
        if not _window_visible(hwnd):
            break
        time.sleep(0.75)
    if manager is not None:
        manager.mark_closed(hwnd)
    if stop_event.is_set():
        return
    if not exit_on_close:
        log.info("UI 窗口已关闭，程序继续驻留系统托盘。")
        return
    log.info("UI 窗口已关闭，准备退出应用。")
    deadline = time.monotonic() + 15 * 60
    while runtime.job.running and time.monotonic() < deadline:
        time.sleep(1.0)
    runtime.shutdown()
    stop_event.set()


def _open_when_ready(
    url: str,
    runtime: Runtime,
    stop_event: threading.Event,
    state_dir: Path,
    *,
    exit_on_close: bool = True,
    manager: ConsoleWindowManager | None = None,
) -> bool:
    log = logging.getLogger("rewards_bot.gui")
    for _ in range(100):
        if stop_event.is_set():
            return False
        try:
            with urlopen(url + "/api/health", timeout=1) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if response.status == 200:
                    if payload.get("app") == APP_NAME:
                        break
                    log.warning("端口健康检查返回了其他服务，未打开窗口：%s", payload)
                    return False
        except Exception:
            pass
        time.sleep(0.25)
    else:
        log.warning("等待本地服务就绪超时，未打开应用窗口。")
        return False
    windows_before = _ui_window_handles()
    launch_ui_window(url, state_dir)
    threading.Thread(
        target=_watch_ui,
        args=(runtime, stop_event, windows_before),
        kwargs={"exit_on_close": exit_on_close, "manager": manager},
        name="rewards-gui-window-watch",
        daemon=True,
    ).start()
    return True


def _auto_exit_after_schedule(
    runtime: Runtime,
    log: logging.Logger,
    request_shutdown: Callable[[str], tuple[bool, str]],
    tray_ref: list[TrayController],
    *,
    trigger: str,
    ok: bool,
    message: str,
    settle_seconds: float = 2.0,
) -> bool:
    """定时任务结束后，按设置优雅地退出整个后台进程。

    只在 trigger=schedule 时生效；手动运行不会让程序退出。
    """

    if trigger != "schedule":
        return False
    try:
        cfg = runtime.store.load()
    except Exception:
        log.exception("读取配置失败，跳过每日自动退出。")
        return False
    if not cfg.general.auto_exit_after_run:
        return False

    if not ok:
        # 失败时保留托盘和后台，方便重新登录或手动重跑；成功跑完才退出。
        log.info(
            "每日定时任务有错误，保留后台便于排查；成功完成后才会按设置自动退出。"
        )
        if tray_ref:
            try:
                tray_ref[0].notify(
                    "每日任务有错误，已保留后台；请打开控制台查看日志。"
                )
            except Exception:
                log.debug("发送任务失败托盘提示失败", exc_info=True)
        return False

    log.info(
        "每日定时任务已成功结束，auto_exit_after_run 已开启，准备退出后台进程。"
    )
    deadline = time.monotonic() + 90
    while runtime.job.running and time.monotonic() < deadline:
        time.sleep(0.5)
    if runtime.job.running:
        log.warning("任务线程未在 90 秒内结束，取消本次自动退出。")
        return False
    if settle_seconds > 0:
        time.sleep(settle_seconds)

    if tray_ref:
        try:
            tray_ref[0].notify(
                "每日任务已结束，Rewards Pilot 即将退出；下次开机将自动启动。"
            )
        except Exception:
            log.debug("发送自动退出托盘提示失败", exc_info=True)

    exit_message = "自动退出尚未执行。"
    for _ in range(3):
        exit_ok, exit_message = request_shutdown(
            "每日定时任务已结束，按设置自动退出。"
        )
        if exit_ok:
            log.info("自动退出已请求：%s", exit_message)
            return True
        time.sleep(1.0)
    log.warning("自动退出未成功：%s", exit_message)
    return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description="Microsoft Rewards 每日任务自动化 · 本地可视化控制台",
    )
    parser.add_argument("-c", "--config", help="配置文件路径（默认：程序目录下的 config.toml）")
    parser.add_argument("--port", type=int, default=8765, help="本地 UI 端口，默认 8765；占用时自动顺延")
    parser.add_argument("--no-browser", action="store_true", help="只启动后端，不打开应用窗口")
    parser.add_argument("--no-tray", action="store_true", help="不创建系统托盘图标")
    parser.add_argument("--no-scheduler", action="store_true", help="启动时不自动开启每日调度")
    parser.add_argument(
        "--autostart",
        action="store_true",
        help="由 Windows 开机启动调用：驻留托盘，不主动打开控制台窗口",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config_path = (
        Path(args.config).expanduser().resolve()
        if args.config
        else (PROJECT_ROOT / "config.toml").resolve()
    )
    example_path = RESOURCE_ROOT / "config.example.toml"
    store = SettingsStore(config_path, example_path)
    try:
        store.ensure()
        _ensure_queries_file()
        cfg = store.load()
        setup_logging(cfg.general.log_dir)
    except Exception as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        return 1

    runtime = Runtime(store, autostart_scheduler=False)
    logger = logging.getLogger("rewards_bot")
    logger.addHandler(runtime.log_buffer)
    log = logging.getLogger("rewards_bot.gui")

    try:
        first_run = bool(runtime.onboarding.snapshot().get("show"))
    except Exception:
        log.exception("读取初始化教程状态失败，将暂缓自动调度。")
        first_run = True

    token = secrets.token_urlsafe(24)
    app = create_app(runtime, token)
    stop_event: threading.Event = app.extensions["stop_event"]
    tray_ref: list[TrayController] = []

    # 配置是唯一事实来源：开启时补登记/修复路径，关闭时清理旧启动项。
    try:
        startup_ok, startup_message = runtime.autostart.sync(
            cfg.general.auto_exit_after_run
        )
        if startup_ok:
            if cfg.general.auto_exit_after_run:
                log.info("自动退出已开启，%s", startup_message)
        else:
            log.warning("同步开机启动状态失败：%s", startup_message)
    except Exception:
        log.exception("同步开机启动状态失败")

    if args.autostart:
        log.info("以开机自启模式启动：驻留系统托盘，不主动打开控制台窗口。")

    requester = app.extensions.get("request_shutdown")
    if requester is not None:

        def on_job_finished(trigger: str, job_ok: bool, job_message: str) -> None:
            if trigger != "schedule":
                return
            threading.Thread(
                target=_auto_exit_after_schedule,
                args=(runtime, log, requester, tray_ref),
                kwargs={"trigger": trigger, "ok": job_ok, "message": job_message},
                name="rewards-auto-exit",
                daemon=True,
            ).start()

        runtime.job.add_finished_listener(on_job_finished)

    if not args.no_scheduler:
        if first_run:
            log.info(
                "首次运行：初始化教程完成前暂缓自动开启每日调度，"
                "避免用户尚未确认时自动运行任务。"
            )
        else:
            ok, message = runtime.scheduler.start()
            if not ok:
                log.warning("自动启动调度失败：%s", message)

    port = find_free_port(args.port)
    url = f"http://127.0.0.1:{port}"
    try:
        server = create_server(app, host="127.0.0.1", port=port, threads=10)
    except Exception:
        log.exception("本地服务启动失败")
        runtime.shutdown()
        return 1

    server_thread = threading.Thread(target=server.run, name="rewards-gui-http", daemon=True)
    server_thread.start()
    log.info(
        "%s v%s 已启动：%s | 配置：%s | 调度：%s",
        APP_NAME,
        VERSION,
        url,
        config_path,
        "开启" if runtime.scheduler.running else "关闭",
    )

    tray: TrayController | None = None
    tray_started = False
    console_ref: list[ConsoleWindowManager] = []

    def open_logs() -> None:
        current = runtime.store.load()
        log_dir = current.general.log_dir
        log_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(log_dir)

    def open_console() -> None:
        if stop_event.is_set() or not console_ref:
            return
        console_ref[0].open()

    def request_exit() -> tuple[bool, str]:
        requester = app.extensions.get("request_shutdown")
        if requester is None:
            return False, "退出入口尚未就绪。"
        return requester("托盘请求退出应用。")

    if not args.no_tray:
        if os.name != "nt":
            log.info("当前系统不支持 Windows 系统托盘，已跳过。")
        else:
            try:
                tray_actions = TrayActions(
                    runtime,
                    open_console=open_console,
                    request_exit=request_exit,
                    open_logs=open_logs,
                )
                candidate = TrayController(tray_actions)
                tray_started = candidate.start()
                if tray_started:
                    tray = candidate
                    tray_ref.append(candidate)
                else:
                    log.warning("系统托盘不可用，关闭窗口仍会结束程序。")
            except Exception:
                log.exception("系统托盘初始化失败，关闭窗口仍会结束程序。")

    console = ConsoleWindowManager(
        url,
        runtime,
        stop_event,
        cfg.general.state_dir,
        exit_on_close=not tray_started,
    )
    console_ref.append(console)
    if not args.no_browser and not args.autostart:
        console.open()
    elif args.autostart and not args.no_browser and not tray_started:
        # 开机自启且托盘不可用时，必须留一个能操作界面的入口，避免成为纯后台幽灵进程。
        log.warning("开机自启时系统托盘不可用，改为打开控制台窗口。")
        console.open()

    try:
        while not stop_event.wait(1.0):
            if not server_thread.is_alive():
                log.error("本地 HTTP 服务已停止。")
                break
    except KeyboardInterrupt:
        log.info("收到 Ctrl+C，正在退出。")
    finally:
        tray_ref.clear()
        if tray is not None:
            tray.stop()
        try:
            console.close_all()
        except Exception:
            log.debug("关闭控制台窗口失败", exc_info=True)
        runtime.shutdown()
        try:
            server.close()
        except Exception:
            pass
        time.sleep(0.3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
