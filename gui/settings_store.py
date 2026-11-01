from __future__ import annotations

import logging
import shutil
import threading
from pathlib import Path
from typing import Any

import tomlkit

from rewards_bot.config import AppConfig, ConfigError, load_config

log = logging.getLogger("rewards_bot.gui.settings")

_FALLBACK_CONFIG = """[general]
url = "https://rewards.bing.com/dashboard"
timezone = "Asia/Shanghai"
run_at = "08:30"
mode = "basic"
headless = false
browser_channel = "msedge"
slow_mo_ms = 40
user_data_dir = ".browser-profile"
state_dir = "state"
log_dir = "logs"
catch_up = true
auto_exit_after_run = false

[basic]
max_tasks = 8
max_rounds_per_task = 14
auto_claim = true
search_enabled = false
search_count = 20
search_delay_min = 6
search_delay_max = 12
search_host = "https://www.bing.com"
search_queries_file = "queries.txt"
read_wait_seconds = 6
task_types = ["daily_quiz", "daily_poll", "daily_link", "checkin", "this_or_that", "weekly_set", "monthly_set", "more_quiz", "more_poll", "more_link", "video"]

[advanced]
api_key = ""
base_url = "https://api.deepseek.com"
model = "deepseek-chat"
vision = false
temperature = 0.0
max_steps = 40
max_minutes = 10
timeout_seconds = 90
allowed_hosts = ["rewards.bing.com", "bing.com", "www.bing.com", "cn.bing.com"]
"""


class SettingsError(ValueError):
    pass


class SettingsStore:
    def __init__(self, config_path: Path, example_path: Path) -> None:
        self.config_path = config_path
        self.example_path = example_path
        self._lock = threading.RLock()

    def ensure(self) -> None:
        with self._lock:
            if self.config_path.exists():
                return
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            if self.example_path.exists():
                shutil.copyfile(self.example_path, self.config_path)
            else:
                self.config_path.write_text(_FALLBACK_CONFIG, encoding="utf-8")
            log.info("已创建配置文件：%s", self.config_path)

    def load(self) -> AppConfig:
        with self._lock:
            self.ensure()
            return load_config(self.config_path)

    def update(self, payload: dict[str, Any]) -> AppConfig:
        if not isinstance(payload, dict):
            raise SettingsError("设置内容必须是 JSON 对象。")
        with self._lock:
            self.ensure()
            try:
                doc = tomlkit.parse(self.config_path.read_text(encoding="utf-8"))
            except (OSError, tomlkit.exceptions.ParseError) as exc:
                raise SettingsError(f"读取配置失败：{exc}") from exc

            general = _table(doc, "general")
            basic = _table(doc, "basic")
            advanced = _table(doc, "advanced")

            g = payload.get("general") or {}
            b = payload.get("basic") or {}
            a = payload.get("advanced") or {}
            if not all(isinstance(item, dict) for item in (g, b, a)):
                raise SettingsError("设置分组必须是 JSON 对象。")

            _set_str(g, "run_at", general, "run_at")
            _set_str(g, "timezone", general, "timezone")
            _set_str(g, "mode", general, "mode")
            _set_bool(g, "headless", general, "headless")
            _set_bool(g, "catch_up", general, "catch_up")
            _set_bool(g, "auto_exit_after_run", general, "auto_exit_after_run")

            _set_int(b, "max_tasks", basic, "max_tasks")
            _set_bool(b, "auto_claim", basic, "auto_claim")
            _set_bool(b, "search_enabled", basic, "search_enabled")
            _set_int(b, "search_count", basic, "search_count")
            _set_float(b, "search_delay_min", basic, "search_delay_min")
            _set_float(b, "search_delay_max", basic, "search_delay_max")
            _set_int(b, "read_wait_seconds", basic, "read_wait_seconds")
            _set_task_types(b, basic)

            _set_str(a, "base_url", advanced, "base_url")
            _set_str(a, "model", advanced, "model")
            _set_bool(a, "vision", advanced, "vision")
            _set_float(a, "temperature", advanced, "temperature")
            _set_int(a, "max_steps", advanced, "max_steps")
            _set_int(a, "max_minutes", advanced, "max_minutes")

            clear_key = _bool_value(a.get("clear_api_key", False), "clear_api_key")
            if "api_key" in a:
                key = a.get("api_key")
                if not isinstance(key, str):
                    raise SettingsError("advanced.api_key 必须是字符串。")
                key = key.strip()
                if key:
                    advanced["api_key"] = key
                elif clear_key:
                    advanced["api_key"] = ""
            elif clear_key:
                advanced["api_key"] = ""

            text = tomlkit.dumps(doc)
            tmp = self.config_path.with_name(self.config_path.name + ".tmp")
            try:
                tmp.write_text(text, encoding="utf-8")
                load_config(tmp)  # 先校验，失败时保留原配置
                tmp.replace(self.config_path)
            except ConfigError:
                raise
            except Exception as exc:
                raise SettingsError(f"配置校验失败：{exc}") from exc
            finally:
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
            cfg = load_config(self.config_path)
            log.info("配置已保存：%s", self.config_path)
            return cfg

    @staticmethod
    def public(cfg: AppConfig) -> dict[str, Any]:
        return {
            "path": str(cfg.path),
            "general": {
                "url": cfg.general.url,
                "run_at": cfg.general.run_at,
                "timezone": cfg.general.timezone,
                "mode": cfg.general.mode,
                "headless": cfg.general.headless,
                "catch_up": cfg.general.catch_up,
                "auto_exit_after_run": cfg.general.auto_exit_after_run,
                "browser_channel": cfg.general.browser_channel,
            },
            "basic": {
                "max_tasks": cfg.basic.max_tasks,
                "auto_claim": cfg.basic.auto_claim,
                "search_enabled": cfg.basic.search_enabled,
                "search_count": cfg.basic.search_count,
                "search_delay_min": cfg.basic.search_delay_min,
                "search_delay_max": cfg.basic.search_delay_max,
                "read_wait_seconds": cfg.basic.read_wait_seconds,
                "task_types": list(cfg.basic.task_types),
            },
            "advanced": {
                "base_url": cfg.advanced.base_url,
                "model": cfg.advanced.model,
                "vision": cfg.advanced.vision,
                "vision_supported": cfg.advanced.vision_supported,
                "temperature": cfg.advanced.temperature,
                "max_steps": cfg.advanced.max_steps,
                "max_minutes": cfg.advanced.max_minutes,
                "api_key_set": bool(cfg.advanced.api_key),
            },
        }


def _table(doc, name: str):
    value = doc.get(name)
    if value is None or not hasattr(value, "keys"):
        value = tomlkit.table()
        doc[name] = value
    return value


def _set_str(payload: dict, key: str, table, target: str) -> None:
    if key not in payload:
        return
    value = payload[key]
    if not isinstance(value, str):
        raise SettingsError(f"{target} 必须是字符串。")
    table[target] = value.strip()


def _set_bool(payload: dict, key: str, table, target: str) -> None:
    if key not in payload:
        return
    table[target] = _bool_value(payload[key], target)


def _bool_value(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise SettingsError(f"{label} 必须是布尔值。")
    return value


def _set_int(payload: dict, key: str, table, target: str) -> None:
    if key not in payload:
        return
    value = payload[key]
    if isinstance(value, bool):
        raise SettingsError(f"{target} 必须是整数。")
    try:
        table[target] = int(value)
    except (TypeError, ValueError) as exc:
        raise SettingsError(f"{target} 必须是整数。") from exc


def _set_float(payload: dict, key: str, table, target: str) -> None:
    if key not in payload:
        return
    value = payload[key]
    if isinstance(value, bool):
        raise SettingsError(f"{target} 必须是数字。")
    try:
        table[target] = float(value)
    except (TypeError, ValueError) as exc:
        raise SettingsError(f"{target} 必须是数字。") from exc


def _set_task_types(payload: dict, table) -> None:
    if "task_types" not in payload:
        return
    value = payload["task_types"]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SettingsError("basic.task_types 必须是字符串数组。")
    table["task_types"] = [item.strip() for item in value if item.strip()]
