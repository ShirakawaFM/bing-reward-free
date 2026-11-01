from __future__ import annotations

import threading
import unittest
from pathlib import Path
from unittest import mock

from gui import server


class ConsoleWindowManagerTests(unittest.TestCase):
    """退出时只能关闭本实例跟踪过的控制台窗口。"""

    def _manager(self) -> server.ConsoleWindowManager:
        return server.ConsoleWindowManager(
            "http://127.0.0.1:1",
            None,
            threading.Event(),
            Path("."),
            exit_on_close=False,
        )

    def test_close_all_only_closes_tracked_windows(self) -> None:
        manager = self._manager()
        manager.mark_opened(101)
        manager.mark_opened(102)
        manager.mark_closed(102)

        with mock.patch.object(server, "_ui_window_handles", return_value={101, 999}):
            with mock.patch.object(server, "_close_window") as close:
                manager.close_all()

        close.assert_called_once_with(101)

    def test_close_all_ignores_untracked_app_window(self) -> None:
        manager = self._manager()

        with mock.patch.object(server, "_ui_window_handles", return_value={777}):
            with mock.patch.object(server, "_close_window") as close:
                manager.close_all()

        close.assert_not_called()

    def test_focused_existing_window_is_tracked_and_closed(self) -> None:
        manager = self._manager()

        with mock.patch.object(server, "_ui_window_handles", return_value={202}):
            with mock.patch.object(server, "_focus_window", return_value=True) as focus:
                manager.open()
        focus.assert_called_once_with(202)

        with mock.patch.object(server, "_ui_window_handles", return_value={202}):
            with mock.patch.object(server, "_close_window") as close:
                manager.close_all()

        close.assert_called_once_with(202)


if __name__ == "__main__":
    unittest.main()
