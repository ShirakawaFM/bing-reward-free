from __future__ import annotations

import ctypes
import sys
import traceback
from datetime import datetime
from pathlib import Path

from rewards_bot.paths import PROJECT_ROOT
from rewards_bot.single_instance import acquire_single_instance, focus_existing_window


def _write_crash_log(text: str) -> Path:
    log_dir = PROJECT_ROOT / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / "gui-crash.log"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n===== {datetime.now().isoformat(timespec='seconds')} =====\n")
            handle.write(text)
            handle.write("\n")
        return path
    except Exception:
        return log_dir / "gui-crash.log"


def _show_error(message: str, log_path: Path) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(
            0,
            f"{message}\n\n详细日志：{log_path}",
            "Rewards Pilot 启动失败",
            0x10,
        )
    except Exception:
        pass


def _show_notice(message: str) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(
            0,
            message,
            "Rewards Pilot",
            0x40,
        )
    except Exception:
        pass


def main() -> int:
    if not acquire_single_instance():
        focus_existing_window()
        _show_notice(
            "Rewards Pilot 已经在运行。\n\n"
            "为保持低功耗与单一调度，本次启动已取消。"
            "请回到已打开的应用窗口；如果窗口已关闭到托盘，"
            "请单击通知区域的 Rewards Pilot 图标重新打开。"
        )
        return 0
    try:
        from gui.server import main as gui_main

        return gui_main()
    except SystemExit:
        raise
    except Exception:
        detail = traceback.format_exc()
        path = _write_crash_log(detail)
        _show_error("程序启动时遇到错误，请查看崩溃日志。", path)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
