from __future__ import annotations

import ctypes
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .paths import RESOURCE_ROOT

LOG = logging.getLogger("rewards_bot.window_branding")

BROWSER_EXECUTABLES = frozenset(
    {
        "msedge.exe",
        "chrome.exe",
        "chromium.exe",
        "brave.exe",
        "vivaldi.exe",
    }
)

WINDOW_CLASS = "Chrome_WidgetWin_1"
WM_SETICON = 0x0080
ICON_SMALL = 0
ICON_BIG = 1
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
SM_CXICON = 11
SM_CXSMICON = 49
SMTO_ABORTIFHUNG = 0x0002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
CLSID_TASKBAR_LIST = "{56FDF344-FD6D-11d0-958A-006097C9A090}"
IID_TASKBAR_LIST3 = "{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}"
TASKBAR_TITLE = "Rewards Pilot 任务浏览器"


@dataclass(frozen=True, slots=True)
class BrowserWindow:
    hwnd: int
    pid: int
    executable: str
    title: str
    visible: bool = True


@dataclass(frozen=True, slots=True)
class BrandSnapshot:
    handles: frozenset[int]
    pids: frozenset[int]


def browser_icon_path() -> Path:
    preferred = RESOURCE_ROOT / "assets" / "task-browser.ico"
    fallback = RESOURCE_ROOT / "assets" / "app.ico"
    return preferred if preferred.exists() else fallback


def app_icon_path() -> Path:
    return RESOURCE_ROOT / "assets" / "app.ico"


def is_browser_executable(name: str) -> bool:
    return Path(str(name or "")).name.lower() in BROWSER_EXECUTABLES


def select_new_windows(
    before: BrandSnapshot,
    windows: Iterable[BrowserWindow],
) -> list[BrowserWindow]:
    """只挑出启动后新出现的 Chromium 浏览器窗口。

    使用“新句柄 + 新进程号”双重过滤，避免把用户此前就打开、
    或刚刚手动打开的同进程 Edge 窗口误认为任务浏览器。
    """

    selected: list[BrowserWindow] = []
    for window in windows:
        if window.hwnd in before.handles:
            continue
        if window.pid in before.pids:
            continue
        if not window.visible or not window.title.strip():
            continue
        if not is_browser_executable(window.executable):
            continue
        selected.append(window)
    return selected


def _is_windows() -> bool:
    return os.name == "nt"


def _win_dll(name: str) -> ctypes.WinDLL:
    return ctypes.WinDLL(name, use_last_error=True)


def _bind_user32(user32) -> None:
    from ctypes import wintypes

    user32.EnumWindows.argtypes = [
        ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM),
        wintypes.LPARAM,
    ]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.LoadImageW.argtypes = [
        wintypes.HINSTANCE,
        wintypes.LPCWSTR,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    user32.SendMessageTimeoutW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    user32.SendMessageTimeoutW.restype = wintypes.LPARAM


def _bind_kernel32(kernel32) -> None:
    from ctypes import wintypes

    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    kernel32.Process32NextW.restype = wintypes.BOOL


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("cntUsage", ctypes.c_uint32),
        ("th32ProcessID", ctypes.c_uint32),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", ctypes.c_uint32),
        ("cntThreads", ctypes.c_uint32),
        ("th32ParentProcessID", ctypes.c_uint32),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_uint32),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


def _process_image_name(kernel32, pid: int) -> str:
    from ctypes import wintypes

    if pid <= 0:
        return ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buffer))
        if not kernel32.QueryFullProcessImageNameW(
            handle, 0, buffer, ctypes.byref(size)
        ):
            return ""
        return Path(buffer.value).name.lower()
    finally:
        kernel32.CloseHandle(handle)


def _browser_process_ids(kernel32) -> set[int]:
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == INVALID_HANDLE_VALUE:
        return set()
    pids: set[int] = set()
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            if is_browser_executable(entry.szExeFile):
                pids.add(int(entry.th32ProcessID))
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return pids


def collect_browser_windows() -> list[BrowserWindow]:
    if not _is_windows():
        return []
    from ctypes import wintypes

    user32 = _win_dll("user32")
    kernel32 = _win_dll("kernel32")
    _bind_user32(user32)
    _bind_kernel32(kernel32)

    found: list[BrowserWindow] = []
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        title_length = user32.GetWindowTextLengthW(hwnd)
        if title_length <= 0:
            return True
        class_buffer = ctypes.create_unicode_buffer(256)
        if not user32.GetClassNameW(hwnd, class_buffer, 256):
            return True
        if class_buffer.value != WINDOW_CLASS:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        executable = _process_image_name(kernel32, int(pid.value))
        if not is_browser_executable(executable):
            return True
        title_buffer = ctypes.create_unicode_buffer(title_length + 1)
        user32.GetWindowTextW(hwnd, title_buffer, title_length + 1)
        found.append(
            BrowserWindow(
                hwnd=int(hwnd),
                pid=int(pid.value),
                executable=executable,
                title=title_buffer.value,
                visible=True,
            )
        )
        return True

    user32.EnumWindows(enum_proc(callback), 0)
    return found


def snapshot_task_browser() -> BrandSnapshot:
    """记录启动任务浏览器前的浏览器窗口与进程，用于识别新窗口。"""

    if not _is_windows():
        return BrandSnapshot(frozenset(), frozenset())
    try:
        kernel32 = _win_dll("kernel32")
        _bind_kernel32(kernel32)
        windows = collect_browser_windows()
        pids = _browser_process_ids(kernel32)
        return BrandSnapshot(
            handles=frozenset(window.hwnd for window in windows),
            pids=frozenset(pid for pid in pids if pid > 0),
        )
    except Exception as exc:
        LOG.debug("无法记录浏览器窗口快照：%s", exc)
        return BrandSnapshot(frozenset(), frozenset())


_ICON_CACHE: dict[tuple[str, int, int], tuple[int, int]] = {}


def _load_icon_handles(path: Path) -> tuple[int, int]:
    if not _is_windows() or not path.exists():
        return (0, 0)
    from ctypes import wintypes

    user32 = _win_dll("user32")
    _bind_user32(user32)
    big_size = user32.GetSystemMetrics(SM_CXICON) or 32
    small_size = user32.GetSystemMetrics(SM_CXSMICON) or 16
    key = (str(path), big_size, small_size)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    big = user32.LoadImageW(
        None, str(path), IMAGE_ICON, big_size, big_size, LR_LOADFROMFILE
    )
    small = user32.LoadImageW(
        None, str(path), IMAGE_ICON, small_size, small_size, LR_LOADFROMFILE
    )
    handles = (int(big or 0), int(small or 0))
    _ICON_CACHE[key] = handles
    return handles


def _send_seticon(hwnd: int, which: int, icon: int) -> bool:
    if not _is_windows() or not hwnd or not icon:
        return False
    user32 = _win_dll("user32")
    _bind_user32(user32)
    result = ctypes.c_size_t()
    ok = user32.SendMessageTimeoutW(
        hwnd,
        WM_SETICON,
        which,
        icon,
        SMTO_ABORTIFHUNG,
        1_000,
        ctypes.byref(result),
    )
    return bool(ok)


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _set_taskbar_overlay(hwnd: int, icon: int) -> bool:
    """给任务栏按钮加一个右上角徽标。

    Edge/Chrome 窗口的 AppUserModelID 由浏览器自身注册，任务栏主图标
    会继续显示 Edge。微软没有公开替换其他进程任务栏主图标的方法，
    但 ITaskbarList3 的覆盖图标可以稳定地把专属徽标叠在按钮上，
    配合窗口图标，让用户一眼识别任务浏览器。
    """

    if not _is_windows() or not hwnd or not icon:
        return False
    ole32 = _win_dll("ole32")
    ole32.CoInitialize.argtypes = [ctypes.c_void_p]
    ole32.CoInitialize.restype = ctypes.c_long
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None
    ole32.CLSIDFromString.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(_GUID)]
    ole32.CLSIDFromString.restype = ctypes.c_long
    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(_GUID),
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(_GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    ole32.CoCreateInstance.restype = ctypes.c_long

    initialized = ole32.CoInitialize(None)
    should_uninitialize = initialized in (0, 1)
    clsid = _GUID()
    iid = _GUID()
    if ole32.CLSIDFromString(CLSID_TASKBAR_LIST, ctypes.byref(clsid)) != 0:
        if should_uninitialize:
            ole32.CoUninitialize()
        return False
    if ole32.CLSIDFromString(IID_TASKBAR_LIST3, ctypes.byref(iid)) != 0:
        if should_uninitialize:
            ole32.CoUninitialize()
        return False
    pointer = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(
        ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(pointer)
    )
    if hr != 0 or not pointer.value:
        if should_uninitialize:
            ole32.CoUninitialize()
        return False

    try:
        vtable = ctypes.cast(
            pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
        )[0]

        def call(index: int, argtypes, *args, restype=ctypes.c_long):
            function = ctypes.WINFUNCTYPE(restype, *argtypes)(vtable[index])
            return function(*args)

        init_hr = call(3, [ctypes.c_void_p], pointer)
        if init_hr != 0:
            return False
        overlay_hr = call(
            18,
            [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p],
            pointer,
            ctypes.c_void_p(hwnd),
            ctypes.c_void_p(icon),
            TASKBAR_TITLE,
        )
        return overlay_hr == 0
    except Exception as exc:
        LOG.debug("设置任务栏徽标失败 hwnd=%s：%s", hwnd, exc)
        return False
    finally:
        try:
            release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(
                vtable[2]
            )
            release(pointer)
        except Exception:
            pass
        if should_uninitialize:
            ole32.CoUninitialize()


def apply_window_icon(
    hwnd: int,
    icon_path: Path | None = None,
    *,
    overlay: bool = False,
) -> bool:
    """给 Chromium 顶层窗口设置图标（任务栏与标题栏都会更新）。"""

    if not _is_windows() or not hwnd:
        return False
    path = icon_path or browser_icon_path()
    try:
        big, small = _load_icon_handles(path)
        if not big and not small:
            LOG.debug("图标资源不可用：%s", path)
            return False
        changed_big = _send_seticon(hwnd, ICON_BIG, big)
        changed_small = _send_seticon(hwnd, ICON_SMALL, small)
        if overlay and small:
            _set_taskbar_overlay(hwnd, small)
        return changed_big or changed_small
    except Exception as exc:
        LOG.debug("设置窗口图标失败 hwnd=%s：%s", hwnd, exc)
        return False


def _icon_for_snapshot() -> Path:
    return browser_icon_path()


def brand_task_browser(
    before: BrandSnapshot | None,
    *,
    timeout: float = 4.0,
    poll: float = 0.2,
) -> list[BrowserWindow]:
    """等待并标记新启动的任务浏览器窗口，失败时安静跳过。"""

    if not _is_windows() or before is None:
        return []
    deadline = time.monotonic() + max(0.0, timeout)
    last_new_at: float | None = None
    branded: dict[int, BrowserWindow] = {}
    icon_path = _icon_for_snapshot()
    while True:
        try:
            candidates = select_new_windows(before, collect_browser_windows())
        except Exception as exc:
            LOG.debug("枚举任务浏览器窗口失败：%s", exc)
            candidates = []
        for window in candidates:
            if window.hwnd in branded:
                continue
            if apply_window_icon(window.hwnd, icon_path, overlay=True):
                branded[window.hwnd] = window
                last_new_at = time.monotonic()
                LOG.info(
                    "已为任务浏览器窗口设置专属图标：hwnd=%s pid=%s",
                    window.hwnd,
                    window.pid,
                )
        now = time.monotonic()
        if branded and last_new_at is not None and now - last_new_at >= 0.8:
            break
        if now >= deadline:
            break
        time.sleep(poll)
    if not branded:
        LOG.debug("未发现新任务浏览器窗口，跳过图标标记。")
    return list(branded.values())


def brand_app_window(hwnd: int) -> bool:
    """给应用自身的 Edge --app 窗口设置应用图标。"""

    if not _is_windows() or not hwnd:
        return False
    changed = apply_window_icon(hwnd, app_icon_path())
    if changed:
        LOG.info("已为应用窗口设置任务图标：hwnd=%s", hwnd)
    return changed