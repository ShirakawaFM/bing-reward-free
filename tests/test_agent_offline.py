from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

from rewards_bot.agent import RewardsAgent
from rewards_bot.config import load_config


DASHBOARD_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>Rewards</title></head>
<body><main>
<h1>Rewards 仪表盘</h1>
<mee-rewards-daily-set-section>
  <mee-card><a href="https://cn.bing.com/search?q=quiz&form=test">每日测验 +10 开始测验</a></mee-card>
</mee-rewards-daily-set-section>
<button>领取 145</button>
</main></body></html>"""

QUIZ_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>每日测验</title></head>
<body><main>
<h1>每日测验</h1>
<div class="quiz">
  <label><input type="radio" name="q" id="rOption0"> 选项 A</label>
  <label><input type="radio" name="q" id="rOption1"> 选项 B</label>
  <button>提交</button>
</div>
</main></body></html>"""


def observation_from(payload: dict) -> dict:
    prompt = payload["messages"][-1]["content"]
    for line in prompt.splitlines():
        line = line.strip()
        if line.startswith('{"step_page"'):
            return json.loads(line)
    raise AssertionError("请求中没有可解析的页面观察")


class FakeLLMServer:
    """本地 OpenAI 兼容假接口，根据观察结果返回脚本化动作。"""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.actions: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                outer.requests.append(
                    {"path": self.path, "headers": dict(self.headers), "payload": payload}
                )
                content = json.dumps(outer.next_action(payload), ensure_ascii=False)
                body = json.dumps(
                    {"choices": [{"message": {"content": content}}]}
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args) -> None:
                return

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def next_action(self, payload: dict) -> dict:
        obs = observation_from(payload)
        url = str(obs["step_page"]["url"])
        elements = obs["elements"]
        step = len(self.actions) + 1

        if step == 1:
            if "/dashboard" not in url:
                raise AssertionError(f"第一步应在仪表盘，实际：{url}")
            action = {
                "action": "click",
                "id": self._find(elements, "开始测验")["id"],
                "reason": "打开每日测验",
            }
        elif step == 2:
            if "cn.bing.com/search" not in url:
                raise AssertionError(f"第二步应在测验页，实际：{url}")
            action = {
                "action": "click",
                "id": self._find(elements, "选项 B")["id"],
                "reason": "选择 B",
            }
        elif step == 3:
            action = {
                "action": "click",
                "id": self._find(elements, "提交")["id"],
                "reason": "提交答案",
            }
        else:
            action = {"action": "finish", "summary": "脚本化测试完成"}
        self.actions.append(action)
        return action

    @staticmethod
    def _find(elements: list[dict], text: str) -> dict:
        for item in elements:
            value = " ".join(
                str(item.get(key) or "") for key in ("text", "aria", "value")
            )
            if text in value:
                return item
        raise AssertionError(f"观察结果中没有找到文字 {text!r}：{elements}")


class AgentOfflineTests(unittest.TestCase):
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

    def test_agent_navigates_dashboard_and_quiz(self) -> None:
        llm = FakeLLMServer()
        llm.start()
        try:
            with tempfile.TemporaryDirectory(prefix="rewards-agent-test-") as tmp:
                cfg_path = Path(tmp) / "config.toml"
                cfg_path.write_text(
                    f"""
[general]
url = "https://rewards.bing.com/dashboard"
timezone = "Asia/Shanghai"
run_at = "08:30"
mode = "advanced"
headless = true
browser_channel = "msedge"
slow_mo_ms = 0
user_data_dir = "{Path(tmp).as_posix()}/profile"
state_dir = "{Path(tmp).as_posix()}/state"
log_dir = "{Path(tmp).as_posix()}/logs"
catch_up = false

[basic]
search_enabled = false
auto_claim = false

[advanced]
api_key = "test-key"
base_url = "{llm.base_url}"
model = "fake-model"
vision = false
max_steps = 6
max_minutes = 2
timeout_seconds = 10
allowed_hosts = ["rewards.bing.com", "bing.com", "cn.bing.com"]
""",
                    encoding="utf-8",
                )
                cfg = load_config(cfg_path)
                state_dir = cfg.general.state_dir

                context = self._browser.new_context(
                    locale="zh-CN", timezone_id="Asia/Shanghai"
                )
                try:
                    def handle(route) -> None:
                        url = route.request.url
                        if url.startswith("https://rewards.bing.com/dashboard"):
                            route.fulfill(
                                status=200,
                                content_type="text/html; charset=utf-8",
                                body=DASHBOARD_HTML,
                            )
                        elif url.startswith("https://cn.bing.com/search"):
                            route.fulfill(
                                status=200,
                                content_type="text/html; charset=utf-8",
                                body=QUIZ_HTML,
                            )
                        else:
                            route.abort()

                    context.route("**/*", handle)
                    page = context.new_page()
                    page.goto("https://rewards.bing.com/dashboard")

                    class FakeSession:
                        """只实现 Agent 需要的会话接口，避免依赖真实浏览器的持久化配置。"""

                        def __init__(self, page, state_dir: Path) -> None:
                            self.page = page
                            self.state_dir = state_dir

                        @property
                        def current_page(self):
                            return self.page

                        def open_dashboard(self):
                            self.page.goto("https://rewards.bing.com/dashboard")
                            return self.page

                        def is_login_page(self) -> bool:
                            return False

                        def screenshot(self, name: str, full_page: bool = False):
                            path = self.state_dir / f"{name}.png"
                            path.parent.mkdir(parents=True, exist_ok=True)
                            self.page.screenshot(path=str(path), full_page=full_page)
                            return path

                        def adopt_new_pages(self) -> bool:
                            return False

                        def goto(self, url: str) -> None:
                            self.page.goto(url)

                    session = FakeSession(page, state_dir)
                    agent = RewardsAgent(session, cfg)
                    summary = agent.run()
                    final_url = page.url
                finally:
                    context.close()

                self.assertIn("脚本化测试完成", summary)
                self.assertEqual(len(llm.requests), 4, llm.requests)
                self.assertEqual(final_url, "https://cn.bing.com/search?q=quiz&form=test")
                self.assertEqual(
                    [action["action"] for action in llm.actions],
                    ["click", "click", "click", "finish"],
                )
                self.assertTrue((state_dir / "step-01.png").exists())

                first = llm.requests[0]
                self.assertEqual(first["path"], "/chat/completions")
                self.assertEqual(first["headers"].get("Authorization"), "Bearer test-key")
                self.assertEqual(first["payload"]["model"], "fake-model")
                self.assertEqual(first["payload"]["messages"][0]["role"], "system")
                sent = json.dumps(first["payload"], ensure_ascii=False)
                self.assertIn("开始测验", sent)
                self.assertIn("每日测验", sent)
        finally:
            llm.stop()


if __name__ == "__main__":
    unittest.main()
