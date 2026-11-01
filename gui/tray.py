from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

from rewards_bot.paths import RESOURCE_ROOT

LOG = logging.getLogger("rewards_bot.gui.tray")

APP_TITLE = "Rewards Pilot"
TRAY_NAME = "rewards-pilot"


def tray_icon_path() -> Path:
    """托盘优先使用程序图标，缺失时退回任务浏览器图标。"""

    for name in ("app.ico", "task-browser.ico"):
        path = RESOURCE_ROOT / "assets" / name
        if path.is_file():
            return path
    return RESOURCE_ROOT / "assets" / "app.ico"


def scheduler_label(running: bool) -> str:
    return f"每日调度：{'已开启' if running else '已关闭'}"


def low_power_label(enabled: bool) -> str:
    return f"低功耗挂机：{'已开启' if enabled else '已关闭'}"


def confirm_run_dialog(title: str, message: str) -> bool:
    """运行前的原生确认框，默认按钮为“否”，避免误触启动真实任务。"""

    if os.name != "nt":
        return True
    try:
        import ctypes

        MB_YESNO = 0x00000004
        MB_ICONWARNING = 0x00000030
        MB_DEFBUTTON2 = 0x00000100
        MB_TOPMOST = 0x00040000
        MB_SETFOREGROUND = 0x00010000
        result = ctypes.windll.user32.MessageBoxW(
            None,
            message,
            title,
            MB_YESNO
            | MB_ICONWARNING
            | MB_DEFBUTTON2
            | MB_TOPMOST
            | MB_SETFOREGROUND,
        )
        return int(result) == 6  # IDYES
    except Exception:
        LOG.exception("显示运行确认框失败")
        return False


def tray_status(runtime: Any) -> str:
    """托盘悬停提示。只显示本程序状态，不包含账号信息。"""

    try:
        if runtime.job.running:
            return "Rewards Pilot · 任务运行中"
        if runtime.power.enabled:
            return "Rewards Pilot · 低功耗挂机"
        if runtime.scheduler.running:
            return "Rewards Pilot · 调度已开启"
    except Exception:
        LOG.debug("读取托盘状态失败", exc_info=True)
    return "Rewards Pilot · 空闲"


class TrayActions:
    """托盘的同步动作集合，不依赖 pystray，方便单元测试。"""

    def __init__(
        self,
        runtime: Any,
        *,
        open_console: Callable[[], None],
        request_exit: Callable[[], tuple[bool, str]],
        open_logs: Callable[[], None],
        confirm_run: Callable[[str, str], bool] = confirm_run_dialog,
    ) -> None:
        self.runtime = runtime
        self.open_console = open_console
        self.request_exit = request_exit
        self.open_logs = open_logs
        self.confirm_run = confirm_run

    def run_now(self) -> tuple[bool, str]:
        if self.runtime.job.running:
            return False, "已有任务正在运行，请等待结束。"
        if self.runtime.login.active:
            return False, "登录窗口正在使用浏览器，请先完成或取消登录。"
        if not self.confirm_run(
            "Rewards Pilot · 立即运行",
            "即将使用当前配置打开任务浏览器，并执行一次真实任务，"
            "期间可能自动领取可领取的奖励。\n\n确定现在运行吗？",
        ):
            return False, "已取消本次运行。"
        return self.runtime.job.start(trigger="tray")

    def toggle_scheduler(self) -> tuple[bool, str]:
        if self.runtime.scheduler.running:
            ok, message = self.runtime.scheduler.stop()
            if not ok:
                return False, message
            return True, "每日调度已暂停。"
        # 从托盘开启调度时不补跑今天的任务，避免一次点击立刻启动真实运行。
        ok, message = self.runtime.scheduler.start(catch_up=False)
        if not ok:
            return False, message
        return True, "每日调度已开启，将从下一个计划时间开始。"

    def toggle_low_power(self) -> tuple[bool, str]:
        enabled = bool(self.runtime.power.enabled)
        if enabled:
            self.runtime.power.deactivate()
            return True, "低功耗挂机已关闭，正在恢复原电源计划。"
        self.runtime.power.activate()
        return True, "低功耗挂机已开启。"

    def quit(self) -> tuple[bool, str]:
        return self.request_exit()


class TrayController:
    """Windows 系统托盘。pystray 只在启动时导入，缺少依赖时由调用方回退。"""

    def __init__(self, actions: TrayActions, *, icon_path: Path | None = None) -> None:
        self.actions = actions
        self.icon_path = icon_path or tray_icon_path()
        self._icon: Any = None
        self._image: Any = None
        self._stop = threading.Event()
        self._refresh_thread: threading.Thread | None = None
        self._last_signature: tuple[Any, ...] | None = None

    @property
    def running(self) -> bool:
        return bool(self._icon is not None and getattr(self._icon, "visible", False))

    def _build_menu(self, pystray: Any) -> Any:
        """右键菜单：左侧点击默认项也能打开控制台。"""

        return pystray.Menu(
            pystray.MenuItem("打开控制台", self._on_open, default=True),
            pystray.MenuItem(
                "立即运行一次",
                self._on_run,
                enabled=self._run_enabled,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                self._scheduler_text,
                self._on_scheduler,
                checked=self._scheduler_checked,
            ),
            pystray.MenuItem(
                self._low_power_text,
                self._on_low_power,
                checked=self._low_power_checked,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("打开日志文件夹", self._on_logs),
            pystray.MenuItem("退出 Rewards Pilot", self._on_quit),
        )

    def start(self) -> bool:
        try:
            import pystray
            from PIL import Image
        except Exception:
            LOG.exception("系统托盘依赖不可用")
            return False

        try:
            with Image.open(self.icon_path) as source:
                self._image = source.convert("RGBA")
            menu = self._build_menu(pystray)
            self._icon = pystray.Icon(
                TRAY_NAME,
                self._image,
                tray_status(self.actions.runtime),
                menu,
            )
            self._icon.run_detached()
        except Exception:
            LOG.exception("系统托盘启动失败")
            self._icon = None
            return False

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not self._icon.visible:
            time.sleep(0.05)
        if not self._icon.visible:
            # 没有可见图标时不能启用“关闭到托盘”，否则用户将无法找回窗口。
            LOG.warning("系统托盘未在预期时间内出现，回退为关闭窗口即退出。")
            self.stop()
            return False

        self._last_signature = self._signature()
        self._refresh_thread = threading.Thread(
            target=self._watch_status,
            name="rewards-tray-status",
            daemon=True,
        )
        self._refresh_thread.start()
        LOG.info("系统托盘已就绪，右键可打开基础选项。")
        return True

    def stop(self) -> None:
        self._stop.set()
        icon = self._icon
        self._icon = None
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                LOG.debug("停止系统托盘失败", exc_info=True)

    def _signature(self) -> tuple[Any, ...]:
        runtime = self.actions.runtime
        try:
            return (
                bool(runtime.job.running),
                bool(runtime.scheduler.running),
                bool(runtime.power.enabled),
                bool(runtime.login.active),
            )
        except Exception:
            return ()

    def _watch_status(self) -> None:
        while not self._stop.wait(2.0):
            signature = self._signature()
            if signature == self._last_signature:
                continue
            self._last_signature = signature
            self._refresh()

    def _refresh(self) -> None:
        icon = self._icon
        if icon is None:
            return
        try:
            icon.update_menu()
            status = tray_status(self.actions.runtime)
            if icon.title != status:
                icon.title = status
        except Exception:
            LOG.debug("刷新托盘菜单失败", exc_info=True)

    def _notify(self, message: str) -> None:
        icon = self._icon
        if icon is None or not message:
            return
        try:
            icon.notify(message, APP_TITLE)
        except Exception:
            LOG.debug("托盘通知失败：%s", message, exc_info=True)

    # ----- 菜单文字/状态 -----

    def _scheduler_text(self, _item=None) -> str:
        return scheduler_label(bool(self.actions.runtime.scheduler.running))

    def _low_power_text(self, _item=None) -> str:
        return low_power_label(bool(self.actions.runtime.power.enabled))

    def _scheduler_checked(self, _item=None) -> bool:
        return bool(self.actions.runtime.scheduler.running)

    def _low_power_checked(self, _item=None) -> bool:
        return bool(self.actions.runtime.power.enabled)

    def _run_enabled(self, _item=None) -> bool:
        try:
            return not self.actions.runtime.job.running and not self.actions.runtime.login.active
        except Exception:
            return True

    # ----- 菜单动作 -----

    def _on_open(self, _icon=None, _item=None) -> None:
        try:
            self.actions.open_console()
        except Exception:
            LOG.exception("从托盘打开控制台失败")
            self._notify("打开控制台失败，请查看日志。")

    def _on_logs(self, _icon=None, _item=None) -> None:
        try:
            self.actions.open_logs()
        except Exception as exc:
            LOG.exception("打开日志文件夹失败")
            self._notify(f"打开日志文件夹失败：{str(exc)[:160]}")

    def _on_run(self, _icon=None, _item=None) -> None:
        self._run_async(self.actions.run_now, "立即运行")

    def _on_scheduler(self, _icon=None, _item=None) -> None:
        self._run_async(self.actions.toggle_scheduler, "切换每日调度")

    def _on_low_power(self, _icon=None, _item=None) -> None:
        self._run_async(self.actions.toggle_low_power, "切换低功耗挂机")

    def _on_quit(self, _icon=None, _item=None) -> None:
        try:
            ok, message = self.actions.quit()
        except Exception as exc:
            LOG.exception("从托盘退出失败")
            ok, message = False, f"退出失败：{str(exc)[:160]}"
        self._notify(message)
        if ok:
            threading.Timer(1.2, self.stop).start()

    def _run_async(self, action: Callable[[], tuple[bool, str]], label: str) -> None:
        def runner() -> None:
            try:
                ok, message = action()
            except Exception as exc:
                LOG.exception("托盘操作失败：%s", label)
                ok, message = False, f"{label}失败：{str(exc)[:200]}"
            self._last_signature = self._signature()
            self._refresh()
            if message:
                self._notify(message)

        threading.Thread(
            target=runner,
            name="rewards-tray-action",
            daemon=True,
        ).start()
