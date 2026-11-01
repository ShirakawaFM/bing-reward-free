from __future__ import annotations

import os
import unittest
from pathlib import Path

from rewards_bot.window_branding import (
    BrandSnapshot,
    BrowserWindow,
    app_icon_path,
    apply_window_icon,
    browser_icon_path,
    is_browser_executable,
    select_new_windows,
)


def window(
    hwnd: int,
    pid: int,
    executable: str = "msedge.exe",
    title: str = "about:blank",
    visible: bool = True,
) -> BrowserWindow:
    return BrowserWindow(
        hwnd=hwnd,
        pid=pid,
        executable=executable,
        title=title,
        visible=visible,
    )


class WindowBrandingTests(unittest.TestCase):
    def test_browser_executable_detection(self) -> None:
        self.assertTrue(is_browser_executable("msedge.exe"))
        self.assertTrue(is_browser_executable(r"C:\Program Files\Edge\MSEDGE.EXE"))
        self.assertTrue(is_browser_executable("chrome.exe"))
        self.assertFalse(is_browser_executable("explorer.exe"))
        self.assertFalse(is_browser_executable("msedgewebview2.exe"))
        self.assertFalse(is_browser_executable(""))

    def test_icon_assets_exist(self) -> None:
        path = browser_icon_path()
        self.assertTrue(path.is_file())
        self.assertEqual(path.suffix.lower(), ".ico")
        self.assertTrue(app_icon_path().is_file())

    def test_select_new_windows_requires_new_handle_and_process(self) -> None:
        before = BrandSnapshot(handles=frozenset({10, 11}), pids=frozenset({100, 101}))
        windows = [
            window(10, 102),  # 旧窗口
            window(12, 101),  # 旧浏览器进程新开的窗口
            window(13, 103, visible=False),
            window(14, 104, title="   "),
            window(15, 105, executable="explorer.exe"),
            window(16, 106),
            window(17, 106, title="任务页"),
        ]
        selected = select_new_windows(before, windows)
        self.assertEqual([item.hwnd for item in selected], [16, 17])

    @unittest.skipUnless(os.name == "nt", "Windows-only icon API")
    def test_apply_icon_rejects_missing_handle(self) -> None:
        self.assertFalse(apply_window_icon(0))
        self.assertTrue(Path(browser_icon_path()).is_file())


if __name__ == "__main__":
    unittest.main()
