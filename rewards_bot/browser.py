from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import (
    BrowserContext,
    Locator,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from .config import AppConfig

LOGIN_HOSTS = (
    "login.live.com",
    "login.microsoftonline.com",
    "login.windows.net",
    "signup.live.com",
    "account.microsoft.com",
    "account.live.com",
)

_DENY_DIALOG_RE = re.compile(
    r"兑换|兌換|redeem|购买|購買|purchase|payment|付款|支付|删除|刪除|delete",
    re.IGNORECASE,
)


class LoginRequired(RuntimeError):
    """浏览器配置中缺少有效的登录态。"""


class BrowserError(RuntimeError):
    """浏览器启动或页面操作失败。"""


def is_login_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return any(host == item or host.endswith("." + item) for item in LOGIN_HOSTS)


class BrowserSession:
    """复用持久化浏览器配置，让用户只需手动登录一次。"""

    def __init__(self, cfg: AppConfig, headless: bool | None = None) -> None:
        self.cfg = cfg
        self.headless = cfg.general.headless if headless is None else headless
        self.log = logging.getLogger("rewards_bot.browser")
        self._playwright: Playwright | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.artifacts_dir = (
            cfg.general.state_dir
            / "screenshots"
            / datetime.now().strftime("%Y%m%d-%H%M%S")
        )

    def __enter__(self) -> "BrowserSession":
        cfg = self.cfg
        cfg.general.user_data_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

        brand_before = None
        if not self.headless:
            try:
                from .window_branding import snapshot_task_browser

                brand_before = snapshot_task_browser()
            except Exception as exc:
                self.log.debug("无法记录任务浏览器窗口快照：%s", exc)

        self._playwright = sync_playwright().start()
        launch_options: dict = {
            "user_data_dir": str(cfg.general.user_data_dir),
            "headless": self.headless,
            "slow_mo": cfg.general.slow_mo_ms,
            "viewport": {"width": 1440, "height": 960},
            "screen": {"width": 1440, "height": 960},
            "locale": "zh-CN",
            "timezone_id": cfg.general.timezone,
            "accept_downloads": False,
            "args": ["--no-first-run", "--no-default-browser-check"],
        }
        if cfg.general.browser_channel:
            launch_options["channel"] = cfg.general.browser_channel
        try:
            self.context = self._playwright.chromium.launch_persistent_context(**launch_options)
        except Exception as exc:
            self._playwright.stop()
            self._playwright = None
            raise BrowserError(
                "浏览器启动失败。Windows 可以设置 general.browser_channel = \"msedge\" 使用系统 Edge，"
                "或执行 `python -m playwright install chromium` 安装内置 Chromium；"
                "如果浏览器配置正被另一个程序占用，请先关闭它。\n"
                f"原始错误：{exc}"
            ) from exc

        self.context.set_default_timeout(15_000)
        self.context.set_default_navigation_timeout(60_000)
        self.context.on("page", self._bind_page)
        pages = [p for p in self.context.pages if not p.is_closed()]
        self.page = pages[0] if pages else self.context.new_page()
        self._bind_page(self.page)
        if not self.headless and brand_before is not None:
            try:
                from .window_branding import brand_task_browser

                branded = brand_task_browser(brand_before)
                if branded:
                    self.log.info(
                        "任务浏览器已使用 Rewards Pilot 专属图标，共 %s 个窗口。",
                        len(branded),
                    )
            except Exception as exc:
                self.log.debug("设置任务浏览器图标失败，不影响任务：%s", exc)
        self.log.debug("浏览器已启动，headless=%s，配置目录=%s", self.headless, cfg.general.user_data_dir)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _bind_page(self, page: Page) -> None:
        try:
            page.set_default_timeout(15_000)
            page.set_default_navigation_timeout(60_000)
            page.on("dialog", self._handle_dialog)
            page.on("crash", lambda _p: self.log.error("页面崩溃"))
        except Exception:
            # 页面可能在绑定瞬间被关闭。
            pass

    def _handle_dialog(self, dialog) -> None:
        try:
            message = dialog.message
            if _DENY_DIALOG_RE.search(message):
                self.log.warning("检测到疑似兑换/支付/删除的对话框，已取消：%s", message[:200])
                dialog.dismiss()
            else:
                self.log.info("自动确认对话框：%s", message[:200])
                dialog.accept()
        except Exception as exc:
            self.log.debug("处理浏览器对话框失败：%s", exc)

    @property
    def current_page(self) -> Page:
        if self.page is None or self.page.is_closed():
            pages = [p for p in self.context.pages if not p.is_closed()] if self.context else []
            if not pages:
                raise BrowserError("浏览器中没有可用页面（可能已被手动关闭）。")
            self.page = pages[-1]
            self._bind_page(self.page)
        return self.page

    def goto(self, url: str) -> None:
        page = self.current_page
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        except PlaywrightTimeoutError:
            self.log.warning("页面加载超时，继续检查当前内容：%s", page.url)
        except Exception as exc:
            raise BrowserError(f"打开页面失败：{url}\n{exc}") from exc
        page.wait_for_timeout(800)

    def adopt_new_pages(self) -> bool:
        """如果点击打开了新标签页，切换到新标签并关闭旧标签。"""
        if self.context is None:
            return False
        pages = [p for p in self.context.pages if not p.is_closed()]
        if not pages:
            raise BrowserError("浏览器窗口中的所有页面都已被关闭。")
        old = self.page
        if old is not None and not old.is_closed() and len(pages) == 1:
            return False
        new_page = pages[-1]
        if new_page is old:
            return False
        self.page = new_page
        self._bind_page(new_page)
        try:
            new_page.wait_for_load_state("domcontentloaded", timeout=8_000)
        except Exception:
            pass
        try:
            new_page.wait_for_timeout(500)
        except Exception:
            pass
        if old is not None and old is not new_page:
            try:
                old.close()
            except Exception:
                pass
        self.log.debug("已切换到新标签页：%s", new_page.url)
        return True

    def click_maybe_popup(self, locator: Locator) -> None:
        """点击并等待可能出现的页面跳转/新标签。"""
        page = self.current_page
        try:
            locator.scroll_into_view_if_needed(timeout=5_000)
        except Exception:
            pass
        try:
            locator.click(timeout=8_000)
        except Exception as exc:
            raise BrowserError(f"点击元素失败：{exc}") from exc
        page.wait_for_timeout(1_000)
        self.adopt_new_pages()
        try:
            self.current_page.wait_for_load_state("domcontentloaded", timeout=8_000)
        except Exception:
            pass

    def is_login_page(self) -> bool:
        page = self.current_page
        if is_login_url(page.url):
            return True
        try:
            return page.locator('input[type="password"]:visible').count() > 0
        except Exception:
            return False

    def open_dashboard(self) -> Page:
        """打开仪表盘，并确认登录态。失败时抛出 LoginRequired。"""
        for attempt in range(2):
            self.goto(self.cfg.general.url)
            page = self.current_page
            page.wait_for_timeout(1_500 if attempt == 0 else 2_500)
            if not self.is_login_page():
                break
        page = self.current_page
        if self.is_login_page():
            raise LoginRequired(
                "登录已失效。请先运行 `python main.py --login` 手动登录，再执行任务。"
            )

        host = (urlparse(page.url).hostname or "").lower()
        if not (host == "rewards.bing.com" or host.endswith(".rewards.bing.com")):
            self.screenshot("unexpected-page")
            raise BrowserError(
                f"打开仪表盘后进入了非预期页面：{page.url}\n"
                "可能是网络、验证码或地区重定向问题，请先手动运行 --login 查看页面。"
            )
        self.log.info("仪表盘已打开：%s", page.url)
        return page

    def screenshot(self, name: str, full_page: bool = False) -> Path | None:
        try:
            safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "-", name).strip("-") or "shot"
            path = self.artifacts_dir / f"{safe_name}.png"
            self.current_page.screenshot(path=str(path), full_page=full_page)
            self.log.debug("截图已保存：%s", path)
            return path
        except Exception as exc:
            self.log.warning("截图失败：%s", exc)
            return None

    def close(self) -> None:
        try:
            if self.context is not None:
                self.context.close()
        except Exception:
            pass
        finally:
            self.context = None
            self.page = None
            if self._playwright is not None:
                try:
                    self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None


def run_interactive_login(cfg: AppConfig) -> int:
    """打开有界面浏览器，让用户手动完成 Microsoft 登录。"""
    print("正在打开浏览器，请完成 Microsoft 账号登录（含双重验证）。")
    print("登录完成后回到本终端，按 Enter 保存登录态。")
    with BrowserSession(cfg, headless=False) as session:
        try:
            session.goto(cfg.general.url)
            session.current_page.wait_for_timeout(2_000)
        except BrowserError as exc:
            print(f"打开页面失败：{exc}")
            return 1
        if session.is_login_page():
            print("请在浏览器窗口中登录。登录后会自动回到 Rewards 仪表盘。")
        else:
            print("检测到当前浏览器配置已经登录。")
        try:
            input("登录完成后按 Enter 继续...")
        except (EOFError, KeyboardInterrupt):
            print()
        try:
            session.open_dashboard()
        except LoginRequired:
            print("仍未检测到有效登录，请重新运行 `python main.py --login`。")
            return 1
        except BrowserError as exc:
            print(f"登录后检查失败：{exc}")
            return 1
        print("登录态已保存到浏览器配置目录，之后定时任务会复用它。")
        session.screenshot("login-check")
    return 0
