from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gui.onboarding import MARKER_VERSION, OnboardingStore
from gui.server import create_app
from rewards_bot.config import load_config


class OnboardingStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state_dir = Path(self.tmp.name) / "state"
        self.store = OnboardingStore(lambda: self.state_dir)

    def test_first_run_is_unseen(self) -> None:
        snapshot = self.store.snapshot()
        self.assertFalse(snapshot["seen"])
        self.assertTrue(snapshot["show"])
        self.assertEqual(snapshot["version"], MARKER_VERSION)

    def test_complete_is_persisted_without_sensitive_data(self) -> None:
        snapshot = self.store.complete("completed")
        self.assertTrue(snapshot["seen"])
        self.assertFalse(snapshot["show"])
        self.assertEqual(snapshot["action"], "completed")
        marker = self.state_dir / "onboarding.json"
        self.assertTrue(marker.is_file())
        payload = json.loads(marker.read_text(encoding="utf-8"))
        self.assertTrue(payload["completed"])
        self.assertEqual(payload["version"], MARKER_VERSION)
        self.assertEqual(set(payload), {"version", "completed", "completed_at", "action"})

    def test_skip_updates_action(self) -> None:
        self.store.complete("completed")
        snapshot = self.store.complete("skipped")
        self.assertTrue(snapshot["seen"])
        self.assertEqual(snapshot["action"], "skipped")

    def test_invalid_action_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.store.complete("forged")

    def test_corrupt_marker_shows_tutorial_again(self) -> None:
        self.state_dir.mkdir(parents=True)
        (self.state_dir / "onboarding.json").write_text("{not json", encoding="utf-8")
        self.assertTrue(self.store.snapshot()["show"])

    def test_old_marker_version_is_not_trusted(self) -> None:
        self.state_dir.mkdir(parents=True)
        (self.state_dir / "onboarding.json").write_text(
            json.dumps({"version": 0, "completed": True, "action": "completed"}),
            encoding="utf-8",
        )
        self.assertTrue(self.store.snapshot()["show"])

    def test_newer_marker_version_is_trusted(self) -> None:
        self.state_dir.mkdir(parents=True)
        (self.state_dir / "onboarding.json").write_text(
            json.dumps({"version": 99, "completed": True, "action": "completed"}),
            encoding="utf-8",
        )
        self.assertTrue(self.store.snapshot()["seen"])


class _FakeJob:
    running = False

    def snapshot(self) -> dict:
        return {
            "running": False,
            "state": "idle",
            "mode": None,
            "trigger": None,
            "started_at": None,
            "finished_at": None,
            "ok": None,
            "message": "等待运行",
        }


class _FakeLogin:
    active = False

    def snapshot(self) -> dict:
        return {
            "active": False,
            "state": "idle",
            "message": "尚未打开登录窗口",
            "started_at": None,
            "finished_at": None,
        }

    def cancel(self) -> None:
        return None


class _FakeScheduler:
    def __init__(self) -> None:
        self.running = False
        self.start_calls: list[bool | None] = []
        self.stop_calls = 0

    def snapshot(self) -> dict:
        return {
            "running": self.running,
            "next_run": None,
            "run_at": "08:30",
            "timezone": "Asia/Shanghai",
        }

    def start(self, catch_up: bool | None = None) -> tuple[bool, str]:
        self.start_calls.append(catch_up)
        return True, "每日调度已启动。"

    def stop(self) -> tuple[bool, str]:
        self.stop_calls += 1
        return True, "每日调度已停止。"


class _FakePower:
    def snapshot(self) -> dict:
        return {"enabled": False, "supported": True}


class _FakeRuntime:
    def __init__(self, store, onboarding) -> None:
        self.store = store
        self.onboarding = onboarding
        self.job = _FakeJob()
        self.login = _FakeLogin()
        self.scheduler = _FakeScheduler()
        self.power = _FakePower()


class OnboardingAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.state_dir = base / "state"
        config_path = base / "config.toml"
        secret = "sk-onboarding-test-secret"
        config_path.write_text(
            "[general]\n"
            "mode = \"basic\"\n"
            f"state_dir = {json.dumps(self.state_dir.as_posix())}\n"
            "[advanced]\n"
            f"api_key = {json.dumps(secret)}\n",
            encoding="utf-8",
        )
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            cfg = load_config(config_path)
        self.secret = secret
        self.store = type("Store", (), {"load": lambda _self: cfg})()
        self.onboarding = OnboardingStore(lambda: self.state_dir)
        self.runtime = _FakeRuntime(self.store, self.onboarding)
        self.token = "test-token"
        self.app = create_app(self.runtime, self.token)
        self.client = self.app.test_client()
        self.headers = {"X-App-Token": self.token}

    def test_state_exposes_onboarding_without_api_key(self) -> None:
        response = self.client.get("/api/state", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["onboarding"]["show"])
        self.assertFalse(data["onboarding"]["seen"])
        self.assertNotIn(self.secret, response.get_data(as_text=True))

    def test_requires_token(self) -> None:
        self.assertEqual(self.client.get("/api/onboarding").status_code, 401)
        self.assertEqual(
            self.client.post("/api/onboarding/complete", json={"action": "skipped"}).status_code,
            401,
        )

    def test_complete_and_skip_are_persisted(self) -> None:
        response = self.client.post(
            "/api/onboarding/complete",
            headers=self.headers,
            json={"action": "skipped"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["onboarding"]["seen"])
        self.assertEqual(response.get_json()["onboarding"]["action"], "skipped")
        state = self.client.get("/api/state", headers=self.headers).get_json()
        self.assertTrue(state["onboarding"]["seen"])
        self.assertFalse(state["onboarding"]["show"])
        self.assertTrue((self.state_dir / "onboarding.json").is_file())

    def test_invalid_action_is_rejected(self) -> None:
        response = self.client.post(
            "/api/onboarding/complete",
            headers=self.headers,
            json={"action": "forged"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertTrue(self.onboarding.snapshot()["show"])

    def test_scheduler_start_can_disable_catch_up(self) -> None:
        response = self.client.post(
            "/api/scheduler/start",
            headers=self.headers,
            json={"catch_up": False},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.runtime.scheduler.start_calls, [False])

        response = self.client.post(
            "/api/scheduler/start",
            headers=self.headers,
            json={"catch_up": "no"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.runtime.scheduler.start_calls, [False])


if __name__ == "__main__":
    unittest.main()
