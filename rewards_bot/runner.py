from __future__ import annotations

import logging
import time

from .agent import AgentAbort, RewardsAgent
from .basic import BasicRunner
from .browser import BrowserSession, LoginRequired
from .config import AppConfig
from .dom import is_rewards_home_url
from .llm import LLMError


def run_once(cfg: AppConfig, mode: str | None = None) -> bool:
    log = logging.getLogger("rewards_bot.runner")
    chosen_mode = (mode or cfg.general.mode).strip().lower()
    if chosen_mode not in {"basic", "advanced"}:
        log.error("未知运行模式：%s", chosen_mode)
        return False
    if chosen_mode == "advanced" and not cfg.advanced.api_key:
        log.error(
            "进阶模式需要 DeepSeek API Key。请在 config.toml 的 [advanced].api_key 中填写，"
            "或设置环境变量 DEEPSEEK_API_KEY。"
        )
        return False

    started = time.monotonic()
    log.info("=" * 78)
    log.info(
        "开始每日任务 | 模式=%s | 浏览器=%s | 自动搜索=%s",
        chosen_mode,
        "headless" if cfg.general.headless else "headful",
        cfg.basic.search_enabled,
    )
    success = True
    task_runner: BasicRunner | None = None

    try:
        with BrowserSession(cfg) as session:
            task_runner = BasicRunner(session, cfg)
            try:
                session.open_dashboard()
                if chosen_mode == "advanced":
                    agent = RewardsAgent(session, cfg)
                    summary = agent.run()
                    log.info("大模型模式结束：%s", summary)
                else:
                    task_runner.run_daily_tasks()
            except LoginRequired as exc:
                log.error("%s", exc)
                success = False
            except (AgentAbort, LLMError) as exc:
                log.error("大模型模式中止：%s", exc)
                success = False
                session.screenshot("agent-abort")
            except Exception:
                log.exception("日常任务执行失败")
                success = False
                session.screenshot("task-failed")

            # 无论任务模式是否顺利结束，都尝试一次安全领取和可选搜索。
            try:
                session.open_dashboard()
            except LoginRequired as exc:
                log.error("无法回到任务页，跳过领取与搜索：%s", exc)
                success = False
            except Exception as exc:
                log.warning("无法回到任务页，跳过领取与搜索：%s", exc)
                success = False
            else:
                if cfg.basic.auto_claim:
                    try:
                        task_runner.claim_rewards()
                    except LoginRequired as exc:
                        log.error("%s", exc)
                        success = False
                    except Exception:
                        log.exception("领取积分时发生异常")
                        success = False

                if cfg.basic.search_enabled:
                    try:
                        task_runner.run_searches()
                    except LoginRequired as exc:
                        log.error("%s", exc)
                        success = False
                    except Exception:
                        log.exception("自动搜索时发生异常")
                        success = False
                else:
                    log.info("自动搜索未启用（basic.search_enabled=false）。")

                try:
                    if not is_rewards_home_url(
                        session.current_page.url, cfg.general.url
                    ):
                        session.open_dashboard()
                    session.screenshot("final", full_page=True)
                except Exception as exc:
                    log.debug("保存最后截图失败：%s", exc)
    except LoginRequired as exc:
        log.error("%s", exc)
        success = False
    except Exception:
        log.exception("本次运行失败")
        success = False

    log.info(
        "本次运行结束：%s，总用时 %.1f 秒。详情见日志与 screenshot 目录。",
        "成功" if success else "有错误/不完整",
        time.monotonic() - started,
    )
    return success
