from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from rewards_bot.basic import BasicRunner
from rewards_bot.config import load_config


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


if __name__ == "__main__":
    unittest.main()
