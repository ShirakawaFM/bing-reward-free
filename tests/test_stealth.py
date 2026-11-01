from __future__ import annotations

import json
import logging
import random
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from rewards_bot.config import (
    AppConfig,
    ConfigError,
    StealthConfig,
    load_config,
)
from rewards_bot.stealth import (
    SearchBeat,
    StrongPlanner,
    _beats_from_payload,
    describe_modes,
    heuristic_plan,
    jitter_query,
    sample_delay,
    sample_span,
)


def make_config(root: Path, extra: str = "", api_key: str = "", base_url: str = "https://api.deepseek.com") -> AppConfig:
    """在临时目录里生成一份最小配置，避免依赖用户真实 config.toml。"""

    text = f"""[general]
url = "https://rewards.bing.com/earn"
timezone = "Asia/Shanghai"
run_at = "08:30"
mode = "basic"
headless = true
state_dir = "state"
log_dir = "logs"

[basic]
search_enabled = true
search_count = 5
search_delay_min = 6
search_delay_max = 12
search_host = "https://www.bing.com"

[advanced]
api_key = "{api_key}"
base_url = "{base_url}"
model = "deepseek-chat"

{extra}
"""
    path = root / "config.toml"
    path.write_text(text, encoding="utf-8")
    return load_config(path)


class QueryJitterTests(unittest.TestCase):
    def test_always_changes_query(self) -> None:
        rng = random.Random(20261101)
        samples = [
            "人工智能 最新进展",
            "Python 入门教程",
            "Windows 使用技巧",
            "Excel 函数 技巧",
            "咖啡 怎么冲泡",
            "abc",
            "科技",
        ]
        for query in samples:
            for _ in range(30):
                mutated, edits = jitter_query(query, rng, 2)
                self.assertNotEqual(mutated, query, f"{query!r} 没有被偏移")
                self.assertGreaterEqual(edits, 1)
                self.assertLessEqual(edits, 2)
                # 语义相近：长度变化不超过 2 个字符（只允许插空格/重复一个字符）。
                self.assertLessEqual(abs(len(mutated) - len(query)), 2)

    def test_respects_max_edits_and_empty_input(self) -> None:
        rng = random.Random(7)
        for _ in range(20):
            mutated, edits = jitter_query("健康饮食 建议", rng, 1)
            self.assertNotEqual(mutated, "健康饮食 建议")
            self.assertGreaterEqual(edits, 1)
            self.assertLessEqual(edits, 1)
        self.assertEqual(jitter_query("", rng, 2), ("", 0))

    def test_jitter_is_reproducible_with_same_seed(self) -> None:
        first = [jitter_query("人工智能 最新进展", random.Random(i), 2) for i in range(5)]
        second = [jitter_query("人工智能 最新进展", random.Random(i), 2) for i in range(5)]
        self.assertEqual(first, second)


class RhythmTests(unittest.TestCase):
    def test_sample_span_bounds_and_variation(self) -> None:
        rng = random.Random(11)
        values = [sample_span(rng, 6.0, 12.0) for _ in range(200)]
        self.assertTrue(all(6.0 <= value <= 12.0 for value in values))
        self.assertGreater(len({round(value, 3) for value in values}), 100)
        # 右偏分布：平均值应明显低于区间中点。
        mean = sum(values) / len(values)
        self.assertLess(mean, 9.0)

    def test_break_is_capped(self) -> None:
        rng = random.Random(3)
        values = [sample_delay(rng, 6.0, 12.0, 1.0) for _ in range(60)]
        self.assertTrue(all(value <= 12.0 * 2.2 + 1e-6 for value in values))
        self.assertTrue(any(value > 12.0 for value in values))


class PlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.cfg = make_config(self.root)
        self.rng = random.Random(42)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_heuristic_plan_shape(self) -> None:
        beats = heuristic_plan(
            ["人工智能 最新进展", "Windows 使用技巧"], 4, self.cfg, self.rng
        )
        self.assertEqual(len(beats), 4)
        for beat in beats:
            self.assertTrue(beat.query.strip())
            self.assertGreaterEqual(beat.dwell, self.cfg.basic.search_delay_min)
            self.assertLessEqual(
                beat.dwell, self.cfg.basic.search_delay_max * 2.2 + 1e-6
            )
            self.assertIn(beat.scroll, (0, 1, 2, 3, 4))
            self.assertIn(beat.hover, (0, 1, 2))
            self.assertIsInstance(beat.click, bool)

    def test_beats_payload_is_sanitized(self) -> None:
        payload = [
            {"q": "人工智能最新进展", "dwell": 999, "scroll": 99, "hover": -3, "click": "true"},
            {"q": "人工智能最新进展", "dwell": 7},  # 重复，应被去掉
            {"q": "", "dwell": 5},  # 空查询
            {"q": "x" * 200, "dwell": 5},  # 过长
            {"q": "Python 入门教程", "dwell": "abc", "scroll": "x", "click": False},
        ]
        beats = _beats_from_payload(payload, source="llm")
        self.assertEqual([beat.query for beat in beats], ["人工智能最新进展", "Python 入门教程"])
        self.assertEqual(beats[0].dwell, 60.0)  # 上限收敛
        self.assertEqual(beats[0].scroll, 5)
        self.assertEqual(beats[0].hover, 0)
        self.assertTrue(beats[0].click)
        self.assertEqual(beats[1].dwell, 8.0)  # 非法值回落默认
        self.assertEqual(beats[1].scroll, 2)

    def test_strong_planner_falls_back_without_api_key(self) -> None:
        planner = StrongPlanner(self.cfg, logging.getLogger("test.stealth"), self.rng)
        beats, report = planner.plan(3, ["人工智能 最新进展"])
        self.assertEqual(len(beats), 3)
        self.assertEqual(report.source, "heuristic")
        self.assertFalse(report.cached)
        self.assertTrue(any("降级" in note for note in report.notes))

    def test_cache_round_trip_and_expiry(self) -> None:
        planner = StrongPlanner(self.cfg, logging.getLogger("test.stealth"), self.rng)
        beats = heuristic_plan(["人工智能 最新进展"], 2, self.cfg, self.rng, source="llm")
        key = planner._cache_key(2, ["人工智能 最新进展"])
        planner._write_cache(key, beats, {"total_tokens": 123})
        cached = planner._read_cache(key)
        self.assertIsNotNone(cached)
        assert cached is not None
        self.assertEqual(len(cached), 2)
        self.assertEqual(cached[0].source, "llm-cache")

        # 把创建时间改成过期，再读应当落空。
        data = json.loads(planner.cache_path.read_text(encoding="utf-8"))
        stale = (datetime.now() - timedelta(hours=48)).isoformat(timespec="seconds")
        data["entries"][key]["created_at"] = stale
        planner.cache_path.write_text(json.dumps(data), encoding="utf-8")
        self.assertIsNone(planner._read_cache(key))

    def test_refresh_keeps_beat_shape_but_changes_timing(self) -> None:
        from rewards_bot.stealth import _refresh_beats

        original = [
            SearchBeat(query="人工智能 最新进展", dwell=9.0, scroll=2, hover=1, click=False)
            for _ in range(3)
        ]
        refreshed = _refresh_beats(original, self.cfg, self.rng)
        self.assertEqual(len(refreshed), 3)
        self.assertTrue(any(abs(item.dwell - 9.0) > 1e-6 for item in refreshed))
        for item in refreshed:
            self.assertEqual(item.scroll, 2)
            self.assertEqual(item.hover, 1)
            self.assertNotEqual(item.query, "人工智能 最新进展")


class ConfigTests(unittest.TestCase):
    def test_defaults_when_section_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(Path(tmp))
        self.assertTrue(cfg.stealth.basic_enabled)
        self.assertFalse(cfg.stealth.strong_enabled)
        self.assertEqual(cfg.stealth.query_jitter, 2)
        self.assertTrue(cfg.stealth.enabled)

    def test_parses_explicit_section(self) -> None:
        extra = """[stealth]
basic_enabled = false
strong_enabled = true
query_jitter = 3
typing_enabled = false
break_probability = 0.3
click_result_probability = 0.4
plan_max_tokens = 900
plan_cache_hours = 6
"""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(Path(tmp), extra)
        self.assertFalse(cfg.stealth.basic_enabled)
        self.assertTrue(cfg.stealth.strong_enabled)
        self.assertEqual(cfg.stealth.query_jitter, 3)
        self.assertFalse(cfg.stealth.typing_enabled)
        self.assertAlmostEqual(cfg.stealth.plan_cache_hours, 6.0)
        self.assertEqual(describe_modes(cfg.stealth), "强力防检测（大模型规划 + 本地抖动）")

    def test_rejects_out_of_range_values(self) -> None:
        cases = (
            "[stealth]\nquery_jitter = 0\n",
            "[stealth]\nbreak_probability = 1.5\n",
            "[stealth]\nclick_result_probability = 2\n",
            "[stealth]\nplan_cache_hours = 9999\n",
        )
        for extra in cases:
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(ConfigError):
                    make_config(Path(tmp), extra)

    def test_describe_modes_for_each_state(self) -> None:
        self.assertIn("基础", describe_modes(StealthConfig()))
        self.assertIn("强力", describe_modes(StealthConfig(strong_enabled=True)))
        self.assertEqual(
            describe_modes(StealthConfig(basic_enabled=False, strong_enabled=False)),
            "关闭",
        )


class SearchRunnerBrowserTests(unittest.TestCase):
    """用真实浏览器验证“人类化输入/悬停”确实作用在页面上（离线，不联网）。"""

    @classmethod
    def setUpClass(cls) -> None:
        from playwright.sync_api import sync_playwright

        cls._pw = sync_playwright().start()
        try:
            cls._browser = cls._pw.chromium.launch(channel="msedge", headless=True)
        except Exception as exc:  # pragma: no cover - 无 Edge 环境自动跳过
            cls._pw.stop()
            raise unittest.SkipTest(f"无法启动 Edge：{exc}") from exc

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls._browser.close()
        finally:
            cls._pw.stop()

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.cfg = make_config(Path(self._tmp.name))
        self.page = self._browser.new_page()

    def tearDown(self) -> None:
        try:
            self.page.close()
        finally:
            self._tmp.cleanup()

    def test_type_query_fills_search_box(self) -> None:
        from rewards_bot.stealth import SearchRunner

        self.page.set_content(
            "<html><body><form>"
            "<input id='sb_form_q' style='width:420px;height:40px'>"
            "</form></body></html>"
        )
        runner = SearchRunner(None, self.cfg)  # type: ignore[arg-type]
        self.assertTrue(runner._type_query(self.page, "人工智能 入门"))
        self.assertEqual(self.page.input_value("#sb_form_q"), "人工智能 入门")

    def test_type_query_returns_false_without_box(self) -> None:
        from rewards_bot.stealth import SearchRunner

        self.page.set_content("<html><body><p>没有搜索框</p></body></html>")
        runner = SearchRunner(None, self.cfg)  # type: ignore[arg-type]
        self.assertFalse(runner._type_query(self.page, "测试"))

    def test_hover_result_moves_mouse_without_error(self) -> None:
        from rewards_bot.stealth import SearchRunner

        self.page.set_content(
            "<html><body><ul id='b_results'>"
            "<li class='b_algo'><h2><a href='https://example.com/a'>第一条结果</a></h2></li>"
            "<li class='b_algo'><h2><a href='https://example.com/b'>第二条结果</a></h2></li>"
            "</ul></body></html>"
        )
        runner = SearchRunner(None, self.cfg)  # type: ignore[arg-type]
        runner._hover_result(self.page)
        self.assertIsNotNone(runner._result_locator(self.page))


class StrongPlannerLLMTests(unittest.TestCase):
    """用本地 HTTP 假接口验证“强力防检测”的整轮一次调用 + 缓存复用。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls._server, cls._port, cls._calls = _start_fake_llm()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._server.shutdown()
        cls._server.server_close()

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.cfg = make_config(
            self.root,
            api_key="test-key",
            base_url=f"http://127.0.0.1:{self._port}/v1",
        )
        self.cfg.stealth.strong_enabled = True
        self.log = logging.getLogger("test.stealth.llm")
        _reset_fake_llm(self._calls)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_plan_uses_one_call_and_reuses_cache(self) -> None:
        from rewards_bot.stealth import StrongPlanner

        planner = StrongPlanner(self.cfg, self.log, random.Random(5))
        beats, report = planner.plan(3, ["人工智能 最新进展", "Windows 使用技巧"])
        self.assertEqual(report.source, "llm")
        self.assertEqual(report.total_tokens, 120)
        self.assertEqual(len(beats), 3)
        self.assertEqual(_calls_count(self._calls), 1)
        self.assertTrue(planner.cache_path.exists())

        # 第二次同参数规划：命中缓存，不再请求模型。
        beats2, report2 = StrongPlanner(self.cfg, self.log, random.Random(6)).plan(
            3, ["人工智能 最新进展", "Windows 使用技巧"]
        )
        self.assertEqual(report2.source, "llm-cache")
        self.assertTrue(report2.cached)
        self.assertEqual(report2.total_tokens, 0)
        self.assertEqual(_calls_count(self._calls), 1)
        self.assertEqual(len(beats2), 3)
        # 缓存命中后仍然会重新采样时间线。
        self.assertNotEqual(
            [round(beat.dwell, 3) for beat in beats],
            [round(beat.dwell, 3) for beat in beats2],
        )

    def test_bad_model_output_falls_back(self) -> None:
        from rewards_bot.stealth import StrongPlanner

        _set_fake_llm_mode(self._calls, "garbage")
        try:
            planner = StrongPlanner(self.cfg, self.log, random.Random(5))
            beats, report = planner.plan(2, ["人工智能 最新进展"])
        finally:
            _set_fake_llm_mode(self._calls, "ok")
        self.assertEqual(report.source, "heuristic")
        self.assertEqual(len(beats), 2)
        self.assertTrue(any("降级" in note for note in report.notes))


# --- 假 LLM 服务 ---


def _start_fake_llm():
    import http.server
    import threading

    state = {"calls": 0, "mode": "ok"}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - 标准库回调名
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            state["calls"] += 1
            if state["mode"] == "garbage":
                content = "这不是 JSON"
            else:
                content = json.dumps(
                    {
                        "pace": 0.9,
                        "beats": [
                            {"q": "人工智能最新进展", "dwell": 7.4, "scroll": 2, "hover": 1, "click": False},
                            {"q": "Windows 使用技巧", "dwell": 9.1, "scroll": 1, "hover": 0, "click": False},
                            {"q": "人工智能 新进展", "dwell": 12.5, "scroll": 3, "hover": 2, "click": False},
                        ],
                    },
                    ensure_ascii=False,
                )
            body = json.dumps(
                {
                    "choices": [{"message": {"content": content}}],
                    "usage": {"prompt_tokens": 80, "completion_tokens": 40, "total_tokens": 120},
                },
                ensure_ascii=False,
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # 静默
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, port, state


def _calls_count(state) -> int:
    return int(state["calls"])


def _reset_fake_llm(state) -> None:
    state["calls"] = 0
    state["mode"] = "ok"


def _set_fake_llm_mode(state, mode: str) -> None:
    state["mode"] = mode


class SearchRunnerFlowTests(unittest.TestCase):
    """整轮搜索流程（首页 → 输入 → 结果页 → 停留/滚动）在假站点上跑通。"""

    HOME_HTML = (
        "<!doctype html><html><head><meta charset='utf-8'><title>Bing</title></head><body>"
        "<form action='/search' method='get'>"
        "<input id='sb_form_q' name='q' style='width:420px;height:40px'>"
        "</form></body></html>"
    )
    RESULTS_HTML = (
        "<!doctype html><html><head><meta charset='utf-8'><title>搜索结果</title></head><body>"
        "<ul id='b_results'>"
        "<li class='b_algo'><h2><a href='https://example.com/a'>第一条结果</a></h2></li>"
        "<li class='b_algo'><h2><a href='https://example.com/b'>第二条结果</a></h2></li>"
        "</ul><div style='height:3000px'></div></body></html>"
    )

    @classmethod
    def setUpClass(cls) -> None:
        from playwright.sync_api import sync_playwright

        cls._pw = sync_playwright().start()
        try:
            cls._browser = cls._pw.chromium.launch(channel="msedge", headless=True)
        except Exception as exc:  # pragma: no cover
            cls._pw.stop()
            raise unittest.SkipTest(f"无法启动 Edge：{exc}") from exc

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls._browser.close()
        finally:
            cls._pw.stop()

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.cfg = make_config(
            root,
            extra="""[stealth]
basic_enabled = true
strong_enabled = false
typing_enabled = true
mouse_jitter = true
click_result_probability = 0
break_probability = 0
""",
        )
        # 把节奏压到亚秒级，测试才跑得动；分布逻辑本身由单元测试覆盖。
        self.cfg.basic.search_delay_min = 0.3
        self.cfg.basic.search_delay_max = 0.6
        self.visited: list[str] = []
        self.context = self._browser.new_context(viewport={"width": 1280, "height": 800})
        self.context.route("**/*", self._handle_route)
        self.page = self.context.new_page()

    def tearDown(self) -> None:
        try:
            self.context.close()
        finally:
            self._tmp.cleanup()

    def _handle_route(self, route) -> None:
        url = route.request.url
        self.visited.append(url)
        body = self.RESULTS_HTML if "/search" in url else self.HOME_HTML
        route.fulfill(status=200, body=body, content_type="text/html; charset=utf-8")

    def test_full_search_round_trip_uses_jittered_queries(self) -> None:
        from rewards_bot.stealth import SearchRunner

        session = _FakeSession(self.page)
        runner = SearchRunner(session, self.cfg)  # type: ignore[arg-type]
        completed = runner.run(2, ["人工智能 入门", "Windows 使用技巧"])
        self.assertEqual(completed, 2)
        search_urls = [url for url in self.visited if "/search?" in url]
        self.assertEqual(len(search_urls), 2)
        queries = []
        for url in search_urls:
            self.assertIn("q=", url)
            raw = url.split("q=", 1)[1].split("&", 1)[0]
            from urllib.parse import unquote_plus

            queries.append(unquote_plus(raw))
        # 每次查询都经过扰动，且两次不完全相同。
        self.assertTrue(all(query for query in queries))
        self.assertEqual(len(set(queries)), 2)
        for query in queries:
            self.assertNotIn(query, ("人工智能 入门", "Windows 使用技巧"))
        # 键入路径会带上 home 页，而不是直接跳搜索结果。
        self.assertTrue(any("/search" not in url and url.endswith("/") for url in self.visited))


class _FakeSession:
    """只实现 SearchRunner 用到的那几个方法，避免真的启动浏览器会话。"""

    def __init__(self, page) -> None:
        self.page = page

    @property
    def current_page(self):
        return self.page

    def goto(self, url: str) -> None:
        self.page.goto(url, wait_until="domcontentloaded", timeout=15_000)
        self.page.wait_for_timeout(120)

    def is_login_page(self) -> bool:
        return False

    def adopt_new_pages(self) -> bool:
        return False

    def screenshot(self, name: str, full_page: bool = False):
        return None


if __name__ == "__main__":
    unittest.main()
