from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from rewards_bot.config import AppConfig, ConfigError
from rewards_bot.scheduler import DailyScheduler

from .autostart import AutostartManager
from .log_buffer import LogBuffer
from .onboarding import OnboardingStore
from .power_mode import LowPowerService
from .settings_store import SettingsStore


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class JobManager:
    """同一时间只允许一个自动化任务，供界面和调度器共用。"""

    def __init__(
        self,
        store: SettingsStore,
        is_login_active: Callable[[], bool],
        low_power: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.store = store
        self.is_login_active = is_login_active
        self.low_power = low_power
        self.log = logging.getLogger("rewards_bot.gui.job")
        self._lock = threading.Lock()
        self._listeners_lock = threading.Lock()
        self._finished_listeners: list[Callable[[str, bool, str], None]] = []
        self._thread: threading.Thread | None = None
        self._status: dict[str, Any] = {
            "running": False,
            "state": "idle",
            "mode": None,
            "trigger": None,
            "started_at": None,
            "finished_at": None,
            "ok": None,
            "message": "等待运行",
        }

    @property
    def running(self) -> bool:
        with self._lock:
            return bool(self._thread and self._thread.is_alive())

    def add_finished_listener(
        self,
        listener: Callable[[str, bool, str], None],
    ) -> None:
        """任务线程收尾后回调 (trigger, ok, message)。回调异常不会影响任务状态。"""

        with self._listeners_lock:
            self._finished_listeners.append(listener)

    def _notify_finished(self, trigger: str, ok: bool, message: str) -> None:
        with self._listeners_lock:
            listeners = list(self._finished_listeners)
        for listener in listeners:
            try:
                listener(trigger, ok, message)
            except Exception:
                self.log.exception("任务完成监听器执行失败")

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            data = dict(self._status)
            data["running"] = bool(self._thread and self._thread.is_alive())
            return data

    def start(self, mode: str | None = None, trigger: str = "manual") -> tuple[bool, str]:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False, "已有任务正在运行，请等待结束。"
        # 跨服务检查放在私有锁之外，避免和 LoginService 的锁互相等待。
        if self.is_login_active():
            return False, "登录窗口正在使用浏览器，请先完成或取消登录。"

        with self._lock:
            if self._thread and self._thread.is_alive():
                return False, "已有任务正在运行，请等待结束。"
            try:
                cfg = self.store.load()
            except Exception as exc:
                self._status = {
                    **self._status,
                    "running": False,
                    "state": "error",
                    "ok": False,
                    "finished_at": now_iso(),
                    "message": f"配置读取失败：{exc}",
                }
                return False, f"配置读取失败：{exc}"

            chosen = (mode or cfg.general.mode).strip().lower()
            if chosen not in {"basic", "advanced"}:
                return False, f"未知模式：{chosen}"
            power_state: dict[str, Any] = {}
            try:
                if self.low_power is not None:
                    power_state = self.low_power()
            except Exception:
                self.log.debug("读取低功耗状态失败，继续按配置运行。", exc_info=True)
            if power_state.get("enabled") and not cfg.general.headless:
                # 低功耗模式下不弹出浏览器窗口，减少 GPU/合成器与屏幕唤醒。
                cfg.general.headless = True
                self.log.info("低功耗挂机中：本次任务使用无头 Edge，不打开浏览器窗口。")
            if chosen == "advanced" and not cfg.advanced.api_key:
                message = "进阶模式缺少 DeepSeek API Key，请先在设置中填写。"
                self._status = {
                    **self._status,
                    "running": False,
                    "state": "error",
                    "mode": chosen,
                    "trigger": trigger,
                    "ok": False,
                    "finished_at": now_iso(),
                    "message": message,
                }
                return False, message

            self._status = {
                "running": True,
                "state": "running",
                "mode": chosen,
                "trigger": trigger,
                "started_at": now_iso(),
                "finished_at": None,
                "ok": None,
                "message": "任务运行中，浏览器窗口会自动打开。",
            }
            self._thread = threading.Thread(
                target=self._run,
                args=(cfg, chosen, trigger),
                name="rewards-gui-job",
                daemon=True,
            )
            thread = self._thread

        self.log.info("启动任务：mode=%s trigger=%s", chosen, trigger)
        thread.start()
        return True, "任务已开始。"

    def _run(self, cfg: AppConfig, mode: str, trigger: str) -> None:
        ok = False
        message = "任务结束"
        try:
            from rewards_bot.runner import run_once

            ok = bool(run_once(cfg, mode=mode))
            message = "运行完成，详情见实时日志。" if ok else "运行结束，但存在错误或未完成项。"
        except Exception as exc:
            self.log.exception("任务运行异常")
            message = f"运行异常：{str(exc)[:300]}"
        finally:
            with self._lock:
                self._status = {
                    **self._status,
                    "running": False,
                    "state": "success" if ok else "error",
                    "ok": ok,
                    "finished_at": now_iso(),
                    "message": message,
                }
            self.log.info("任务结束：%s", message)
            self._notify_finished(trigger, ok, message)


class LoginService:
    """在独立线程中打开登录浏览器，避免 Playwright 跨线程使用。"""

    def __init__(
        self,
        store: SettingsStore,
        is_job_running: Callable[[], bool],
    ) -> None:
        self.store = store
        self.is_job_running = is_job_running
        self.log = logging.getLogger("rewards_bot.gui.login")
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._finish = threading.Event()
        self._cancel = threading.Event()
        self._state: dict[str, Any] = {
            "state": "idle",
            "message": "尚未打开登录窗口",
            "started_at": None,
            "finished_at": None,
        }

    @property
    def active(self) -> bool:
        with self._lock:
            return bool(
                self._thread
                and self._thread.is_alive()
                and self._state.get("state") in {"opening", "waiting", "checking", "canceling"}
            )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            data = dict(self._state)
            data["active"] = bool(
                self._thread
                and self._thread.is_alive()
                and self._state.get("state") in {"opening", "waiting", "checking", "canceling"}
            )
            return data

    def _set(self, state: str, message: str, **extra: Any) -> None:
        with self._lock:
            self._state = {**self._state, "state": state, "message": message, **extra}

    def start(self) -> tuple[bool, str]:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False, "登录窗口已经打开。"
            if self.is_job_running():
                return False, "任务正在运行，请等待结束后再登录。"
            try:
                cfg = self.store.load()
            except Exception as exc:
                return False, f"配置读取失败：{exc}"
            self._finish.clear()
            self._cancel.clear()
            self._state = {
                "state": "opening",
                "message": "正在打开登录浏览器…",
                "started_at": now_iso(),
                "finished_at": None,
            }
            self._thread = threading.Thread(
                target=self._run,
                args=(cfg,),
                name="rewards-gui-login",
                daemon=True,
            )
            thread = self._thread
        thread.start()
        return True, "登录浏览器正在打开。"

    def _run(self, cfg: AppConfig) -> None:
        from rewards_bot.browser import BrowserSession, LoginRequired

        try:
            with BrowserSession(cfg, headless=False) as session:
                session.goto(cfg.general.url)
                self._set(
                    "waiting",
                    "请在弹出的 Edge 窗口完成 Microsoft 登录，然后点击“检查登录状态”。",
                )
                deadline = time.monotonic() + 600
                while time.monotonic() < deadline:
                    if self._cancel.is_set():
                        self._set("canceled", "已取消登录。", finished_at=now_iso())
                        return

                    try:
                        pages = session.context.pages if session.context else []
                    except Exception:
                        pages = []
                    if not pages:
                        self._set(
                            "error",
                            "登录窗口已被关闭。请重新点击登录。",
                            finished_at=now_iso(),
                        )
                        return

                    if self._finish.is_set():
                        self._finish.clear()
                        self._set("checking", "正在检查登录状态…")
                        try:
                            session.open_dashboard()
                        except LoginRequired:
                            self._set(
                                "waiting",
                                "还没有检测到完整登录，请完成登录（含验证码/双重验证）后重试。",
                            )
                            continue
                        except Exception as exc:
                            self.log.warning("登录检查失败：%s", exc)
                            self._set(
                                "error",
                                f"检查登录状态失败：{str(exc)[:240]}",
                                finished_at=now_iso(),
                            )
                            return
                        try:
                            session.screenshot("login-success")
                        except Exception:
                            pass
                        self._set(
                            "success",
                            "登录态已保存，可以开始运行任务。",
                            finished_at=now_iso(),
                        )
                        self.log.info("Microsoft 登录成功，登录态已保存。")
                        return

                    time.sleep(0.35)
                self._set("error", "登录窗口等待超时，请重新点击登录。", finished_at=now_iso())
        except Exception as exc:
            self.log.exception("打开登录窗口失败")
            self._set(
                "error",
                f"打开登录窗口失败：{str(exc)[:300]}",
                finished_at=now_iso(),
            )

    def finish(self) -> tuple[bool, str]:
        with self._lock:
            if not self.active:
                return False, "当前没有打开的登录窗口。"
            self._set("checking", "正在检查登录状态…")
            self._finish.set()
        return True, "正在检查登录状态。"

    def cancel(self) -> None:
        with self._lock:
            if not self.active:
                return
            self._set("canceling", "正在关闭登录窗口…")
            self._cancel.set()


class SchedulerService:
    def __init__(self, store: SettingsStore, job: JobManager) -> None:
        self.store = store
        self.job = job
        self.log = logging.getLogger("rewards_bot.gui.scheduler")
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._scheduler: DailyScheduler | None = None
        self._stop = threading.Event()
        self._running = False

    @property
    def running(self) -> bool:
        with self._lock:
            return bool(self._thread and self._thread.is_alive())

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            scheduler = self._scheduler
            next_run = scheduler.next_run_at if scheduler else None
            return {
                "running": self.running,
                "next_run": next_run.isoformat(timespec="seconds") if next_run else None,
                "run_at": scheduler.cfg.run_at if scheduler else None,
                "timezone": scheduler.cfg.timezone if scheduler else None,
            }

    def start(self, catch_up: bool | None = None) -> tuple[bool, str]:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False, "调度器已经在运行。"
            try:
                cfg = self.store.load()
            except Exception as exc:
                return False, f"配置读取失败：{exc}"
            general = cfg.general
            if catch_up is not None:
                from dataclasses import replace

                general = replace(general, catch_up=catch_up)
            scheduler = DailyScheduler(general)
            self._scheduler = scheduler
            self._stop = threading.Event()
            stop = self._stop
            mode = cfg.general.mode

            def job_callback() -> bool:
                ok, message = self.job.start(mode=mode, trigger="schedule")
                if not ok:
                    self.log.warning("定时任务未能启动：%s", message)
                return ok

            self._thread = threading.Thread(
                target=self._loop,
                args=(scheduler, job_callback, stop),
                name="rewards-gui-scheduler",
                daemon=True,
            )
            thread = self._thread
            self._running = True
        thread.start()
        self.log.info("每日调度已启动：%s（%s）", cfg.general.run_at, cfg.general.timezone)
        return True, "每日调度已启动。"

    def _loop(
        self,
        scheduler: DailyScheduler,
        job_callback: Callable[[], bool],
        stop: threading.Event,
    ) -> None:
        try:
            scheduler.run(job_callback, stop_event=stop)
        except Exception:
            self.log.exception("调度器异常退出")
        finally:
            with self._lock:
                self._running = False
                if self._thread is threading.current_thread():
                    self._thread = None

    def stop(self) -> tuple[bool, str]:
        with self._lock:
            thread = self._thread
            if not thread or not thread.is_alive():
                return False, "调度器当前未运行。"
            self._stop.set()
        thread.join(timeout=8)
        self.log.info("每日调度已停止。")
        return True, "每日调度已停止。"

    def restart(self) -> None:
        was_running = self.running
        if was_running:
            self.stop()
        if was_running:
            self.start(catch_up=False)


class Runtime:
    def __init__(
        self,
        store: SettingsStore,
        autostart_scheduler: bool = True,
    ) -> None:
        self.store = store
        self.log_buffer = LogBuffer()
        self.autostart = AutostartManager(store.config_path)
        self.job = JobManager(
            store,
            is_login_active=lambda: self.login.active,
            low_power=lambda: self.power.snapshot(),
        )
        self.login = LoginService(store, is_job_running=lambda: self.job.running)
        self.scheduler = SchedulerService(store, self.job)
        self.power = LowPowerService(
            state_dir=lambda: self.store.load().general.state_dir,
            is_busy=lambda: self.job.running or self.login.active,
        )
        self.onboarding = OnboardingStore(
            state_dir=lambda: self.store.load().general.state_dir,
        )
        self.scheduler_error: str | None = None
        try:
            self.power.recover_stale_session()
        except Exception:
            logging.getLogger("rewards_bot.gui").exception("恢复低功耗残留状态失败")
        if autostart_scheduler:
            try:
                self.scheduler.start()
            except Exception as exc:
                self.scheduler_error = str(exc)
                logging.getLogger("rewards_bot.gui").exception("自动启动调度失败")

    def shutdown(self) -> None:
        try:
            self.scheduler.stop()
        except Exception:
            pass
        try:
            self.login.cancel()
        except Exception:
            pass
        try:
            self.power.shutdown()
        except Exception:
            pass
