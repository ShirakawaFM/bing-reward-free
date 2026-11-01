from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from rewards_bot.paths import PROJECT_ROOT

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Rewards Pilot"


class AutostartError(RuntimeError):
    """读写 Windows 开机启动项失败。"""


def startup_command(
    config_path: Path,
    *,
    frozen: bool | None = None,
    executable: Path | None = None,
    project_root: Path | None = None,
) -> str:
    """生成登录时启动本程序的命令。

    冻结后的 EXE 直接带参数启动；源码运行优先使用 pythonw，避免弹出控制台。
    """

    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    exe = Path(executable or sys.executable).expanduser().resolve()
    root = Path(project_root or PROJECT_ROOT).expanduser().resolve()
    if is_frozen:
        parts = [str(exe)]
    else:
        python = exe
        pythonw = exe.with_name("pythonw.exe")
        if pythonw.exists():
            python = pythonw
        parts = [str(python), str(root / "desktop.py")]
    parts.extend(
        [
            "--autostart",
            "--config",
            str(Path(config_path).expanduser().resolve()),
        ]
    )
    return subprocess.list2cmdline(parts)


def read_registered(name: str = VALUE_NAME) -> str | None:
    if os.name != "nt":
        return None
    try:
        import winreg
    except ImportError as exc:  # pragma: no cover - 仅非 Windows 理论路径
        raise AutostartError("当前 Python 缺少 winreg，无法管理开机启动。") from exc
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY,
            0,
            winreg.KEY_QUERY_VALUE,
        ) as key:
            value, _kind = winreg.QueryValueEx(key, name)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise AutostartError(f"读取开机启动项失败：{exc}") from exc
    text = str(value).strip()
    return text or None


def write_registered(command: str, name: str = VALUE_NAME) -> None:
    if os.name != "nt":
        raise AutostartError("开机启动只支持 Windows。")
    command = command.strip()
    if not command:
        raise AutostartError("开机启动命令为空。")
    try:
        import winreg

        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, command)
    except AutostartError:
        raise
    except Exception as exc:
        raise AutostartError(f"写入开机启动项失败：{exc}") from exc


def remove_registered(name: str = VALUE_NAME) -> None:
    if os.name != "nt":
        return
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, name)
    except FileNotFoundError:
        return
    except Exception as exc:
        raise AutostartError(f"移除开机启动项失败：{exc}") from exc


class AutostartManager:
    """把“每日跑完退出”与当前用户的开机启动项保持同步。"""

    def __init__(self, config_path: Path) -> None:
        self.config_path = Path(config_path)
        self.log = logging.getLogger("rewards_bot.gui.autostart")

    @property
    def supported(self) -> bool:
        return os.name == "nt"

    def command(self) -> str:
        return startup_command(self.config_path)

    def snapshot(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "supported": self.supported,
            "registered": False,
            "matches": False,
            "error": None,
        }
        if not self.supported:
            return data
        try:
            current = read_registered()
            expected = self.command()
        except Exception as exc:
            data["error"] = str(exc)[:300]
            return data
        data["registered"] = bool(current)
        data["matches"] = bool(current and current == expected)
        return data

    def sync(self, enabled: bool) -> tuple[bool, str]:
        """登记或移除开机启动。返回 (是否成功, 面向界面的提示)。"""

        if not self.supported:
            if enabled:
                return False, "开机启动只支持 Windows。"
            return True, "当前系统无需开机启动。"
        if enabled:
            try:
                command = self.command()
                if read_registered() == command:
                    return True, "开机启动已登记。"
                write_registered(command)
            except Exception as exc:
                self.log.exception("登记开机启动失败")
                return False, f"登记开机启动失败：{str(exc)[:240]}"
            self.log.info("已登记 Windows 开机启动：%s", command)
            return True, "已登记开机启动。"
        try:
            if read_registered() is None:
                return True, "开机启动未登记。"
            remove_registered()
        except Exception as exc:
            self.log.exception("移除开机启动失败")
            return False, f"移除开机启动失败：{str(exc)[:240]}"
        self.log.info("已移除 Windows 开机启动项。")
        return True, "已移除开机启动。"
