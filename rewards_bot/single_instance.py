from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

_MUTEX_NAME = "Local\\RewardsPilot.SingleInstance.v1"
_ERROR_ALREADY_EXISTS = 183
_mutex_handle: int | None = None


def acquire_single_instance(name: str = _MUTEX_NAME) -> bool:
    """创建会话级互斥量，确保只运行一个 Rewards Pilot。

    互斥句柄保存在模块全局变量中，进程退出时由 Windows 自动释放。
    """

    global _mutex_handle
    if os.name != "nt":
        return True
    if _mutex_handle:
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [
            ctypes.c_void_p,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.GetLastError.restype = wintypes.DWORD
        handle = kernel32.CreateMutexW(None, False, name)
        if not handle:
            return True
        if kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        _mutex_handle = int(handle)
        return True
    except Exception:
        # 单实例保护失败时不能阻止程序启动。
        return True


def focus_existing_window(marker: str = "Rewards Pilot") -> bool:
    """尝试把已运行的应用窗口带到前台。"""

    if os.name != "nt":
        return False
    try:
        user32 = ctypes.windll.user32
        found: list[int] = []
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
                        found.append(int(hwnd))
            return True

        user32.EnumWindows(enum_proc(callback), 0)
        if not found:
            return False
        hwnd = found[0]
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False
