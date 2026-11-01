from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError

from .browser import BrowserSession, LoginRequired, is_login_url
from .config import AppConfig
from .dom import (
    click_block_reason,
    format_observation,
    host_allowed,
    is_rewards_home_url,
    observe,
)
from .llm import LLMClient, LLMError

SYSTEM_PROMPT = """你是 Microsoft Rewards 日常任务助手，正在代替账户所有者操作一个已经登录的浏览器。你的目标是用尽量少的步骤完成网页上的日常任务，并安全收尾。

## 目标
1. 在 Microsoft Rewards 任务页上完成“每日集 / Daily set / 每日任务”里可见的简单任务，例如测验、投票、打卡。
2. 任务页面出现测验或投票时，选择一个看起来合理的选项，然后点击“下一页 / 下一题 / 提交 / 投票 / 完成 / Next / Continue / Submit / Done”等按钮继续，直到出现积分奖励或任务完成。
3. 有些每日任务只是打开一个 Bing 搜索或阅读页面，页面上没有答题控件。这类任务打开后停留约 4–6 秒即可视为完成，然后返回任务页，不要点击搜索结果、广告或翻页按钮。
4. 完成后返回任务页，继续处理尚未完成的任务。
5. 只有在页面上出现明确的“领取 / Claim”时才可以领取已获得的积分。
6. 所有可做的日常任务都完成、没有新的任务、或页面要求你登录/验证时，使用 finish。

## 绝对禁止
- 禁止兑换积分、购买商品、充值、付款、填写任何支付信息。
- 禁止修改账号、密码、隐私、安全、设置，禁止退出登录、删除任何内容。
- 禁止输入账号密码或任何个人隐私信息，禁止下载文件。
- 禁止访问允许域名之外的网站。允许的域名：{allowed_hosts}
- 禁止点击广告、赞助链接、外部跳转链接。不要处理验证码或人机验证，遇到就让用户手动处理并 finish。
- 只操作当前观察结果中列出的元素 id，不要猜测不存在的 id；每次页面变化后 id 会重新编号，必须使用最新一次观察的 id。
- 允许点击“领取 / Claim”，但禁止点击“兑换 / Redeem”。
- 在 Bing 搜索结果页上，不要点击普通搜索结果、广告、分页或其他站外链接。

## 操作建议
- 你看到的页面元素带有 id，点击时填写 id。页头/页脚和导航区域的元素由 region 标注，优先操作 region=main 或 dialog 的内容。
- 如果点击后页面没有变化，不要连续重复同一个动作。可以滚动、等待，或者导航回任务页。
- 对于没有按钮的阅读类任务，点击任务卡片后等待几秒即可返回任务页。
- 页面文字含“已完成 / Completed”的卡片不要再次点击。
- 不要试图赚取搜索积分以外的额外任务；这个程序有独立的搜索模块。
- 如果一项任务明显失败，不要卡住；返回任务页继续其他任务。
- 在认为日常任务已经全部处理完时，主动 finish 并说明原因。

## 输出格式
每次只输出一个 JSON 对象，不要 Markdown，不要解释文本。格式：
{{"reason":"简短说明","action":"click","id":12}}
{{"reason":"简短说明","action":"scroll","dy":600}}
{{"reason":"简短说明","action":"wait","seconds":2}}
{{"reason":"简短说明","action":"back"}}
{{"reason":"简短说明","action":"navigate","url":"{dashboard_url}"}}
{{"reason":"简短说明","action":"finish","summary":"本轮完成情况"}}

只允许上述 action。navigate 只能导航到任务页。"""


class AgentAbort(RuntimeError):
    """LLM 模式无法继续。"""


class RewardsAgent:
    def __init__(self, session: BrowserSession, cfg: AppConfig) -> None:
        self.session = session
        self.cfg = cfg
        self.log = logging.getLogger("rewards_bot.agent")
        self.llm = LLMClient(cfg.advanced)
        self.allowed_hosts = cfg.advanced.allowed_hosts
        self.dashboard_url = cfg.general.url
        self.system_prompt = SYSTEM_PROMPT.format(
            allowed_hosts="、".join(self.allowed_hosts),
            dashboard_url=self.dashboard_url,
        )

    def run(self) -> str:
        page = self.session.open_dashboard()
        history: list[str] = []
        last_signature: tuple[Any, ...] | None = None
        repeats = 0
        invalid_outputs = 0
        started = time.monotonic()
        deadline = started + self.cfg.advanced.max_minutes * 60

        for step in range(1, self.cfg.advanced.max_steps + 1):
            if time.monotonic() > deadline:
                self.log.warning("大模型模式已达到时间上限（%s 分钟）。", self.cfg.advanced.max_minutes)
                return "达到时间上限，已停止。"

            page = self.session.current_page
            if self.session.is_login_page():
                raise LoginRequired("任务过程中登录失效，请手动运行 --login。")
            try:
                obs = observe(page)
            except PlaywrightError as exc:
                raise AgentAbort(f"读取页面失败：{exc}") from exc

            screenshot = self.session.screenshot(f"step-{step:02d}")
            self.log.info(
                "[%s/%s] %s | 交互元素 %s 个",
                step,
                self.cfg.advanced.max_steps,
                (obs.get("title") or obs.get("url") or "").strip()[:100],
                len(obs.get("elements", [])),
            )
            user_prompt = self._build_user_prompt(step, obs, history)
            messages = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            try:
                raw = self.llm.complete(messages, screenshot)
                decision = LLMClient.parse_json_object(raw)
                action = self._normalize_action(decision)
                invalid_outputs = 0
            except LLMError as exc:
                invalid_outputs += 1
                self.log.warning("模型输出或接口异常（连续 %s 次）：%s", invalid_outputs, exc)
                history.append(f"第 {step} 步：输出无效或接口错误（{str(exc)[:180]}）。请严格输出一个 JSON 动作。")
                if invalid_outputs >= 3:
                    raise AgentAbort(f"连续多次无法获得有效的模型动作：{exc}") from exc
                time.sleep(1.0)
                continue

            reason = str(decision.get("reason") or "").strip()[:300]
            self.log.info("模型决策：%s | 理由：%s", json.dumps(action, ensure_ascii=False), reason)
            if action["action"] == "finish":
                summary = str(action.get("summary") or reason or "模型结束任务").strip()
                self.log.info("模型宣布结束：%s", summary)
                return summary

            signature = self._action_signature(action)
            if signature == last_signature:
                repeats += 1
            else:
                repeats = 0
                last_signature = signature

            try:
                ok, detail = self._execute(action)
            except LoginRequired:
                raise
            except PlaywrightError as exc:
                ok, detail = False, f"浏览器操作失败：{exc}"
            except Exception as exc:
                ok, detail = False, f"动作执行异常：{exc}"

            status = "成功" if ok else "失败"
            self.log.info("动作结果：%s | %s", status, detail[:300])
            history.append(f"第 {step} 步：{signature} -> {status}：{detail[:220]}")
            if len(history) > 12:
                history = history[-12:]

            # 防止模型在两个页面之间无限来回。
            if not ok and repeats >= 3:
                history.append("系统提示：同一动作已连续失败多次，请改用返回任务页/滚动/等待，或 finish。")
            if repeats >= 6:
                raise AgentAbort("检测到连续 6 次完全相同的无效动作，已停止。")
            time.sleep(0.6)

        return f"达到最大步数 {self.cfg.advanced.max_steps}，已停止。"

    def _build_user_prompt(self, step: int, obs: dict[str, Any], history: list[str]) -> str:
        history_text = "\n".join(history[-12:]) if history else "（这是第一步）"
        return (
            f"这是第 {step}/{self.cfg.advanced.max_steps} 步。\n"
            f"最近动作记录：\n{history_text}\n\n"
            f"当前页面观察（元素的 id 只在本步有效）：\n{format_observation(obs)}\n\n"
            "请根据目标和安全约束，输出下一步的一个 JSON 动作。"
        )

    @staticmethod
    def _action_signature(action: dict[str, Any]) -> str:
        kind = action.get("action")
        if kind == "click":
            return f"click #{action.get('id')}"
        if kind == "scroll":
            return f"scroll {action.get('dy')}"
        if kind == "wait":
            return f"wait {action.get('seconds')}"
        if kind == "navigate":
            return f"navigate {action.get('url')}"
        return str(kind)

    @staticmethod
    def _normalize_action(decision: dict[str, Any]) -> dict[str, Any]:
        kind = str(decision.get("action") or decision.get("type") or "").strip().lower()
        reason = str(decision.get("reason") or "").strip()[:400]
        if kind == "click":
            raw_id = decision.get("id", decision.get("element_id"))
            try:
                element_id = int(raw_id)
            except (TypeError, ValueError) as exc:
                raise LLMError("click 动作缺少有效的整数 id。") from exc
            if element_id < 0 or element_id > 10_000:
                raise LLMError("click 动作的 id 超出范围。")
            return {"action": "click", "id": element_id, "reason": reason}
        if kind == "scroll":
            try:
                dy = int(decision.get("dy", 600))
            except (TypeError, ValueError):
                dy = 600
            dy = max(-3000, min(3000, dy))
            if dy == 0:
                dy = 600
            return {"action": "scroll", "dy": dy, "reason": reason}
        if kind == "wait":
            try:
                seconds = float(decision.get("seconds", 2))
            except (TypeError, ValueError):
                seconds = 2.0
            seconds = max(0.5, min(10.0, seconds))
            return {"action": "wait", "seconds": seconds, "reason": reason}
        if kind == "back":
            return {"action": "back", "reason": reason}
        if kind == "navigate":
            url = str(decision.get("url") or "").strip()
            return {"action": "navigate", "url": url, "reason": reason}
        if kind == "finish":
            summary = str(decision.get("summary") or reason or "任务结束").strip()[:1000]
            return {"action": "finish", "summary": summary, "reason": reason}
        raise LLMError(f"不支持的动作：{kind!r}")

    def _execute(self, action: dict[str, Any]) -> tuple[bool, str]:
        page = self.session.current_page
        kind = action["action"]

        if kind == "click":
            element_id = action["id"]
            selector = f'[data-qbot-id="{element_id}"]'
            count = page.locator(selector).count()
            if count == 0:
                return False, "该元素已不存在，页面可能发生变化；请基于新的观察重新选择。"
            locator = page.locator(selector).first
            try:
                info = locator.evaluate(
                    """(el) => {
                        const text = [
                          el.innerText || '',
                          el.getAttribute('aria-label') || '',
                          el.getAttribute('title') || '',
                          el.value || ''
                        ].join(' ').replace(/\\s+/g, ' ').trim().slice(0, 400);
                        return {
                          tag: el.tagName.toLowerCase(),
                          text: text,
                          href: typeof el.href === 'string' ? el.href : '',
                          type: (el.getAttribute('type') || '').toLowerCase()
                        };
                    }"""
                )
            except PlaywrightError as exc:
                return False, f"读取元素信息失败：{exc}"
            block_reason = click_block_reason(
                str(info.get("text") or ""),
                str(info.get("href") or ""),
                self.allowed_hosts,
                input_type=str(info.get("type") or ""),
            )
            if block_reason:
                self.log.warning("安全护栏拦截了点击：%s", block_reason)
                return False, f"安全护栏拦截：{block_reason}"

            self.log.debug("点击元素 #%s：%s", element_id, info.get("text", "")[:160])
            try:
                locator.scroll_into_view_if_needed(timeout=5_000)
            except PlaywrightError:
                pass
            try:
                locator.click(timeout=8_000)
            except PlaywrightError as exc:
                return False, f"点击失败：{str(exc).splitlines()[0][:200]}"

            page.wait_for_timeout(900)
            self.session.adopt_new_pages()
            try:
                self.session.current_page.wait_for_load_state("domcontentloaded", timeout=6_000)
            except Exception:
                pass
            self.session.current_page.wait_for_timeout(600)

            current_url = self.session.current_page.url
            if is_login_url(current_url):
                raise LoginRequired("点击后跳转到了登录页，请手动运行 --login。")
            host = (urlparse(current_url).hostname or "").lower()
            if host and not host_allowed(host, self.allowed_hosts):
                self.log.warning("点击后进入未允许的域名：%s", current_url[:200])
                self.session.screenshot("blocked-host")
                self.session.goto(self.dashboard_url)
                return False, f"点击后进入了不允许的域名 {host}，已返回任务页。"
            label = str(info.get("text") or "").replace("\n", " ")[:80]
            return True, f"已点击“{label}”，当前页面：{current_url[:160]}"

        if kind == "scroll":
            page.evaluate("(dy) => window.scrollBy(0, dy)", action["dy"])
            page.wait_for_timeout(500)
            return True, f"已滚动 {action['dy']} 像素。"

        if kind == "wait":
            page.wait_for_timeout(int(action["seconds"] * 1000))
            return True, f"已等待 {action['seconds']} 秒。"

        if kind == "back":
            try:
                page.go_back(wait_until="domcontentloaded", timeout=15_000)
                page.wait_for_timeout(900)
            except PlaywrightError:
                self.session.goto(self.dashboard_url)
                page = self.session.current_page
            if is_login_url(self.session.current_page.url):
                raise LoginRequired("返回时进入了登录页，请手动运行 --login。")
            host = (urlparse(self.session.current_page.url).hostname or "").lower()
            if host and not host_allowed(host, self.allowed_hosts):
                self.session.goto(self.dashboard_url)
                return False, "返回到了不允许的域名，已转到任务页。"
            return True, f"已返回上一页：{self.session.current_page.url[:160]}"

        if kind == "navigate":
            url = action.get("url", "")
            if not is_rewards_home_url(url, self.dashboard_url):
                return False, "navigate 只允许回到 Microsoft Rewards 任务页。"
            self.session.goto(self.dashboard_url)
            if self.session.is_login_page():
                raise LoginRequired("导航后进入登录页，请手动运行 --login。")
            return True, "已返回任务页。"

        return False, f"未处理的动作：{kind}"
