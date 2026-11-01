from __future__ import annotations

import unittest

from rewards_bot.agent import RewardsAgent
from rewards_bot.dom import click_block_reason, host_allowed, is_dashboard_url
from rewards_bot.llm import LLMClient, LLMError

HOSTS = ["rewards.bing.com", "bing.com", "www.bing.com", "cn.bing.com"]


class GuardTests(unittest.TestCase):
    def test_blocks_redeem_labels(self) -> None:
        for label in ["兑换", "兑换奖励", "Redeem", "Redeem now", "购买", "购买礼品卡", "设置", "退出登录"]:
            with self.subTest(label=label):
                self.assertIsNotNone(click_block_reason(label, "", HOSTS))

    def test_allows_claim_and_quiz_answers(self) -> None:
        for label in ["领取", "领取奖励", "Claim", "Claim points", "下一页", "选项 A"]:
            with self.subTest(label=label):
                self.assertIsNone(click_block_reason(label, "", HOSTS))

    def test_blocks_any_purchase_wording(self) -> None:
        # 宁可误拦测验选项，也不误点购买/兑换：含“购买”的标签一律拦截。
        self.assertIsNotNone(click_block_reason("购买力", "", HOSTS))

    def test_blocks_risky_and_external_links(self) -> None:
        self.assertIsNotNone(
            click_block_reason("查看", "https://rewards.bing.com/redeem/sku/123", HOSTS)
        )
        self.assertIsNotNone(
            click_block_reason("查看", "https://example.com/prize", HOSTS)
        )
        self.assertIsNone(
            click_block_reason("开始任务", "https://www.bing.com/search?q=quiz", HOSTS)
        )

    def test_blocks_password_input(self) -> None:
        self.assertIsNotNone(click_block_reason("", "", HOSTS, input_type="password"))

    def test_host_allowed(self) -> None:
        self.assertTrue(host_allowed("cn.bing.com", HOSTS))
        self.assertTrue(host_allowed("https://rewards.bing.com/dashboard", HOSTS))
        self.assertFalse(host_allowed("bing.com.evil.example", HOSTS))
        self.assertFalse(host_allowed("https://example.com", HOSTS))

    def test_dashboard_url(self) -> None:
        self.assertTrue(
            is_dashboard_url("https://rewards.bing.com/dashboard", "https://rewards.bing.com/dashboard")
        )
        self.assertTrue(
            is_dashboard_url("https://rewards.bing.com/dashboard?x=1", "https://rewards.bing.com/dashboard")
        )
        self.assertFalse(
            is_dashboard_url("https://rewards.bing.com/redeem", "https://rewards.bing.com/dashboard")
        )


class LLMParseTests(unittest.TestCase):
    def test_parse_plain_json(self) -> None:
        self.assertEqual(LLMClient.parse_json_object('{"action":"click","id":1}'), {"action": "click", "id": 1})

    def test_parse_fenced_json(self) -> None:
        raw = '```json\n{"action":"finish","summary":"done"}\n```'
        self.assertEqual(LLMClient.parse_json_object(raw)["action"], "finish")

    def test_parse_bad_json(self) -> None:
        with self.assertRaises(LLMError):
            LLMClient.parse_json_object("not json")


class AgentActionTests(unittest.TestCase):
    def test_normalize_click(self) -> None:
        action = RewardsAgent._normalize_action({"action": "click", "element_id": "12", "reason": "test"})
        self.assertEqual(action["id"], 12)

    def test_normalize_scroll_clamps(self) -> None:
        action = RewardsAgent._normalize_action({"action": "scroll", "dy": 999999})
        self.assertEqual(action["dy"], 3000)

    def test_normalize_wait_clamps(self) -> None:
        action = RewardsAgent._normalize_action({"action": "wait", "seconds": 999})
        self.assertEqual(action["seconds"], 10.0)

    def test_reject_unknown(self) -> None:
        with self.assertRaises(LLMError):
            RewardsAgent._normalize_action({"action": "type", "text": "password"})

    def test_finish_summary(self) -> None:
        action = RewardsAgent._normalize_action({"action": "finish", "summary": "全部完成"})
        self.assertEqual(action["action"], "finish")
        self.assertEqual(action["summary"], "全部完成")


if __name__ == "__main__":
    unittest.main()
