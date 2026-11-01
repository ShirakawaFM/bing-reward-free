from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from rewards_bot.basic import BasicRunner
from rewards_bot.config import load_config
from rewards_bot.points import PointsTracker, read_points_summary


DASHBOARD_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>Rewards</title></head>
<body><main>
<h1>Rewards 仪表盘</h1>
<mee-rewards-daily-set-section>
  <mee-card><a href="https://cn.bing.com/search?q=daily&form=test">每日搜索任务 +10</a></mee-card>
</mee-rewards-daily-set-section>
<button>领取奖励</button>
</main></body></html>"""

SEARCH_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>搜索</title></head>
<body><main><h1>搜索结果</h1><p>这是一个打开即完成的阅读/搜索任务页面。</p></main></body></html>"""

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def dashboard_with_balance(balance: int, task_done: bool) -> str:
    """模拟带账户余额与任务徽标的 /earn 页面，余额只由本地路由控制。"""

    card = ""
    if not task_done:
        card = (
            "<mee-card><a href='https://www.bing.com/search?q=daily&form=test'>"
            "<p>+10</p><span>每日搜索任务</span></a></mee-card>"
        )
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>Rewards</title></head>"
        "<body><header role='banner'><div class='balance'>"
        f"<p>{balance:,}</p>"
        "<img alt='OMR medal' width='16' height='16' "
        "src='data:image/gif;base64,R0lGODlhAQABAAAAACw='>"
        "</div></header><main>"
        "<h1>Rewards 仪表盘</h1>"
        "<mee-rewards-daily-set-section>"
        f"{card}"
        "</mee-rewards-daily-set-section>"
        "<button>领取奖励</button>"
        "</main></body></html>"
    )



class BasicOfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._pw = sync_playwright().start()
        try:
            cls._browser = cls._pw.chromium.launch(channel="msedge", headless=True)
        except Exception as exc:
            cls._pw.stop()
            raise unittest.SkipTest(f"无法启动 Edge：{exc}") from exc

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls._browser.close()
        finally:
            cls._pw.stop()

    def test_basic_tasks_and_claim_without_live_account(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rewards-basic-test-") as tmp:
            cfg_path = Path(tmp) / "config.toml"
            cfg_path.write_text(
                f"""
[general]
url = "https://rewards.bing.com/earn"
timezone = "Asia/Shanghai"
run_at = "08:30"
mode = "basic"
headless = true
browser_channel = "msedge"
slow_mo_ms = 0
user_data_dir = "{Path(tmp).as_posix()}/profile"
state_dir = "{Path(tmp).as_posix()}/state"
log_dir = "{Path(tmp).as_posix()}/logs"
catch_up = false

[basic]
max_tasks = 2
max_rounds_per_task = 3
auto_claim = true
search_enabled = false
read_wait_seconds = 1
""",
                encoding="utf-8",
            )
            cfg = load_config(cfg_path)
            visits: list[str] = []
            blocked: list[str] = []

            context = self._browser.new_context(locale="zh-CN", timezone_id="Asia/Shanghai")
            try:
                def handle(route) -> None:
                    url = route.request.url
                    visits.append(url)
                    if url.startswith("https://rewards.bing.com/earn"):
                        route.fulfill(
                            status=200,
                            content_type="text/html; charset=utf-8",
                            body=DASHBOARD_HTML,
                        )
                    elif url.startswith("https://cn.bing.com/search"):
                        route.fulfill(
                            status=200,
                            content_type="text/html; charset=utf-8",
                            body=SEARCH_HTML,
                        )
                    else:
                        blocked.append(url)
                        route.abort()

                context.route("**/*", handle)
                page = context.new_page()
                page.goto("https://rewards.bing.com/earn")

                class FakeSession:
                    def __init__(self, page) -> None:
                        self.page = page

                    @property
                    def current_page(self):
                        return self.page

                    def open_dashboard(self):
                        self.page.goto("https://rewards.bing.com/earn")
                        return self.page

                    def is_login_page(self) -> bool:
                        return False

                    def adopt_new_pages(self) -> bool:
                        return False

                    def goto(self, url: str) -> None:
                        self.page.goto(url)

                    def click_maybe_popup(self, locator) -> None:
                        locator.scroll_into_view_if_needed(timeout=3_000)
                        locator.click(timeout=5_000)
                        self.page.wait_for_timeout(200)
                        self.page.wait_for_load_state("domcontentloaded", timeout=5_000)
                        self.page.wait_for_timeout(100)

                    def screenshot(self, name: str, full_page: bool = False):
                        return None

                runner = BasicRunner(FakeSession(page), cfg)
                processed = runner.run_daily_tasks()
                claimed = runner.claim_rewards()
            finally:
                context.close()

            self.assertEqual(processed, 1)
            self.assertEqual(claimed, 1)
            self.assertTrue(
                any(url.startswith("https://cn.bing.com/search") for url in visits),
                visits,
            )
            self.assertEqual(blocked, [])
            self.assertEqual(
                [url for url in visits if url.startswith("https://rewards.bing.com")][0],
                "https://rewards.bing.com/earn",
            )
            self.assertEqual(
                (urlparse(visits[-1]).hostname or ""), "rewards.bing.com"
            )

    def test_task_points_evidence_requires_real_readings_and_shots(self) -> None:
        """余额由本地伪造页面实时变化，验证证据链、结算与日志，不接触真实账户。"""

        with tempfile.TemporaryDirectory(prefix="rewards-points-basic-") as tmp:
            cfg_path = Path(tmp) / "config.toml"
            cfg_path.write_text(
                f"""
[general]
url = "https://rewards.bing.com/earn"
timezone = "Asia/Shanghai"
run_at = "08:30"
mode = "basic"
headless = true
browser_channel = "msedge"
slow_mo_ms = 0
user_data_dir = "{Path(tmp).as_posix()}/profile"
state_dir = "{Path(tmp).as_posix()}/state"
log_dir = "{Path(tmp).as_posix()}/logs"
catch_up = false

[basic]
max_tasks = 2
max_rounds_per_task = 1
auto_claim = true
search_enabled = false
read_wait_seconds = 1
""",
                encoding="utf-8",
            )
            cfg = load_config(cfg_path)
            state = {"balance": 1000, "done": False}
            visits: list[str] = []
            blocked: list[str] = []
            artifacts_dir = (
                cfg.general.state_dir / "screenshots" / "20261101-120000"
            )

            context = self._browser.new_context(
                locale="zh-CN", timezone_id="Asia/Shanghai"
            )
            try:

                def handle(route) -> None:
                    url = route.request.url
                    visits.append(url)
                    if url.startswith("https://rewards.bing.com/earn"):
                        route.fulfill(
                            status=200,
                            content_type="text/html; charset=utf-8",
                            body=dashboard_with_balance(
                                state["balance"], state["done"]
                            ),
                        )
                    elif url.startswith("https://www.bing.com/search"):
                        # 模拟打开任务页后真实获得 +10 分。
                        state["balance"] += 10
                        state["done"] = True
                        route.fulfill(
                            status=200,
                            content_type="text/html; charset=utf-8",
                            body=SEARCH_HTML,
                        )
                    else:
                        blocked.append(url)
                        route.abort()

                context.route("**/*", handle)
                page = context.new_page()
                page.goto("https://rewards.bing.com/earn")

                class FakeSession:
                    def __init__(self, page, artifacts: Path) -> None:
                        self.page = page
                        self.artifacts_dir = artifacts

                    @property
                    def current_page(self):
                        return self.page

                    def open_dashboard(self):
                        self.page.goto("https://rewards.bing.com/earn")
                        return self.page

                    def is_login_page(self) -> bool:
                        return False

                    def adopt_new_pages(self) -> bool:
                        return False

                    def goto(self, url: str) -> None:
                        self.page.goto(url)

                    def click_maybe_popup(self, locator) -> None:
                        locator.scroll_into_view_if_needed(timeout=3_000)
                        locator.click(timeout=5_000)
                        self.page.wait_for_timeout(200)
                        self.page.wait_for_load_state(
                            "domcontentloaded", timeout=5_000
                        )
                        self.page.wait_for_timeout(100)

                    def screenshot(self, name: str, full_page: bool = False):
                        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
                        path = self.artifacts_dir / f"{name}.png"
                        path.write_bytes(PNG_1X1)
                        return path

                session = FakeSession(page, artifacts_dir)
                tracker = PointsTracker(session, cfg)
                runner = BasicRunner(session, cfg, points=tracker)
                with self.assertLogs("rewards_bot.points", level="INFO") as captured:
                    tracker.begin_run()
                    processed = runner.run_daily_tasks()
                    claimed = runner.claim_rewards()
                    tracker.finish_run()
            finally:
                context.close()

            self.assertEqual(processed, 1)
            self.assertEqual(claimed, 1)
            self.assertEqual(blocked, [])

            summary = read_points_summary(
                cfg.general.state_dir, cfg.general.timezone
            )
            self.assertTrue(summary["available"], summary)
            self.assertEqual(summary["today_confirmed"], 10)
            self.assertEqual(summary["today_confirmed_tasks"], 1)
            self.assertEqual(summary["today_unconfirmed_tasks"], 0)
            self.assertEqual(summary["today_net"], 10)
            self.assertIsNotNone(summary["balance"], summary)
            self.assertEqual(summary["balance"]["points"], 1010)
            self.assertIsNotNone(summary["remaining"], summary)
            self.assertEqual(summary["remaining"]["points"], 0)

            last = summary["last_run"]
            self.assertIsNotNone(last, summary)
            self.assertEqual(last["before"], 1000)
            self.assertEqual(last["after"], 1010)
            self.assertEqual(last["delta"], 10)
            self.assertEqual(last["status"], "confirmed")
            self.assertEqual(last["confirmed"], 10)
            self.assertEqual(len(last["tasks"]), 1)
            task = last["tasks"][0]
            self.assertEqual(task["status"], "confirmed")
            self.assertEqual(task["before"], 1000)
            self.assertEqual(task["after"], 1010)
            self.assertEqual(task["delta"], 10)
            self.assertIsNotNone(task["before_shot"])
            self.assertIsNotNone(task["after_shot"])

            for name in (
                "points-run-start",
                "points-task-01-before",
                "points-task-01-after",
                "points-run-end",
            ):
                self.assertTrue(
                    (artifacts_dir / f"{name}.png").is_file(), name
                )

            logs = "\n".join(captured.output)
            self.assertIn("任务积分实测：+10 分", logs)
            self.assertIn("本次运行积分结算", logs)


if __name__ == "__main__":
    unittest.main()
