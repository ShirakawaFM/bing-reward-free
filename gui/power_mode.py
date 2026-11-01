from __future__ import annotations

import copy
import csv
import ctypes
import io
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

PLAN_GUID_RE = re.compile(
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)
KNOWN_PLANS = {
    "a1841308-3541-4fab-bc81-f71556f20b4a": "节能",
    "381b4222-f694-41f0-9685-ff5bb260df2e": "平衡",
    "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c": "高性能",
}
POWER_SAVER_ALIAS = "a1841308-3541-4fab-bc81-f71556f20b4a"
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001
_PROCESS_POWER_THROTTLING = 4
_POWER_THROTTLING_EXECUTION_SPEED = 0x1

# 这里只放“用户自己启动的应用”，绝不包含系统进程、Shell、浏览器或本程序。
# 关闭应用是用户主动勾选的可选动作，默认不会执行。
SAFE_BACKGROUND_APPS: dict[str, dict[str, str]] = {
    "onedrive.exe": {"label": "OneDrive", "hint": "云同步，关闭后本次同步会暂停"},
    "dropbox.exe": {"label": "Dropbox", "hint": "云同步，关闭后本次同步会暂停"},
    "teams.exe": {"label": "Microsoft Teams", "hint": "会退出会议与消息通知"},
    "ms-teams.exe": {"label": "Microsoft Teams（新版）", "hint": "会退出会议与消息通知"},
    "slack.exe": {"label": "Slack", "hint": "会退出工作区与通知"},
    "discord.exe": {"label": "Discord", "hint": "会退出语音与消息"},
    "wechat.exe": {"label": "微信", "hint": "会退出微信，未发送消息可能丢失"},
    "weixin.exe": {"label": "微信（新版）", "hint": "会退出微信，未发送消息可能丢失"},
    "qq.exe": {"label": "QQ", "hint": "会退出 QQ，未发送消息可能丢失"},
    "dingtalk.exe": {"label": "钉钉", "hint": "会退出钉钉与消息通知"},
    "spotify.exe": {"label": "Spotify", "hint": "会停止播放"},
    "steam.exe": {"label": "Steam", "hint": "会退出 Steam 客户端"},
    "steamwebhelper.exe": {"label": "Steam Web Helper", "hint": "Steam 的内置浏览器进程"},
    "epicgameslauncher.exe": {"label": "Epic Games Launcher", "hint": "会退出 Epic 客户端"},
    "baidunetdisk.exe": {"label": "百度网盘", "hint": "会暂停传输任务"},
    "thunder.exe": {"label": "迅雷", "hint": "会暂停下载任务"},
    "qbittorrent.exe": {"label": "qBittorrent", "hint": "会暂停下载任务"},
}


def _decode(payload: bytes | None) -> str:
    if not payload:
        return ""
    encodings = ["utf-8-sig", locale_encoding(), "mbcs", "gbk", "cp936", "latin-1"]
    seen: set[str] = set()
    for encoding in encodings:
        if not encoding or encoding.lower() in seen:
            continue
        seen.add(encoding.lower())
        try:
            return payload.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return payload.decode("utf-8", errors="replace")


def locale_encoding() -> str | None:
    try:
        import locale

        return locale.getpreferredencoding(False)
    except Exception:
        return None


def _run(args: list[str], timeout: float = 15.0) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
    except Exception as exc:
        return False, str(exc)
    text = (_decode(completed.stdout) + _decode(completed.stderr)).strip()
    return completed.returncode == 0, text


def _log() -> logging.Logger:
    return logging.getLogger("rewards_bot.gui.power")


def parse_active_plan_output(output: str) -> tuple[str, str] | None:
    match = PLAN_GUID_RE.search(output or "")
    if not match:
        return None
    guid = match.group(1).lower()
    tail = (output or "")[match.end() :].strip()
    name = ""
    if tail.startswith("("):
        closing = tail.rfind(")")
        if closing > 0:
            name = tail[1:closing].strip()
    if not name:
        name = KNOWN_PLANS.get(guid, "自定义电源计划")
    return guid, name


def get_active_plan() -> tuple[str, str] | None:
    ok, output = _run(["powercfg", "/getactivescheme"])
    if not ok:
        return None
    return parse_active_plan_output(output)


def set_active_plan(target: str) -> tuple[bool, str]:
    if not target:
        return False, "电源计划为空。"
    return _run(["powercfg", "/setactive", target])


def parse_tasklist_csv(text: str) -> list[dict[str, Any]]:
    processes: list[dict[str, Any]] = []
    try:
        rows = csv.reader(io.StringIO(text))
        for row in rows:
            if len(row) < 5:
                continue
            name = row[0].strip()
            pid_text = row[1].strip()
            if not name or not pid_text.isdigit():
                continue
            memory_kb = 0
            digits = re.sub(r"[^0-9]", "", row[4] or "")
            if digits:
                try:
                    memory_kb = int(digits)
                except ValueError:
                    memory_kb = 0
            processes.append(
                {
                    "exe": name,
                    "pid": int(pid_text),
                    "session": row[2].strip(),
                    "memory_mb": round(memory_kb / 1024, 1),
                }
            )
    except (csv.Error, ValueError):
        return processes
    return processes


def list_processes() -> list[dict[str, Any]]:
    if os.name != "nt":
        return []
    ok, output = _run(["tasklist", "/fo", "csv", "/nh"], timeout=25)
    if not ok:
        _log().debug("读取进程列表失败：%s", output[:300])
        return []
    return parse_tasklist_csv(output)


def detect_safe_background_apps() -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for proc in list_processes():
        exe = proc["exe"].lower()
        meta = SAFE_BACKGROUND_APPS.get(exe)
        if meta is None:
            continue
        item = groups.setdefault(
            exe,
            {
                "exe": proc["exe"],
                "label": meta["label"],
                "hint": meta["hint"],
                "count": 0,
                "memory_mb": 0.0,
                "pids": [],
            },
        )
        item["count"] += 1
        item["memory_mb"] = round(item["memory_mb"] + float(proc["memory_mb"]), 1)
        item["pids"].append(proc["pid"])
    return sorted(
        groups.values(),
        key=lambda item: (-item["memory_mb"], item["label"].lower()),
    )


def close_safe_background_apps(names: list[str]) -> list[dict[str, Any]]:
    """只关闭用户指定、且位于安全白名单中的应用。

    不调用按名称的全局 taskkill，也不接受任意 PID；系统进程、浏览器、
    Rewards Pilot 自身都不在白名单内，因此不会被误杀。
    """

    requested: list[str] = []
    for name in names:
        exe = str(name or "").strip().lower()
        if exe in SAFE_BACKGROUND_APPS and exe not in requested:
            requested.append(exe)
    if not requested:
        return []

    processes = list_processes()
    current_pid = os.getpid()
    results: list[dict[str, Any]] = []
    for exe in requested:
        meta = SAFE_BACKGROUND_APPS[exe]
        targets = [
            item
            for item in processes
            if item["exe"].lower() == exe and item["pid"] != current_pid
        ]
        killed = 0
        failures: list[str] = []
        for proc in targets:
            pid = int(proc["pid"])
            ok, output = _run(["taskkill", "/PID", str(pid), "/F"], timeout=10)
            if ok:
                killed += 1
            else:
                failures.append(f"PID {pid}：{output[:120]}")
        results.append(
            {
                "exe": meta["label"],
                "targets": len(targets),
                "closed": killed,
                "failures": failures,
            }
        )
        if targets:
            _log().info(
                "低功耗清理：%s，结束 %s/%s 个进程。",
                meta["label"],
                killed,
                len(targets),
            )
    return results


def set_process_efficiency(enabled: bool) -> dict[str, Any]:
    """让当前进程进入低优先级 / EcoQoS 效率模式。"""

    result = {"priority": False, "eco_qos": False, "detail": ""}
    if os.name != "nt":
        result["detail"] = "仅 Windows 支持"
        return result
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.SetPriorityClass.restype = wintypes.BOOL
        kernel32.SetProcessInformation.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetProcessInformation.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(0x0200, False, os.getpid())  # PROCESS_SET_INFORMATION
        if not handle:
            result["detail"] = "无法打开当前进程句柄"
            return result

        class PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
            _fields_ = [
                ("Version", ctypes.c_ulong),
                ("ControlMask", ctypes.c_ulong),
                ("StateMask", ctypes.c_ulong),
            ]

        try:
            priority = 0x40 if enabled else 0x20  # IDLE / NORMAL
            result["priority"] = bool(kernel32.SetPriorityClass(handle, priority))
            state = PROCESS_POWER_THROTTLING_STATE(
                Version=1,
                ControlMask=_POWER_THROTTLING_EXECUTION_SPEED,
                StateMask=_POWER_THROTTLING_EXECUTION_SPEED if enabled else 0,
            )
            result["eco_qos"] = bool(
                kernel32.SetProcessInformation(
                    handle,
                    _PROCESS_POWER_THROTTLING,
                    ctypes.byref(state),
                    ctypes.sizeof(state),
                )
            )
            if not result["eco_qos"]:
                result["detail"] = "系统不支持 EcoQoS，已尽量降低优先级"
        finally:
            kernel32.CloseHandle(handle)
    except Exception as exc:
        result["detail"] = f"进程节能设置失败：{str(exc)[:160]}"
    return result


class _AwakeKeeper:
    """在独立线程中阻止系统空闲休眠，但允许显示器关闭。"""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self.ok = False

    def start(self) -> bool:
        if os.name != "nt":
            return False
        if self._thread and self._thread.is_alive():
            self.ok = True
            return True
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._loop,
            name="rewards-power-awake",
            daemon=True,
        )
        self._thread.start()
        self._ready.wait(timeout=2.0)
        return self.ok

    def _loop(self) -> None:
        kernel32 = ctypes.windll.kernel32
        kernel32.SetThreadExecutionState.argtypes = [wintypes.DWORD]
        kernel32.SetThreadExecutionState.restype = wintypes.DWORD
        try:
            self.ok = bool(
                kernel32.SetThreadExecutionState(
                    _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED
                )
            )
            self._ready.set()
            while not self._stop.wait(45):
                kernel32.SetThreadExecutionState(
                    _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED
                )
        except Exception as exc:
            _log().debug("保持系统唤醒失败：%s", exc)
            self.ok = False
            self._ready.set()
        finally:
            try:
                kernel32.SetThreadExecutionState(_ES_CONTINUOUS)
            except Exception:
                pass
            self._ready.set()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.5)
        self._thread = None
        self.ok = False


class LowPowerService:
    def __init__(
        self,
        state_dir: Callable[[], Path],
        is_busy: Callable[[], bool] | None = None,
    ) -> None:
        self._state_dir = state_dir
        self._is_busy = is_busy
        self._lock = threading.RLock()
        self._state_file: Path | None = None
        self._awake = _AwakeKeeper()
        self._state: dict[str, Any] = {
            "enabled": False,
            "supported": os.name == "nt",
            "started_at": None,
            "ended_at": None,
            "target_days": 7,
            "days_active": 0.0,
            "hold_awake": False,
            "eco_qos": False,
            "priority_lowered": False,
            "power_plan": {
                "before": None,
                "before_name": None,
                "active": None,
                "active_name": None,
                "changed": False,
            },
            "actions": [],
            "warnings": [],
            "cleanup": [],
            "last_message": "低功耗模式未开启。",
        }

    @property
    def enabled(self) -> bool:
        with self._lock:
            return bool(self._state["enabled"])

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            data = copy.deepcopy(self._state)
            data["single_instance_guard"] = True
            if data["enabled"] and data["started_at"]:
                try:
                    started = datetime.fromisoformat(str(data["started_at"]))
                    days = (datetime.now().astimezone() - started).total_seconds() / 86400
                    data["days_active"] = round(max(0.0, days), 2)
                except (ValueError, TypeError):
                    pass
            return data

    def _state_path(self) -> Path | None:
        try:
            base = Path(self._state_dir()).expanduser().resolve()
        except Exception as exc:
            _log().debug("无法解析低功耗状态目录：%s", exc)
            return None
        return base / "power_mode.json"

    def _write_crash_recovery(self, original_plan: tuple[str, str] | None) -> None:
        path = self._state_path()
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "original_plan": original_plan[0] if original_plan else None,
                "original_plan_name": original_plan[1] if original_plan else None,
                "written_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
            self._state_file = path
        except OSError as exc:
            _log().debug("写入低功耗恢复文件失败：%s", exc)

    def _clear_crash_recovery(self) -> None:
        path = self._state_file or self._state_path()
        if path is None:
            return
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        self._state_file = None

    def recover_stale_session(self) -> None:
        """上次异常退出若改过电源计划，启动时恢复原计划。"""

        path = self._state_path()
        if path is None or not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._clear_crash_recovery()
            return
        original = str(payload.get("original_plan") or "").strip()
        if not original:
            self._clear_crash_recovery()
            return
        active = get_active_plan()
        if active and active[0] == original.lower():
            self._clear_crash_recovery()
            return
        ok, output = set_active_plan(original)
        if ok:
            _log().info("已恢复上次异常退出前的电源计划：%s", payload.get("original_plan_name") or original)
            self._clear_crash_recovery()
        else:
            _log().warning("恢复电源计划失败：%s", output[:200])

    def activate(self, close_apps: list[str] | None = None) -> dict[str, Any]:
        close_apps = close_apps or []
        with self._lock:
            if self._state["enabled"]:
                return self.snapshot()
            if os.name != "nt":
                raise RuntimeError("低功耗模式目前仅支持 Windows。")

            actions: list[str] = []
            warnings: list[str] = []
            before = get_active_plan()
            changed = False
            active = before
            if before:
                if before[0] == POWER_SAVER_ALIAS:
                    actions.append("Windows 已处于节能电源计划，无需切换。")
                else:
                    ok, output = set_active_plan(POWER_SAVER_ALIAS)
                    if ok:
                        changed = True
                        active = get_active_plan() or before
                        actions.append("已切换到 Windows 节能电源计划。")
                    else:
                        warnings.append(
                            "无法切换系统电源计划（可能需要管理员权限），已退回进程级节能。"
                            f" {output[:140]}"
                        )
            else:
                warnings.append("无法读取当前电源计划，仅启用进程级节能。")

            efficiency = set_process_efficiency(True)
            if efficiency["priority"]:
                actions.append("Rewards Pilot 已降到最低 CPU 优先级。")
            if efficiency["eco_qos"]:
                actions.append("已启用 Windows EcoQoS 效率模式。")
            elif efficiency["detail"]:
                warnings.append(efficiency["detail"])

            awake = self._awake.start()
            if awake:
                actions.append("已阻止系统空闲休眠；显示器仍可正常关闭。")
            else:
                warnings.append("无法申请系统唤醒锁，请检查电源策略。")

            cleanup: list[dict[str, Any]] = []
            if close_apps:
                if self._is_busy and self._is_busy():
                    warnings.append("任务或登录窗口正在运行，已跳过关闭后台应用。")
                else:
                    cleanup = close_safe_background_apps(close_apps)
                    closed = sum(item["closed"] for item in cleanup)
                    if closed:
                        actions.append(f"已关闭 {closed} 个用户选择的后台进程。")
                    failed = [item for item in cleanup if item["failures"]]
                    if failed:
                        warnings.append("部分后台应用无法关闭，详情见下方结果。")

            if changed and before:
                self._write_crash_recovery(before)
            elif not changed:
                self._clear_crash_recovery()

            started_at = datetime.now().astimezone().isoformat(timespec="seconds")
            self._state = {
                "enabled": True,
                "supported": True,
                "started_at": started_at,
                "ended_at": None,
                "target_days": 7,
                "days_active": 0.0,
                "hold_awake": awake,
                "eco_qos": bool(efficiency["eco_qos"]),
                "priority_lowered": bool(efficiency["priority"]),
                "power_plan": {
                    "before": before[0] if before else None,
                    "before_name": before[1] if before else None,
                    "active": active[0] if active else None,
                    "active_name": active[1] if active else None,
                    "changed": changed,
                },
                "actions": actions,
                "warnings": warnings,
                "cleanup": cleanup,
                "last_message": "低功耗挂机已开启。",
            }
            _log().info(
                "低功耗模式已开启：系统计划=%s，唤醒锁=%s，EcoQoS=%s，清理=%s。",
                active[1] if active else "未知",
                awake,
                efficiency["eco_qos"],
                sum(item["closed"] for item in cleanup),
            )
            return self.snapshot()

    def deactivate(self) -> dict[str, Any]:
        with self._lock:
            if not self._state["enabled"]:
                return self.snapshot()
            actions: list[str] = []
            warnings: list[str] = []
            plan = self._state.get("power_plan") or {}

            self._awake.stop()
            if plan.get("changed") and plan.get("before"):
                ok, output = set_active_plan(str(plan["before"]))
                if ok:
                    actions.append(
                        f"已恢复电源计划：{plan.get('before_name') or plan['before']}。"
                    )
                    plan = {
                        **plan,
                        "active": plan.get("before"),
                        "active_name": plan.get("before_name"),
                        "changed": False,
                    }
                else:
                    warnings.append(f"恢复电源计划失败：{output[:180]}")
            self._clear_crash_recovery()

            efficiency = set_process_efficiency(False)
            if efficiency["priority"] or efficiency["eco_qos"]:
                actions.append("已恢复正常进程优先级。")

            self._state.update(
                {
                    "enabled": False,
                    "ended_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "hold_awake": False,
                    "eco_qos": False,
                    "priority_lowered": False,
                    "power_plan": plan,
                    "actions": actions,
                    "warnings": warnings,
                    "last_message": "低功耗挂机已关闭，电源计划已恢复。",
                }
            )
            _log().info(
                "低功耗模式已关闭：%s%s",
                "；".join(actions) or "无电源计划改动",
                f"；警告：{'；'.join(warnings)}" if warnings else "",
            )
            return self.snapshot()

    def shutdown(self) -> None:
        try:
            self.deactivate()
        except Exception:
            _log().exception("退出时恢复低功耗模式失败")
