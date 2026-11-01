from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rewards_bot.config import ConfigError, load_config
from rewards_bot.tasks_catalog import (
    AI_ONLY_TASK_IDS,
    BASIC_CARD_TASK_IDS,
    DEFAULT_TASK_TYPES,
    MANUAL_TASK_IDS,
    TASK_BY_ID,
    TASK_IDS,
    catalog_payload,
    classify_task,
    points_forecast,
    validate_task_types,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def task(text: str, section: str = "unknown") -> dict:
    return {"text": text, "own_text": text, "href": "", "section": section}


class TaskCatalogTests(unittest.TestCase):
    def test_catalog_integrity(self) -> None:
        self.assertEqual(len(TASK_IDS), len(set(TASK_IDS)))
        self.assertTrue(set(DEFAULT_TASK_TYPES).issubset(BASIC_CARD_TASK_IDS))
        self.assertTrue(AI_ONLY_TASK_IDS)
        self.assertTrue(MANUAL_TASK_IDS)
        self.assertFalse(set(BASIC_CARD_TASK_IDS) & set(AI_ONLY_TASK_IDS))
        self.assertFalse(set(BASIC_CARD_TASK_IDS) & set(MANUAL_TASK_IDS))
        self.assertTrue(all(spec.label for spec in TASK_BY_ID.values()))

    def test_catalog_payload_groups_every_item(self) -> None:
        payload = catalog_payload()
        group_ids = {group["id"] for group in payload["groups"]}
        self.assertTrue(all(item["group"] in group_ids for item in payload["items"]))
        self.assertEqual(len(payload["items"]), len(TASK_IDS))

    def test_validate_task_types_orders_and_rejects_unknown(self) -> None:
        self.assertEqual(
            validate_task_types(["more_link", "daily_quiz"]),
            ["daily_quiz", "more_link"],
        )
        self.assertEqual(validate_task_types([]), [])
        with self.assertRaises(ValueError):
            validate_task_types(["not-a-task"])
        with self.assertRaises(ValueError):
            validate_task_types(["survey"])
        with self.assertRaises(ValueError):
            validate_task_types("daily_quiz")

    def test_classify_sections_and_kinds(self) -> None:
        cases = [
            (task("每日测验：选出正确答案 +10", "daily"), "daily_quiz"),
            (task("Daily quiz +15", "more"), "more_quiz"),
            (task("每日投票 +10", "daily"), "daily_poll"),
            (task("本周集锦 +100", "weekly"), "weekly_set"),
            (task("每月打卡 +50", "monthly"), "monthly_set"),
            (task("阅读这篇文章 +5", "more"), "more_link"),
            (task("每日签到 +30", "daily"), "checkin"),
            (task("This or That：猫还是狗", "daily"), "this_or_that"),
            (task("观看视频 +10", "more"), "video"),
            (task("未知的普通浏览卡片 +5", "unknown"), "more_link"),
        ]
        for sample, expected in cases:
            with self.subTest(sample=sample["text"]):
                self.assertEqual(classify_task(sample), expected)

    def test_classify_marks_ai_and_manual_tasks(self) -> None:
        cases = [
            (task("填写问卷 +50"), "survey"),
            (task("连胜保护 +20"), "streak"),
            (task("限时活动 +100"), "special_events"),
            (task("购买 Surface 返 500 积分"), "purchase"),
            (task("Xbox Game Pass 任务"), "xbox"),
            (task("移动端搜索 3 次"), "mobile_search"),
            (task("邀请好友加入"), "referral"),
            (task("完善个人资料"), "profile"),
        ]
        for sample, expected in cases:
            with self.subTest(sample=sample["text"]):
                self.assertEqual(classify_task(sample), expected)


class PointsForecastTests(unittest.TestCase):
    def test_default_forecast_is_a_transparent_local_estimate(self) -> None:
        forecast = points_forecast(DEFAULT_TASK_TYPES, search_enabled=False)
        self.assertTrue(forecast["estimated"])
        self.assertEqual(forecast["selected_count"], 11)
        self.assertEqual(forecast["selectable_count"], 11)
        self.assertEqual(forecast["missing_ids"], ["web_search"])
        self.assertEqual(forecast["missing_labels"], ["Bing 每日搜索"])
        self.assertEqual(forecast["missing_count"], 1)
        self.assertEqual(forecast["daily"]["low"], 65)
        self.assertEqual(forecast["daily"]["high"], 278)
        self.assertEqual(forecast["weekly"]["low"], 458)
        self.assertEqual(forecast["weekly"]["high"], 1947)
        self.assertLess(forecast["daily"]["low"], forecast["daily"]["mid"])
        self.assertLess(forecast["daily"]["mid"], forecast["daily"]["high"])
        self.assertEqual(forecast["locked_ai_count"], len(AI_ONLY_TASK_IDS))
        self.assertEqual(forecast["locked_manual_count"], len(MANUAL_TASK_IDS))

    def test_no_missing_options_when_everything_is_enabled(self) -> None:
        forecast = points_forecast(
            BASIC_CARD_TASK_IDS,
            search_enabled=True,
            search_count=20,
            auto_claim=True,
        )
        self.assertEqual(forecast["missing_count"], 0)
        self.assertEqual(forecast["missing_ids"], [])
        self.assertEqual(forecast["missing_daily"], {"low": 0, "high": 0, "mid": 0})
        # 20 次搜索按每次 3 分计入每日上限。
        self.assertEqual(forecast["daily"]["high"], 278 + 60)
        self.assertEqual(forecast["daily"]["low"], 65)
        self.assertTrue(forecast["auto_claim"])

    def test_search_points_are_capped(self) -> None:
        capped = points_forecast(BASIC_CARD_TASK_IDS, search_enabled=True, search_count=999)
        enough = points_forecast(BASIC_CARD_TASK_IDS, search_enabled=True, search_count=30)
        self.assertEqual(capped["daily"]["high"], enough["daily"]["high"])
        self.assertEqual(capped["daily"]["high"], 278 + 90)

    def test_only_selected_cards_contribute_to_totals(self) -> None:
        forecast = points_forecast(["daily_quiz"], search_enabled=False)
        self.assertEqual(forecast["daily"], {"low": 10, "high": 50, "mid": 30})
        self.assertEqual(forecast["weekly"], {"low": 70, "high": 350, "mid": 210})
        self.assertNotIn("daily_quiz", forecast["missing_ids"])
        self.assertEqual(forecast["missing_count"], 11)

    def test_weekly_and_monthly_are_amortized_into_daily_estimate(self) -> None:
        weekly_only = points_forecast(["weekly_set"])
        self.assertEqual(weekly_only["daily"]["low"], 7)
        self.assertEqual(weekly_only["daily"]["high"], 21)
        self.assertEqual(weekly_only["weekly"]["low"], 50)
        self.assertEqual(weekly_only["weekly"]["high"], 150)

        monthly_only = points_forecast(["monthly_set"])
        self.assertEqual(monthly_only["daily"]["low"], 3)
        self.assertEqual(monthly_only["daily"]["high"], 17)
        self.assertEqual(monthly_only["weekly"]["low"], 23)
        self.assertEqual(monthly_only["weekly"]["high"], 117)

    def test_empty_selection_returns_zero_and_lists_every_option(self) -> None:
        forecast = points_forecast(
            [], search_enabled=False, search_count=20, auto_claim=False
        )
        self.assertEqual(forecast["daily"], {"low": 0, "high": 0, "mid": 0})
        self.assertEqual(forecast["weekly"], {"low": 0, "high": 0, "mid": 0})
        self.assertEqual(forecast["selected_count"], 0)
        self.assertEqual(forecast["missing_count"], 12)
        self.assertIn("web_search", forecast["missing_ids"])
        self.assertEqual(forecast["missing_daily"]["low"], 65)
        self.assertEqual(forecast["missing_daily"]["high"], 278 + 60)
        self.assertFalse(forecast["auto_claim"])


class TaskConfigTests(unittest.TestCase):
    def _load(self, basic: str):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                '[general]\n[basic]\n' + basic + "\n", encoding="utf-8"
            )
            return load_config(path)

    def test_task_types_roundtrip(self) -> None:
        cfg = self._load('task_types = ["daily_quiz", "more_poll"]')
        self.assertEqual(cfg.basic.task_types, ["daily_quiz", "more_poll"])

    def test_missing_task_types_uses_defaults(self) -> None:
        cfg = self._load("max_tasks = 3")
        self.assertEqual(cfg.basic.task_types, list(DEFAULT_TASK_TYPES))

    def test_empty_task_types_is_allowed(self) -> None:
        cfg = self._load("task_types = []")
        self.assertEqual(cfg.basic.task_types, [])

    def test_unknown_or_ai_task_type_is_rejected(self) -> None:
        with self.assertRaises(ConfigError):
            self._load('task_types = ["daily_quiz", "mystery"]')
        with self.assertRaises(ConfigError):
            self._load('task_types = ["survey"]')

    def test_example_config_has_catalog_defaults(self) -> None:
        cfg = load_config(PROJECT_ROOT / "config.example.toml")
        self.assertEqual(cfg.basic.task_types, list(DEFAULT_TASK_TYPES))


if __name__ == "__main__":
    unittest.main()
