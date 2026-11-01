from __future__ import annotations

import logging
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gui.autostart import AutostartManager, startup_command
from gui.server import _auto_exit_after_schedule, create_app
from gui.services import JobManager
from gui.settings_store import SettingsStore

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class StartupCommandTests(unittest.TestCase):
    def test_frozen_command_uses_exe_and_config(self) -> None:
        command = startup_command(
            Path(r"C:\Users\Me\Rewards Pilot\config.toml"),
            frozen=True,
            executable=Path(r"C:\Program Files\Rewards Pilot\RewardsPilot.exe"),
        )
        self.assertIn('"C:\\Program Files\\Rewards Pilot\\RewardsPilot.exe"', command)
        self.assertIn("--autostart", command)
        self.assertIn("--config", command)
        self.assertIn('"C:\\Users\\Me\\Rewards Pilot\\config.toml"', command)

    def test_source_command_prefers_pythonw(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            python = root / "python.exe"
            python.write_text("", encoding="utf-8")
            pythonw = root / "pythonw.exe"
            pythonw.write_text("", encoding="utf-8")
            config = root / "my config.toml"
            command = startup_command(
                config,
                frozen=False,
                executable=python,
                project_root=root,
            )
        self.assertIn(str(pythonw), command)
        self.assertIn("desktop.py", command)
        self.assertIn(f'"{config.resolve()}"', command)
        self.assertIn("--autostart", command)


@unittest.skipUnless(os.name == "nt", "开机启动注册表测试仅在 Windows 上运行")
class AutostartManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = AutostartManager(Path("config.toml"))

    def test_sync_enable_writes_command(self) -> None:
        with (
            patch("gui.autostart.read_registered", return_value=None),
            patch("gui.autostart.write_registered") as writer,
        ):
            ok, message = self.manager.sync(True)
        self.assertTrue(ok, message)
        writer.assert_called_once_with(self.manager.command())

    def test_sync_enable_is_idempotent(self) -> None:
        with (
            patch(
                "gui.autostart.read_registered",
                return_value=self.manager.command(),
            ),
            patch("gui.autostart.write_registered") as writer,
        ):
            ok, message = self.manager.sync(True)
        self.assertTrue(ok, message)
        writer.assert_not_called()

    def test_sync_disable_removes_entry(self) -> None:
        with (
            patch("gui.autostart.read_registered", return_value="old command"),
            patch("gui.autostart.remove_registered") as remover,
        ):
            ok, message = self.manager.sync(False)
        self.assertTrue(ok, message)
        remover.assert_called_once()

    def test_snapshot_reports_path_mismatch(self) -> None:
        with patch("gui.autostart.read_registered", return_value="stale.exe"):
            snapshot = self.manager.snapshot()
        self.assertTrue(snapshot["registered"])
        self.assertFalse(snapshot["matches"])
        self.assertTrue(snapshot["supported"])


class AutoExitTriggerTests(unittest.TestCase):
    def _runtime(self, enabled: bool = True):
        cfg = SimpleNamespace(
            general=SimpleNamespace(auto_exit_after_run=enabled),
        )
        return SimpleNamespace(
            store=SimpleNamespace(load=lambda: cfg),
            job=SimpleNamespace(running=False),
        )

    def test_successful_schedule_requests_shutdown(self) -> None:
        calls: list[str] = []
        tray = SimpleNamespace(notify=lambda message: calls.append(message))
        exits: list[str] = []

        def shutdown(reason: str):
            exits.append(reason)
            return True, "应用正在退出。"

        result = _auto_exit_after_schedule(
            self._runtime(),
            logging.getLogger("test.autostart"),
            shutdown,
            [tray],
            trigger="schedule",
            ok=True,
            message="ok",
            settle_seconds=0,
        )
        self.assertTrue(result)
        self.assertEqual(len(exits), 1)
        self.assertTrue(any("即将退出" in item for item in calls))

    def test_manual_run_does_not_exit(self) -> None:
        exits: list[str] = []
        result = _auto_exit_after_schedule(
            self._runtime(),
            logging.getLogger("test.autostart"),
            lambda reason: (exits.append(reason) or (True, "退出")),
            [],
            trigger="manual",
            ok=True,
            message="ok",
            settle_seconds=0,
        )
        self.assertFalse(result)
        self.assertEqual(exits, [])

    def test_failed_schedule_keeps_app_alive(self) -> None:
        calls: list[str] = []
        tray = SimpleNamespace(notify=lambda message: calls.append(message))
        exits: list[str] = []
        result = _auto_exit_after_schedule(
            self._runtime(),
            logging.getLogger("test.autostart"),
            lambda reason: (exits.append(reason) or (True, "退出")),
            [tray],
            trigger="schedule",
            ok=False,
            message="failed",
            settle_seconds=0,
        )
        self.assertFalse(result)
        self.assertEqual(exits, [])
        self.assertTrue(any("保留后台" in item for item in calls))

    def test_disabled_setting_does_not_exit(self) -> None:
        exits: list[str] = []
        result = _auto_exit_after_schedule(
            self._runtime(enabled=False),
            logging.getLogger("test.autostart"),
            lambda reason: (exits.append(reason) or (True, "退出")),
            [],
            trigger="schedule",
            ok=True,
            message="ok",
            settle_seconds=0,
        )
        self.assertFalse(result)
        self.assertEqual(exits, [])


class JobCompletionListenerTests(unittest.TestCase):
    def test_listeners_receive_trigger_and_result(self) -> None:
        manager = JobManager(SimpleNamespace(), is_login_active=lambda: False)
        seen: list[tuple[str, bool, str]] = []
        manager.add_finished_listener(
            lambda trigger, ok, message: seen.append((trigger, ok, message))
        )
        manager._notify_finished("schedule", True, "done")
        self.assertEqual(seen, [("schedule", True, "done")])


class SettingsAutoExitTests(unittest.TestCase):
    def test_update_and_public_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            shutil.copyfile(PROJECT_ROOT / "config.example.toml", path)
            store = SettingsStore(path, PROJECT_ROOT / "config.example.toml")
            cfg = store.update({"general": {"auto_exit_after_run": True}})
            self.assertTrue(cfg.general.auto_exit_after_run)
            self.assertTrue(
                store.public(cfg)["general"]["auto_exit_after_run"]
            )
            cfg = store.update({"general": {"auto_exit_after_run": False}})
            self.assertFalse(cfg.general.auto_exit_after_run)


class _FakeAutostart:
    def __init__(self) -> None:
        self.enabled = False
        self.sync_calls: list[bool] = []

    def sync(self, enabled: bool) -> tuple[bool, str]:
        self.sync_calls.append(enabled)
        self.enabled = enabled
        return True, "已登记开机启动。" if enabled else "已移除开机启动。"

    def snapshot(self) -> dict:
        return {
            "supported": True,
            "registered": self.enabled,
            "matches": self.enabled,
            "error": None,
        }


class SettingsAutostartAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name) / "config.toml"
        shutil.copyfile(PROJECT_ROOT / "config.example.toml", path)
        self.store = SettingsStore(path, PROJECT_ROOT / "config.example.toml")
        self.autostart = _FakeAutostart()
        runtime = SimpleNamespace(
            store=self.store,
            autostart=self.autostart,
            scheduler=SimpleNamespace(restart=lambda: None),
        )
        self.token = "autostart-test-token"
        self.client = create_app(runtime, self.token).test_client()
        self.headers = {"X-App-Token": self.token}

    def test_settings_exposes_autostart_and_toggle_updates_registry(self) -> None:
        response = self.client.get("/api/settings", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("autostart", data)
        self.assertFalse(data["settings"]["general"]["auto_exit_after_run"])

        response = self.client.put(
            "/api/settings",
            headers=self.headers,
            json={"general": {"auto_exit_after_run": True}},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["settings"]["general"]["auto_exit_after_run"])
        self.assertTrue(data["autostart"]["matches"])
        self.assertEqual(self.autostart.sync_calls, [True])

        response = self.client.put(
            "/api/settings",
            headers=self.headers,
            json={"general": {"auto_exit_after_run": False}},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            response.get_json()["settings"]["general"]["auto_exit_after_run"]
        )
        self.assertEqual(self.autostart.sync_calls, [True, False])


if __name__ == "__main__":
    unittest.main()
