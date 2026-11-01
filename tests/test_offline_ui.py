from __future__ import annotations

import unittest

from playwright.sync_api import sync_playwright

from rewards_bot.basic import (
    MARK_ANSWER_JS,
    MARK_CLAIMS_JS,
    MARK_PROGRESS_JS,
    QUIZ_DETECT_JS,
    SCAN_TASKS_JS,
)


class OfflineUITests(unittest.TestCase):
    """用本地 HTML 固定样例验证浏览器脚本，不访问线上账户。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls._pw = sync_playwright().start()
        try:
            cls._browser = cls._pw.chromium.launch(channel="msedge", headless=True)
        except Exception as exc:  # 没有 Edge 的环境跳过，而不是让测试失败
            cls._pw.stop()
            raise unittest.SkipTest(f"无法启动 Edge 进行离线 UI 测试：{exc}") from exc
        cls._context = cls._browser.new_context(locale="zh-CN")
        cls.page = cls._context.new_page()

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls._browser.close()
        finally:
            cls._pw.stop()

    def _load(self, body: str) -> None:
        self.page.set_content(
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<style>body{font:16px sans-serif} button,a{display:inline-block;padding:12px}"
            "mee-card{display:block;padding:8px}</style></head>"
            f"<body>{body}</body></html>"
        )

    def test_quiz_detected_with_radios(self) -> None:
        self._load(
            "<div class='quiz'><p>每日测验</p>"
            "<label><input type='radio' name='q' id='rOption0'> 选项 A</label>"
            "<label><input type='radio' name='q' id='rOption1'> 选项 B</label>"
            "<label><input type='radio' name='q' id='rOption2'> 选项 C</label></div>"
        )
        self.assertTrue(self.page.evaluate(QUIZ_DETECT_JS))

    def test_quiz_detected_with_role_radio(self) -> None:
        self._load(
            "<div role='radiogroup'>"
            "<div role='radio' aria-checked='false'>选项 A</div>"
            "<div role='radio' aria-checked='false'>选项 B</div></div>"
        )
        self.assertTrue(self.page.evaluate(QUIZ_DETECT_JS))

    def test_dashboard_carousel_is_not_quiz(self) -> None:
        # 线上仪表盘有 role=radiogroup 的轮播控件，不应被误判成测验。
        self._load(
            "<main><div role='radiogroup' aria-label='活动轮播'>"
            "<button aria-label='上一张'>‹</button>"
            "<button aria-label='下一张'>›</button>"
            "<button aria-label='第 1 页'>1</button>"
            "<button aria-label='第 2 页'>2</button></div>"
            "<button>领取 145</button></main>"
        )
        self.assertFalse(self.page.evaluate(QUIZ_DETECT_JS))

    def test_task_scan_keeps_only_real_task_links(self) -> None:
        self._load(
            "<mee-rewards-daily-set-section><mee-card>"
            "<a href='https://cn.bing.com/search?q=harbour&form=rw'>"
            "<span>+10</span> 悉尼阳光海港温暖</a>"
            "</mee-card></mee-rewards-daily-set-section>"
            "<button>领取 145 积分</button>"
            "<mee-card><a href='https://rewards.bing.com/redeem/123'>兑换奖励 +50</a></mee-card>"
            "<mee-card><a href='https://www.bing.com/search?q=done'>每日任务 +10 已完成</a></mee-card>"
            "<mee-card><a href='https://www.bing.com/search?q=more'>了解更多</a></mee-card>"
            "<nav><a href='https://www.bing.com/search?q=nav'>每日任务 +10</a></nav>"
        )
        tasks = self.page.evaluate(SCAN_TASKS_JS)
        self.assertEqual(len(tasks), 1, tasks)
        self.assertIn("cn.bing.com/search", tasks[0]["href"])
        self.assertIn("海港", tasks[0]["own_text"])
        self.assertEqual(tasks[0]["section"], "daily")

    def test_claim_scanner_ignores_redeem(self) -> None:
        self._load(
            "<button>可领取 145 领取</button>"
            "<button>领取奖励</button>"
            "<button>兑换奖励</button>"
            "<button>Redeem now</button>"
        )
        claims = self.page.evaluate(MARK_CLAIMS_JS)
        texts = [item["text"] for item in claims]
        self.assertIn("可领取 145 领取", texts)
        self.assertIn("领取奖励", texts)
        self.assertNotIn("兑换奖励", texts)
        self.assertNotIn("Redeem now", texts)

    def test_progress_ignores_bing_pagination(self) -> None:
        self._load(
            "<div id='b_results'><a href='https://www.bing.com/search?q=x&first=11'>下一页</a></div>"
            "<div class='quiz'><button>下一页</button></div>"
        )
        text = self.page.evaluate(MARK_PROGRESS_JS)
        self.assertEqual(text, "下一页")
        in_results = self.page.evaluate(
            "() => { const el = document.querySelector('[data-qbot-progress=\"1\"]');"
            " return !!(el && el.closest('#b_results')); }"
        )
        self.assertFalse(in_results)

    def test_invisible_radio_uses_label(self) -> None:
        self._load(
            "<input type='radio' name='q' id='rOption0' style='opacity:0;width:0;height:0'>"
            "<label for='rOption0'>选项 A</label>"
            "<input type='radio' name='q' id='rOption1' style='opacity:0;width:0;height:0'>"
            "<label for='rOption1'>选项 B</label>"
        )
        text = self.page.evaluate(MARK_ANSWER_JS)
        self.assertEqual(text, "选项 A")


if __name__ == "__main__":
    unittest.main()
