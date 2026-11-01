from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from rewards_bot.points import (
    PointsLedger,
    evaluate_task_evidence,
    normalize_snapshot,
)


def make_snapshot(points: int, remaining: int | None = None) -> dict:
    raw = {
        "balance": {"value": points, "raw": f"{points:,}", "source": "page_header"},
        "remaining": None,
    }
    if remaining is not None:
        raw["remaining"] = {
            "points": remaining,
            "task_count": 2,
            "sections": {"daily": remaining},
            "source": "visible_task_cards",
        }
    return normalize_snapshot(raw)


class EvidenceTests(unittest.TestCase):
    def test_confirmed_only_with_both_shots_and_positive_delta(self) -> None:
        result = evaluate_task_evidence(
            make_snapshot(1234),
            make_snapshot(1284),
            {"run": "run-1", "name": "points-task-01-before.png"},
            {"run": "run-1", "name": "points-task-01-after.png"},
        )
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["delta"], 50)
        self.assertEqual(result["before"], 1234)
        self.assertEqual(result["after"], 1284)

    def test_positive_delta_without_screenshots_is_not_confirmed(self) -> None:
        result = evaluate_task_evidence(
            make_snapshot(1234),
            make_snapshot(1284),
            None,
            {"run": "run-1", "name": "points-task-01-after.png"},
        )
        self.assertEqual(result["status"], "missing_screenshot")
        self.assertEqual(result["delta"], 50)
        self.assertFalse(result["has_shots"])

    def test_missing_balance_is_not_confirmed(self) -> None:
        result = evaluate_task_evidence(
            make_snapshot(1234),
            normalize_snapshot(None),
            {"run": "run-1", "name": "points-task-01-before.png"},
            {"run": "run-1", "name": "points-task-01-after.png"},
        )
        self.assertEqual(result["status"], "missing_balance")
        self.assertIsNone(result["delta"])

    def test_decrease_is_not_counted_as_earned(self) -> None:
        result = evaluate_task_evidence(
            make_snapshot(1300),
            make_snapshot(1250),
            {"run": "run-1", "name": "points-task-01-before.png"},
            {"run": "run-1", "name": "points-task-01-after.png"},
        )
        self.assertEqual(result["status"], "decreased")
        self.assertEqual(result["delta"], -50)

    def test_normalize_snapshot_rejects_invalid_values(self) -> None:
        snapshot = normalize_snapshot(
            {
                "balance": {"value": "not-a-number"},
                "remaining": {"points": -5, "task_count": "many", "sections": {}},
            }
        )
        self.assertIsNone(snapshot["balance"])
        self.assertIsNone(snapshot["remaining"])


class LedgerTests(unittest.TestCase):
    def test_summary_uses_real_readings_and_builds_evidence_urls(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rewards-points-test-") as tmp:
            state_dir = Path(tmp)
            ledger = PointsLedger(state_dir, "Asia/Shanghai")
            today = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")

            start = make_snapshot(1234, remaining=250)
            start["at"] = today
            start["shot"] = {"run": "20261101-083000", "name": "points-run-start.png"}
            ledger.record_reading("run_start", start, "20261101-083000")

            ledger.record_task(
                {
                    "at": today,
                    "run_id": "20261101-083000",
                    "index": 1,
                    "label": "每日测验",
                    "status": "confirmed",
                    "before": 1234,
                    "after": 1284,
                    "delta": 50,
                    "note": "",
                    "before_shot": {
                        "run": "20261101-083000",
                        "name": "points-task-01-before.png",
                    },
                    "after_shot": {
                        "run": "20261101-083000",
                        "name": "points-task-01-after.png",
                    },
                }
            )
            ledger.record_task(
                {
                    "at": today,
                    "run_id": "20261101-083000",
                    "index": 2,
                    "label": "阅读任务",
                    "status": "unchanged",
                    "before": 1284,
                    "after": 1284,
                    "delta": 0,
                    "note": "任务期间余额未变化",
                    "before_shot": {
                        "run": "20261101-083000",
                        "name": "points-task-02-before.png",
                    },
                    "after_shot": {
                        "run": "20261101-083000",
                        "name": "points-task-02-after.png",
                    },
                }
            )

            end = make_snapshot(1300, remaining=120)
            end["at"] = today
            end["shot"] = {"run": "20261101-083000", "name": "points-run-end.png"}
            ledger.record_reading("run_end", end, "20261101-083000")
            ledger.record_run(
                {
                    "id": "20261101-083000",
                    "started_at": today,
                    "finished_at": today,
                    "mode": "basic",
                    "before": 1234,
                    "after": 1300,
                    "delta": 66,
                    "confirmed": 50,
                    "unconfirmed": 1,
                    "status": "confirmed",
                    "start_shot": {
                        "run": "20261101-083000",
                        "name": "points-run-start.png",
                    },
                    "end_shot": {
                        "run": "20261101-083000",
                        "name": "points-run-end.png",
                    },
                    "tasks": [],
                }
            )

            summary = ledger.summary()
            self.assertTrue(summary["available"])
            self.assertEqual(summary["today_confirmed"], 50)
            self.assertEqual(summary["today_confirmed_tasks"], 1)
            self.assertEqual(summary["today_unconfirmed_tasks"], 1)
            self.assertEqual(summary["balance"]["points"], 1300)
            self.assertEqual(summary["remaining"]["points"], 120)
            self.assertEqual(summary["today_net"], 66)
            self.assertEqual(
                summary["balance"]["shot"]["url"],
                "/api/screenshots/20261101-083000/points-run-end.png",
            )
            last = summary["last_run"]
            self.assertEqual(last["delta"], 66)
            self.assertEqual(last["confirmed"], 50)
            self.assertEqual(
                last["start_shot"]["url"],
                "/api/screenshots/20261101-083000/points-run-start.png",
            )

    def test_corrupt_ledger_degrades_to_empty_summary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rewards-points-test-") as tmp:
            state_dir = Path(tmp)
            path = state_dir / "points" / "ledger.json"
            path.parent.mkdir(parents=True)
            path.write_text("{not-json", encoding="utf-8")
            summary = PointsLedger(state_dir, "Asia/Shanghai").summary()
            self.assertFalse(summary["available"])
            self.assertEqual(summary["today_confirmed"], 0)
            self.assertIsNone(summary["balance"])


if __name__ == "__main__":
    unittest.main()
