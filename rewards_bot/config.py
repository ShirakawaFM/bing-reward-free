from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .paths import PROJECT_ROOT
from .tasks_catalog import DEFAULT_TASK_TYPES, validate_task_types

_RUN_AT_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

DEFAULT_REWARDS_URL = "https://rewards.bing.com/earn"


class ConfigError(ValueError):
    """配置不合法。"""


@dataclass(slots=True)
class GeneralConfig:
    url: str = DEFAULT_REWARDS_URL
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
    auto_exit_after_run: bool = False

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
class StealthConfig:
    """防检测参数。

    basic_enabled  —— 基础防检测：查询字符偏移 + 右偏节奏 + 逐字输入（本地规则，零费用）。
    strong_enabled —— 强力防检测：一次大模型调用规划整轮人类行为，带缓存与本地抖动。
    两者都关闭时完全保留原始行为。
    """

    basic_enabled: bool = True
    strong_enabled: bool = False
    query_jitter: int = 2
    typing_enabled: bool = True
    mouse_jitter: bool = True
    break_probability: float = 0.12
    click_result_probability: float = 0.15
    plan_max_tokens: int = 700
    plan_cache_hours: float = 12.0
    # 强力模式下每步观察内容的压缩上限，用来压低 token。
    strong_max_page_text: int = 1200
    strong_max_elements: int = 45

    @property
    def enabled(self) -> bool:
        return self.basic_enabled or self.strong_enabled


@dataclass(slots=True)
class AppConfig:
    path: Path
    general: GeneralConfig
    basic: BasicConfig
    advanced: AdvancedConfig
    stealth: StealthConfig = field(default_factory=StealthConfig)


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


def normalize_rewards_url(value: object) -> str:
    """把旧版默认的 /dashboard 迁移到当前任务页 /earn，其他地址保持原样。"""

    text = str(value).strip() if value is not None else ""
    if not text:
        return DEFAULT_REWARDS_URL
    try:
        parts = urlsplit(text)
    except ValueError:
        return text
    host = (parts.hostname or "").lower()
    path = (parts.path or "/").rstrip("/").lower() or "/"
    if host == "rewards.bing.com" and path == "/dashboard":
        return urlunsplit(
            (
                parts.scheme or "https",
                parts.netloc or "rewards.bing.com",
                "/earn",
                parts.query,
                parts.fragment,
            )
        )
    return text


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).expanduser().resolve()
    if not config_path.exists():
        raise ConfigError(
            f"找不到配置文件：{config_path}\n"
            "请先复制 config.example.toml 为 config.toml，或用 -c 指定配置文件。"
        )
    try:
        # 兼容记事本/编辑器保存的 UTF-8 BOM：tomllib 不接受行首 BOM。
        raw = tomllib.loads(config_path.read_text(encoding="utf-8-sig"))
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
        url=normalize_rewards_url(_get(g, "url", DEFAULT_REWARDS_URL)),
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
        auto_exit_after_run=_as_bool(g.get("auto_exit_after_run"), False),
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

    stealth = _load_stealth(raw.get("stealth") or {})

    return AppConfig(
        path=config_path,
        general=general,
        basic=basic,
        advanced=advanced,
        stealth=stealth,
    )


def _load_stealth(s: dict) -> StealthConfig:
    """解析 [stealth] 段。缺省时保持“基础防检测开启、强力关闭”。"""
    if not isinstance(s, dict):
        return StealthConfig()

    def _num(key: str, default: float) -> float:
        try:
            return float(_get(s, key, default))
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"stealth.{key} 必须是数字。") from exc

    def _int(key: str, default: int) -> int:
        try:
            return int(_get(s, key, default))
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"stealth.{key} 必须是整数。") from exc

    query_jitter = _int("query_jitter", 2)
    if query_jitter < 1 or query_jitter > 3:
        raise ConfigError("stealth.query_jitter 只能是 1、2 或 3。")

    break_probability = _num("break_probability", 0.12)
    if break_probability < 0 or break_probability > 0.9:
        raise ConfigError("stealth.break_probability 必须在 0 – 0.9 之间。")

    click_probability = _num("click_result_probability", 0.15)
    if click_probability < 0 or click_probability > 1:
        raise ConfigError("stealth.click_result_probability 必须在 0 – 1 之间。")

    cache_hours = _num("plan_cache_hours", 12.0)
    if cache_hours < 0 or cache_hours > 24 * 30:
        raise ConfigError("stealth.plan_cache_hours 必须在 0 – 720 之间。")

    return StealthConfig(
        basic_enabled=_as_bool(s.get("basic_enabled"), True),
        strong_enabled=_as_bool(s.get("strong_enabled"), False),
        query_jitter=query_jitter,
        typing_enabled=_as_bool(s.get("typing_enabled"), True),
        mouse_jitter=_as_bool(s.get("mouse_jitter"), True),
        break_probability=break_probability,
        click_result_probability=click_probability,
        plan_max_tokens=max(200, min(2000, _int("plan_max_tokens", 700))),
        plan_cache_hours=cache_hours,
        strong_max_page_text=max(200, min(3000, _int("strong_max_page_text", 1200))),
        strong_max_elements=max(10, min(140, _int("strong_max_elements", 45))),
    )
