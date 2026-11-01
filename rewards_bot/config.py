from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .paths import PROJECT_ROOT
from .tasks_catalog import DEFAULT_TASK_TYPES, validate_task_types

_RUN_AT_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


class ConfigError(ValueError):
    """配置不合法。"""


@dataclass(slots=True)
class GeneralConfig:
    url: str = "https://rewards.bing.com/dashboard"
    timezone: str = "Asia/Shanghai"
    run_at: str = "08:30"
    mode: str = "basic"
    headless: bool = False
    browser_channel: str = ""
    slow_mo_ms: int = 40
    user_data_dir: Path = field(default_factory=lambda: PROJECT_ROOT / ".browser-profile")
    state_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "state")
    log_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "logs")
    catch_up: bool = True

    @property
    def run_hour_minute(self) -> tuple[int, int]:
        hour, minute = self.run_at.split(":")
        return int(hour), int(minute)

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@dataclass(slots=True)
class BasicConfig:
    max_tasks: int = 8
    max_rounds_per_task: int = 14
    auto_claim: bool = True
    search_enabled: bool = False
    search_count: int = 20
    search_delay_min: float = 6.0
    search_delay_max: float = 12.0
    search_host: str = "https://www.bing.com"
    search_queries_file: Path = field(
        default_factory=lambda: PROJECT_ROOT / "queries.txt"
    )
    read_wait_seconds: int = 6
    task_types: list[str] = field(default_factory=lambda: list(DEFAULT_TASK_TYPES))


@dataclass(slots=True)
class AdvancedConfig:
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    vision: bool = False
    temperature: float = 0.0
    max_steps: int = 40
    max_minutes: int = 10
    timeout_seconds: int = 90
    allowed_hosts: list[str] = field(
        default_factory=lambda: [
            "rewards.bing.com",
            "bing.com",
            "www.bing.com",
            "cn.bing.com",
        ]
    )

    @property
    def vision_supported(self) -> bool:
        """DeepSeek 官方 API 目前只接收文本，截图仅用于排查问题。"""
        host = self.base_url.lower()
        return self.vision and "api.deepseek.com" not in host


@dataclass(slots=True)
class AppConfig:
    path: Path
    general: GeneralConfig
    basic: BasicConfig
    advanced: AdvancedConfig


def _as_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "是"}
    return bool(value)


def _resolve_path(value: object, base: Path, default: Path) -> Path:
    if value is None or str(value).strip() == "":
        return default
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _get(table: dict, key: str, default):
    value = table.get(key, default)
    return default if value is None else value


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).expanduser().resolve()
    if not config_path.exists():
        raise ConfigError(
            f"找不到配置文件：{config_path}\n"
            "请先复制 config.example.toml 为 config.toml，或用 -c 指定配置文件。"
        )
    try:
        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"配置文件 TOML 语法错误：{exc}") from exc

    base = config_path.parent
    g = raw.get("general") or {}
    b = raw.get("basic") or {}
    a = raw.get("advanced") or {}

    run_at = str(_get(g, "run_at", "08:30")).strip()
    if not _RUN_AT_RE.match(run_at):
        raise ConfigError("general.run_at 必须是 HH:MM，例如 08:30。")
    hour, minute = run_at.split(":")
    run_at = f"{int(hour):02d}:{int(minute):02d}"

    timezone_name = str(_get(g, "timezone", "Asia/Shanghai")).strip()
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(f"未知时区：{timezone_name}") from exc

    mode = str(_get(g, "mode", "basic")).strip().lower()
    if mode not in {"basic", "advanced"}:
        raise ConfigError("general.mode 只能是 basic 或 advanced。")

    general = GeneralConfig(
        url=str(_get(g, "url", "https://rewards.bing.com/dashboard")).strip(),
        timezone=timezone_name,
        run_at=run_at,
        mode=mode,
        headless=_as_bool(g.get("headless"), False),
        browser_channel=str(_get(g, "browser_channel", "")).strip(),
        slow_mo_ms=max(0, int(_get(g, "slow_mo_ms", 40))),
        user_data_dir=_resolve_path(
            g.get("user_data_dir"), base, PROJECT_ROOT / ".browser-profile"
        ),
        state_dir=_resolve_path(g.get("state_dir"), base, PROJECT_ROOT / "state"),
        log_dir=_resolve_path(g.get("log_dir"), base, PROJECT_ROOT / "logs"),
        catch_up=_as_bool(g.get("catch_up"), True),
    )

    search_min = float(_get(b, "search_delay_min", 6.0))
    search_max = float(_get(b, "search_delay_max", 12.0))
    if search_min <= 0 or search_max < search_min:
        raise ConfigError("basic.search_delay_min/max 必须是正数，且 max >= min。")

    raw_task_types = b.get("task_types")
    if raw_task_types is None:
        task_types = list(DEFAULT_TASK_TYPES)
    else:
        try:
            task_types = validate_task_types(raw_task_types)
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc

    basic = BasicConfig(
        max_tasks=max(1, min(30, int(_get(b, "max_tasks", 8)))),
        max_rounds_per_task=max(1, min(40, int(_get(b, "max_rounds_per_task", 14)))),
        auto_claim=_as_bool(b.get("auto_claim"), True),
        search_enabled=_as_bool(b.get("search_enabled"), False),
        search_count=max(0, min(100, int(_get(b, "search_count", 20)))),
        search_delay_min=search_min,
        search_delay_max=search_max,
        search_host=str(_get(b, "search_host", "https://www.bing.com")).strip().rstrip("/"),
        search_queries_file=_resolve_path(
            b.get("search_queries_file"), base, PROJECT_ROOT / "queries.txt"
        ),
        read_wait_seconds=max(1, min(60, int(_get(b, "read_wait_seconds", 6)))),
        task_types=task_types,
    )

    api_key = str(_get(a, "api_key", "")).strip()
    if api_key.startswith("env:"):
        api_key = os.environ.get(api_key[4:].strip(), "").strip()
    if not api_key:
        api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        api_key = os.environ.get("REWARDS_LLM_API_KEY", "").strip()

    allowed_hosts_raw = a.get("allowed_hosts") or [
        "rewards.bing.com",
        "bing.com",
        "www.bing.com",
        "cn.bing.com",
    ]
    if not isinstance(allowed_hosts_raw, list):
        raise ConfigError("advanced.allowed_hosts 必须是字符串数组。")
    allowed_hosts = [str(h).strip().lower() for h in allowed_hosts_raw if str(h).strip()]

    advanced = AdvancedConfig(
        api_key=api_key,
        base_url=str(_get(a, "base_url", "https://api.deepseek.com")).strip().rstrip("/"),
        model=str(_get(a, "model", "deepseek-chat")).strip(),
        vision=_as_bool(a.get("vision"), False),
        temperature=max(0.0, min(2.0, float(_get(a, "temperature", 0.0)))),
        max_steps=max(3, min(120, int(_get(a, "max_steps", 40)))),
        max_minutes=max(1, min(60, int(_get(a, "max_minutes", 10)))),
        timeout_seconds=max(15, min(300, int(_get(a, "timeout_seconds", 90)))),
        allowed_hosts=allowed_hosts,
    )

    return AppConfig(path=config_path, general=general, basic=basic, advanced=advanced)
