from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from rewards_bot.config import ConfigError, load_config
from rewards_bot.scheduler import DailyScheduler

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ConfigTests(unittest.TestCase):
    def test_example_config_loads(self) -> None:
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            cfg = load_config(PROJECT_ROOT / "config.example.toml")
        self.assertEqual(cfg.general.mode, "basic")
        self.assertEqual(cfg.general.run_at, "08:30")
        self.assertEqual(cfg.general.timezone, "Asia/Shanghai")
        self.assertEqual(cfg.general.browser_channel, "msedge")
        self.assertEqual(cfg.general.run_hour_minute, (8, 30))
        self.assertTrue(cfg.general.catch_up)
        self.assertEqual(cfg.general.url, "https://rewards.bing.com/earn")
        self.assertFalse(cfg.basic.search_enabled)
        self.assertFalse(cfg.advanced.vision_supported)

    def test_legacy_dashboard_url_migrates_to_earn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.toml"
            path.write_text(
                '[general]\nurl = "https://rewards.bing.com/dashboard"\n',
                encoding="utf-8",
            )
            cfg = load_config(path)
        self.assertEqual(cfg.general.url, "https://rewards.bing.com/earn")

    def test_custom_url_is_not_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "custom.toml"
            path.write_text(
                '[general]\nurl = "https://rewards.bing.com/earn?region=cn"\n',
                encoding="utf-8",
            )
            cfg = load_config(path)
        self.assertEqual(cfg.general.url, "https://rewards.bing.com/earn?region=cn")

    def test_env_api_key_fallback(self) -> None:
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test"}):
            cfg = load_config(PROJECT_ROOT / "config.example.toml")
        self.assertEqual(cfg.advanced.api_key, "sk-test")

    def test_invalid_run_at(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.toml"
            path.write_text('[general]\nrun_at = "25:99"\n', encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_relative_paths_resolve_to_config_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.toml"
            path.write_text(
                '[general]\nuser_data_dir = "profile"\nstate_dir = "st"\nlog_dir = "lg"\n',
                encoding="utf-8",
            )
            cfg = load_config(path)
        self.assertEqual(cfg.general.user_data_dir, Path(tmp).resolve() / "profile")
        self.assertEqual(cfg.general.state_dir, Path(tmp).resolve() / "st")
        self.assertEqual(cfg.general.log_dir, Path(tmp).resolve() / "lg")

    def test_unknown_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.toml"
            path.write_text('[general]\nmode = "magic"\n', encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path)


class SchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.cfg = load_config(PROJECT_ROOT / "config.example.toml").general
        self.cfg.run_at = "08:30"
        self.cfg.state_dir = base
        self.scheduler = DailyScheduler(self.cfg)

    def test_next_run_before_and_after(self) -> None:
        tz = self.cfg.tzinfo
        before = datetime(2026, 11, 1, 7, 0, tzinfo=tz)
        after = datetime(2026, 11, 1, 9, 0, tzinfo=tz)
        self.assertEqual(self.scheduler._next_run(before).day, 1)
        self.assertEqual(self.scheduler._next_run(before).hour, 8)
        self.assertEqual(self.scheduler._next_run(after).day, 2)
        self.assertEqual(self.scheduler._next_run(after).hour, 8)

    def test_state_roundtrip(self) -> None:
        from datetime import date

        self.scheduler._mark_attempted(date(2026, 11, 1))
        self.assertEqual(self.scheduler._read_last_date(), date(2026, 11, 1))


if __name__ == "__main__":
    unittest.main()
