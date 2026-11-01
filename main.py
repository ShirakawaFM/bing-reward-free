from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rewards_bot.browser import run_interactive_login
from rewards_bot.config import ConfigError, load_config
from rewards_bot.logging_setup import setup_logging
from rewards_bot.paths import PROJECT_ROOT
from rewards_bot.runner import run_once
from rewards_bot.scheduler import DailyScheduler

DEFAULT_CONFIG = PROJECT_ROOT / "config.toml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Microsoft Rewards 每日任务自动化（基础模式 / DeepSeek 元素索引模式）"
    )
    parser.add_argument(
        "-c",
        "--config",
        default=str(DEFAULT_CONFIG),
        help=f"配置文件路径（默认：{DEFAULT_CONFIG}）",
    )
    parser.add_argument(
        "-m",
        "--mode",
        choices=["basic", "advanced"],
        help="覆盖配置文件中的运行模式",
    )
    parser.add_argument("--login", action="store_true", help="打开浏览器手动登录并保存登录态")
    parser.add_argument("--once", action="store_true", help="立即执行一次，然后退出")
    parser.add_argument("--schedule", action="store_true", help="每天在配置时间执行（默认行为）")
    parser.add_argument("-v", "--verbose", action="store_true", help="在终端输出调试日志")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2

    setup_logging(cfg.general.log_dir, verbose=args.verbose)
    mode = args.mode or cfg.general.mode

    if args.login:
        return run_interactive_login(cfg)

    if args.once:
        return 0 if run_once(cfg, mode=mode) else 1

    # 无参数或显式 --schedule 均进入常驻调度。
    print("=" * 70)
    print("Microsoft Rewards 每日任务自动化")
    print(f"配置：{cfg.path}")
    print(f"模式：{mode}    时间：每天 {cfg.general.run_at}（{cfg.general.timezone}）")
    print(f"日志：{cfg.general.log_dir / 'rewards_bot.log'}")
    print("首次使用请先运行：python main.py --login")
    print("按 Ctrl+C 停止。")
    print("=" * 70)

    if mode == "advanced" and not cfg.advanced.api_key:
        print("错误：进阶模式缺少 DeepSeek API Key，请先配置。", file=sys.stderr)
        return 2

    scheduler = DailyScheduler(cfg.general)
    try:
        scheduler.run(lambda: run_once(cfg, mode=mode))
    except KeyboardInterrupt:
        print("\n已停止调度。")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
