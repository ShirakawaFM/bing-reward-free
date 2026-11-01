"""人类行为模拟（防检测）模块。

两种强度：

* **基础防检测** —— 纯本地规则，零额外网络/费用：
  - 搜索词随机偏移（同音/形近汉字替换、英文相邻字母换位、键盘邻键笔误），
    每次改动 1–2 个字符，语义保持高度相近；
  - 节奏采样（右偏分布，不是均匀随机），每次间隔都不同，偶发“走神”长停顿；
  - 逐字符输入 + 真实鼠标移动 + 分段滚动，而不是一次性跳转 URL。
* **强力防检测** —— 一次大模型调用产出整轮“人类操作剧本”（每条搜索的停留时长、
  滚动次数、是否悬停/点击结果），执行时再叠加本地抖动。整轮只消耗一次
  completion（默认 ≤700 max_tokens），并有磁盘缓存，同一天重复运行不再计费。

两种模式都可以单独开关；都不开时保留原来的行为，便于对比和回滚。
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote_plus, urlparse

from playwright.sync_api import Error as PlaywrightError

from .browser import BrowserSession, LoginRequired
from .config import AppConfig, StealthConfig

# --------------------------------------------------------------------------
# 查询扰动
# --------------------------------------------------------------------------

_CJK_RANGE = "\u4e00-\u9fff"

# 常见同音/形近字组。每组内的字可以互相替换，肉眼几乎看不出差别，
# 但对搜索引擎来说已经是一次不同的查询。
_HOMOPHONE_GROUPS: tuple[str, ...] = (
    "的得地", "在再", "已己", "做作", "及极", "帐账", "辨辩", "即既",
    "象像", "须需", "查察", "秘蜜", "启起", "址止", "圆园", "历厉",
    "度渡", "练炼", "分份", "占站", "慢漫", "器气", "简减", "词辞",
    "搜叟", "索锁", "推堆", "攻功", "略掠", "记纪", "题提", "新闻闻",
    "健建", "健康慷", "饮食饮", "技技", "巧巧", "旅旅", "攻略攻",
)

# QWERTY 相邻键，用于制造“手滑”级别的英文笔误。
_KEY_NEIGHBOURS: dict[str, str] = {
    "q": "wa", "w": "qes", "e": "wrd", "r": "etf", "t": "ryg", "y": "tuh",
    "u": "yij", "i": "uok", "o": "ipl", "p": "ol",
    "a": "qsz", "s": "awdx", "d": "sefc", "f": "drgv", "g": "fthb",
    "h": "gyjn", "j": "hukm", "k": "jil", "l": "kop",
    "z": "asx", "x": "zsdc", "c": "xdfv", "v": "cfgb", "b": "vghn",
    "n": "bhjm", "m": "njk",
}


def _build_homophone_table() -> dict[str, str]:
    table: dict[str, str] = {}
    for group in _HOMOPHONE_GROUPS:
        for ch in group:
            others = [other for other in group if other != ch]
            if others:
                table.setdefault(ch, "".join(others))
    return table


_CJK_ALTERNATES = _build_homophone_table()

_ASCII_WORD_RE = re.compile(r"[A-Za-z]{2,}")


def _pick_cjk_position(text: str, rng: random.Random) -> int | None:
    positions = [
        idx
        for idx, ch in enumerate(text)
        if ch in _CJK_ALTERNATES and len(text) > 1
    ]
    if not positions:
        return None
    return rng.choice(positions)


def _edit_cjk(text: str, rng: random.Random) -> str | None:
    """把一个汉字换成同音/形近字。"""
    pos = _pick_cjk_position(text, rng)
    if pos is None:
        return None
    alternates = _CJK_ALTERNATES[text[pos]]
    replacement = rng.choice(alternates)
    if not replacement or replacement == text[pos]:
        return None
    return text[:pos] + replacement + text[pos + 1 :]


def _edit_latin(text: str, rng: random.Random) -> str | None:
    """英文单词：相邻字母换位 / 键盘邻键 / 漏字母 / 重复字母。"""
    words = [match.span() for match in _ASCII_WORD_RE.finditer(text)]
    if not words:
        return None
    start, end = rng.choice(words)
    word = text[start:end]
    if len(word) < 2:
        return None
    mode = rng.choice(("transpose", "neighbour", "drop", "double"))
    if mode == "transpose":
        idx = rng.randrange(len(word) - 1)
        mutated = word[:idx] + word[idx + 1] + word[idx] + word[idx + 2 :]
    elif mode == "neighbour":
        idx = rng.randrange(len(word))
        lower = word[idx].lower()
        neighbours = _KEY_NEIGHBOURS.get(lower)
        if not neighbours:
            return None
        replacement = rng.choice(neighbours)
        if word[idx].isupper():
            replacement = replacement.upper()
        mutated = word[:idx] + replacement + word[idx + 1 :]
    elif mode == "drop":
        if len(word) <= 3:
            return None
        idx = rng.randrange(1, len(word) - 1)
        mutated = word[:idx] + word[idx + 1 :]
    else:  # double
        idx = rng.randrange(len(word))
        mutated = word[:idx] + word[idx] + word[idx:]
    if mutated == word:
        return None
    return text[:start] + mutated + text[end:]


def jitter_query(
    query: str,
    rng: random.Random,
    max_edits: int = 2,
) -> tuple[str, int]:
    """给搜索词加一点随机偏移，返回 (新查询, 实际改动次数)。

    只改动 1–2 个字符、或交换相邻字母位置，语义与原文高度一致；
    这样每次发出去的查询都不完全相同，但用户要搜的东西还是同一个。
    """
    text = (query or "").strip()
    if not text:
        return query, 0
    max_edits = max(0, min(3, int(max_edits)))
    if max_edits == 0 or len(text) < 2:
        return text, 0

    target = rng.randint(1, max_edits)
    current = text
    edits = 0
    attempts = 0
    while edits < target and attempts < 8:
        attempts += 1
        mutator = _edit_cjk if rng.random() < 0.62 else _edit_latin
        candidate = mutator(current, rng)
        if not candidate or candidate == current:
            # 换另一种改动方式再试一次，避免中文词里没有可替换字时直接放弃。
            candidate = _edit_latin(current, rng) if mutator is _edit_cjk else _edit_cjk(current, rng)
        if candidate and candidate != current:
            current = candidate
            edits += 1
    if edits == 0:
        # 兜底：保证一定有一次肉眼可见但语义不变的偏移。
        forced = _force_edit(current, rng)
        if forced and forced != current:
            current = forced
            edits = 1
    if current == text:
        # 两次改动可能互相抵消（例如把字换走又换回来），再兜一次。
        forced = _force_edit(text, rng)
        if forced and forced != text:
            current = forced
            edits = max(1, edits)
    return current, edits


def _force_edit(text: str, rng: random.Random) -> str | None:
    """没有同音字/英文可用时的兜底改动：相邻字符换位、插空格或重复字符。"""
    if len(text) < 2:
        return None
    strategies = ("swap_adjacent", "space", "double")
    order = list(strategies)
    rng.shuffle(order)
    for strategy in order:
        if strategy == "swap_adjacent":
            idx = rng.randrange(len(text) - 1)
            if text[idx].isspace() or text[idx + 1].isspace():
                continue
            return text[:idx] + text[idx + 1] + text[idx] + text[idx + 2 :]
        if strategy == "space":
            candidates = [i for i, ch in enumerate(text) if ch.isalpha() and i > 0]
            if not candidates:
                continue
            idx = rng.choice(candidates)
            return text[:idx] + " " + text[idx:]
        if strategy == "double":
            candidates = [i for i, ch in enumerate(text) if not ch.isspace()]
            if not candidates:
                continue
            idx = rng.choice(candidates)
            return text[:idx] + text[idx] + text[idx:]
    return None


# --------------------------------------------------------------------------
# 节奏采样
# --------------------------------------------------------------------------


def sample_span(rng: random.Random, low: float, high: float, bias: float = 1.7) -> float:
    """在 [low, high] 内采样一个右偏的时长（秒）。

    均匀随机本身就是机器特征：真人的间隔是“多数偏短、偶尔明显拖长”的右偏分布。
    """
    low = max(0.01, float(low))
    high = max(low, float(high))
    if high <= low:
        return low
    t = rng.random() ** max(1.0, float(bias))
    value = low + (high - low) * t
    # 加一点点高斯微抖动，让同样的 t 也不会重复出现。
    return max(low, min(high, value * rng.gauss(1.0, 0.035)))


def sample_delay(
    rng: random.Random,
    low: float,
    high: float,
    break_probability: float = 0.0,
) -> float:
    """搜索/操作之间的等待时长，带偶发“走神”长停顿。

    长停顿不会无限放大：最多放大到 high 的 2.2 倍，避免一轮搜索被拖成几十分钟。
    """
    value = sample_span(rng, low, high)
    if break_probability > 0 and rng.random() < break_probability:
        value = min(value * rng.uniform(1.4, 2.6), max(high, low) * 2.2)
    return value


def typing_delay(rng: random.Random) -> float:
    """单个字符的输入间隔，模拟真人键盘节奏。"""
    if rng.random() < 0.06:
        return rng.uniform(0.22, 0.62)  # 打字中途想了一下
    return rng.uniform(0.035, 0.17)


# --------------------------------------------------------------------------
# 行为剧本
# --------------------------------------------------------------------------


@dataclass(slots=True)
class SearchBeat:
    """一次搜索的“人类动作剧本”。"""

    query: str
    dwell: float = 8.0
    scroll: int = 2
    hover: int = 1
    click: bool = False
    source: str = "heuristic"

    def to_json(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "dwell": round(float(self.dwell), 2),
            "scroll": int(self.scroll),
            "hover": int(self.hover),
            "click": bool(self.click),
            "source": self.source,
        }


@dataclass(slots=True)
class PlanReport:
    """本轮剧本的来源与消耗，写日志用。"""

    source: str = "legacy"
    cached: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    notes: list[str] = field(default_factory=list)


_SUFFIXES: tuple[str, ...] = (
    "最新消息", "是什么", "怎么用", "推荐", "教程", "对比", "2026",
    "生活小技巧", "常见问题", "经验分享", "指南", "新闻",
)


def _weighted(rng: random.Random, pairs: Sequence[tuple[Any, float]]) -> Any:
    total = sum(weight for _, weight in pairs)
    pick = rng.random() * total
    upto = 0.0
    for value, weight in pairs:
        upto += weight
        if pick <= upto:
            return value
    return pairs[-1][0]


def heuristic_plan(
    queries: Sequence[str],
    count: int,
    cfg: AppConfig,
    rng: random.Random,
    source: str = "heuristic",
) -> list[SearchBeat]:
    """本地生成整轮剧本：查询扰动 + 右偏节奏 + 随机滚动/悬停/点击。"""
    stealth = cfg.stealth
    basic = cfg.basic
    beats: list[SearchBeat] = []
    pool = [q for q in queries if q.strip()] or ["今天有什么新闻"]
    for _ in range(max(0, int(count))):
        base = rng.choice(pool)
        shaped, _edits = jitter_query(base, rng, stealth.query_jitter)
        if rng.random() < 0.55:
            shaped = f"{shaped} {rng.choice(_SUFFIXES)}"
        dwell = sample_delay(
            rng,
            basic.search_delay_min,
            basic.search_delay_max,
            stealth.break_probability,
        )
        beats.append(
            SearchBeat(
                query=shaped,
                dwell=dwell,
                scroll=rng.choices((0, 1, 2, 3, 4), weights=(10, 26, 32, 22, 10))[0],
                hover=rng.choices((0, 1, 2), weights=(40, 42, 18))[0],
                click=rng.random() < stealth.click_result_probability,
                source=source,
            )
        )
    return beats


# --------------------------------------------------------------------------
# 强力防检测：一次调用生成整轮剧本，并做磁盘缓存
# --------------------------------------------------------------------------

PLAN_SYSTEM = (
    "你是真人搜索行为模拟器。只输出 JSON，不要解释。"
    "目标：让下面的搜索过程在节奏、改写和阅读深度上像普通用户，同时不改变搜索意图。"
)

PLAN_USER = (
    "为 Bing 规划 {count} 次搜索。\n"
    "候选主题：{topics}\n"
    "要求：\n"
    "1) q 必须是候选主题的轻微改写（同音/形近字、相邻字母换位、增删一个词），语义保持一致；\n"
    "2) 不要重复完全相同的 q；\n"
    "3) dwell 为停留秒数，取 5–{upper:.0f} 之间的小数，越靠前越短、偶尔一个明显长；\n"
    "4) scroll 为滚动次数 0–4；hover 为悬停结果数 0–2；click 表示是否点开一条结果再返回，最多 2 条为 true；\n"
    "5) 输出格式：{{\"pace\":0.9,\"beats\":[{{\"q\":\"...\",\"dwell\":7.4,\"scroll\":2,\"hover\":1,\"click\":false}}]}}"
)


class StrongPlanner:
    """用大模型“想”一遍人类行为，再把结果缓存下来复用。"""

    def __init__(self, cfg: AppConfig, log: logging.Logger, rng: random.Random) -> None:
        self.cfg = cfg
        self.log = log
        self.rng = rng
        self.stealth: StealthConfig = cfg.stealth
        self.cache_path = cfg.general.state_dir / "stealth" / "plan-cache.json"

    # ---- 缓存 ----

    def _cache_key(self, count: int, queries: Sequence[str]) -> str:
        digest = hashlib.sha256()
        digest.update(str(self.cfg.advanced.model).encode("utf-8"))
        digest.update(b"|")
        digest.update(str(count).encode("utf-8"))
        digest.update(b"|")
        digest.update(str(self.cfg.basic.search_host).encode("utf-8"))
        digest.update(b"|")
        digest.update("\n".join(sorted(queries)[:24]).encode("utf-8"))
        return digest.hexdigest()[:16]

    def _read_cache(self, key: str) -> list[SearchBeat] | None:
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        entry = (raw.get("entries") or {}).get(key)
        if not isinstance(entry, dict):
            return None
        try:
            created = datetime.fromisoformat(str(entry.get("created_at")))
        except ValueError:
            return None
        ttl = timedelta(hours=max(0.0, float(self.stealth.plan_cache_hours)))
        if datetime.now() - created > ttl:
            return None
        beats = _beats_from_payload(entry.get("beats"), source="llm-cache")
        return beats or None

    def _write_cache(self, key: str, beats: Sequence[SearchBeat], usage: dict[str, Any]) -> None:
        entries: dict[str, Any] = {}
        try:
            existing = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if isinstance(existing.get("entries"), dict):
                entries = existing["entries"]
        except (OSError, ValueError):
            entries = {}
        # 只保留最近 20 条，避免文件无限增长。
        entries[key] = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "usage": usage,
            "beats": [beat.to_json() for beat in beats],
        }
        if len(entries) > 20:
            ordered = sorted(
                entries.items(),
                key=lambda item: str(item[1].get("created_at") or ""),
                reverse=True,
            )[:20]
            entries = dict(ordered)
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(
                json.dumps({"entries": entries}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            self.log.debug("写入行为剧本缓存失败：%s", exc)

    # ---- 主入口 ----

    def plan(self, count: int, queries: Sequence[str]) -> tuple[list[SearchBeat], PlanReport]:
        report = PlanReport(source="llm")
        pool = [q.strip() for q in queries if q.strip()]
        if not pool or count <= 0:
            return [], report

        key = self._cache_key(count, pool)
        cached = self._read_cache(key)
        if cached:
            report.source = "llm-cache"
            report.cached = True
            report.notes.append("命中本地剧本缓存，本轮不产生 token 消耗")
            return _refresh_beats(cached, self.cfg, self.rng), report

        if not self.cfg.advanced.api_key:
            report.source = "heuristic"
            report.notes.append("强力防检测已开启但没有 API Key，自动降级为本地人类行为模拟")
            return heuristic_plan(pool, count, self.cfg, self.rng), report

        beats, usage, error = self._call_model(count, pool)
        if error:
            report.source = "heuristic"
            report.notes.append(f"大模型规划失败，已降级：{error}")
            return heuristic_plan(pool, count, self.cfg, self.rng), report

        report.prompt_tokens = int(usage.get("prompt_tokens") or 0)
        report.completion_tokens = int(usage.get("completion_tokens") or 0)
        report.total_tokens = int(
            usage.get("total_tokens")
            or report.prompt_tokens + report.completion_tokens
        )
        report.notes.append(f"一次调用生成 {len(beats)} 条动作，本轮后续不再请求大模型")
        self._write_cache(key, beats, usage)
        return beats, report

    def _call_model(
        self,
        count: int,
        queries: Sequence[str],
    ) -> tuple[list[SearchBeat], dict[str, Any], str]:
        # 延迟导入，避免没装/没配置大模型的用户也要走这条依赖链。
        from .llm import LLMClient

        upper = max(self.cfg.basic.search_delay_max, 6.0)
        topics = "；".join(queries[:12])
        user_prompt = PLAN_USER.format(count=count, topics=topics, upper=upper)
        messages = [
            {"role": "system", "content": PLAN_SYSTEM},
            {"role": "user", "content": user_prompt},
        ]
        try:
            client = LLMClient(self.cfg.advanced, max_tokens=self.stealth.plan_max_tokens)
            raw = client.complete(messages)
            usage = dict(getattr(client, "last_usage", {}) or {})
            payload = LLMClient.parse_json_object(raw)
        except Exception as exc:  # noqa: BLE001 - 任何失败都走降级
            return [], {}, str(exc)[:200]

        beats = _beats_from_payload(payload.get("beats"), source="llm")
        if not beats:
            return [], usage, "模型没有给出可用的 beats"
        beats = _fit_count(beats, count, queries, self.cfg, self.rng)
        return beats, usage, ""


def _beats_from_payload(payload: Any, source: str) -> list[SearchBeat]:
    """把模型/缓存里的宽松 JSON 收敛成可信的 SearchBeat 列表。"""
    if not isinstance(payload, list):
        return []
    beats: list[SearchBeat] = []
    seen: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        query = str(item.get("q") or item.get("query") or "").strip()
        if not query or len(query) > 90:
            continue
        if query in seen:
            continue
        seen.add(query)
        try:
            dwell = float(item.get("dwell", 8.0))
        except (TypeError, ValueError):
            dwell = 8.0
        try:
            scroll = int(item.get("scroll", 2))
        except (TypeError, ValueError):
            scroll = 2
        try:
            hover = int(item.get("hover", 1))
        except (TypeError, ValueError):
            hover = 1
        click = item.get("click")
        if isinstance(click, str):
            click = click.strip().lower() in {"1", "true", "yes", "是"}
        beats.append(
            SearchBeat(
                query=query,
                dwell=max(3.0, min(60.0, dwell)),
                scroll=max(0, min(5, scroll)),
                hover=max(0, min(3, hover)),
                click=bool(click),
                source=source,
            )
        )
    return beats


def _fit_count(
    beats: list[SearchBeat],
    count: int,
    queries: Sequence[str],
    cfg: AppConfig,
    rng: random.Random,
) -> list[SearchBeat]:
    """让剧本条数与实际需要一致：多了截断，少了用本地剧本补齐。"""
    count = max(0, int(count))
    if len(beats) >= count:
        return beats[:count]
    padding = heuristic_plan(queries, count - len(beats), cfg, rng, source="heuristic-fill")
    return beats + padding


def _refresh_beats(
    beats: Sequence[SearchBeat],
    cfg: AppConfig,
    rng: random.Random,
) -> list[SearchBeat]:
    """缓存命中时再抖一次：同样的剧本也不能每次跑出一模一样的时间线。"""
    refreshed: list[SearchBeat] = []
    for beat in beats:
        query, _ = jitter_query(beat.query, rng, cfg.stealth.query_jitter)
        refreshed.append(
            SearchBeat(
                query=query,
                dwell=max(3.0, min(60.0, beat.dwell * rng.uniform(0.82, 1.22))),
                scroll=beat.scroll,
                hover=beat.hover,
                click=beat.click,
                source="llm-cache",
            )
        )
    return refreshed


# --------------------------------------------------------------------------
# 执行器
# --------------------------------------------------------------------------

_SEARCH_BOX_SELECTORS: tuple[str, ...] = (
    "#sb_form_q",
    "input[name='q']",
    "textarea[name='q']",
    "input[type='search']",
    "[role='searchbox']",
    "#searchbox",
)

_RESULT_LINK_SELECTORS: tuple[str, ...] = (
    "#b_results h2 a",
    "#b_results .b_algo a",
    "li.b_algo h2 a",
)

_DEFAULT_QUERIES: tuple[str, ...] = (
    "今天有什么新闻",
    "Windows 使用技巧",
    "人工智能 最新进展",
    "如何提高工作效率",
    "本周天气",
    "健康饮食 建议",
)


class SearchRunner:
    """按“人类剧本”执行一轮搜索，基础/强力两种模式共用同一套执行器。"""

    def __init__(
        self,
        session: BrowserSession,
        cfg: AppConfig,
        log: logging.Logger | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.session = session
        self.cfg = cfg
        self.log = log or logging.getLogger("rewards_bot.stealth")
        self.rng = rng or random.Random()
        self.stealth: StealthConfig = cfg.stealth
        host = cfg.basic.search_host
        if not host.startswith(("http://", "https://")):
            host = "https://" + host
        self.host = host.rstrip("/")
        self.host_name = (urlparse(self.host).hostname or "www.bing.com").lower()
        self.last_report = PlanReport()

    # ---- 对外 ----

    def run(self, count: int, queries: Sequence[str] | None = None) -> int:
        if count <= 0:
            return 0
        pool = list(queries or _DEFAULT_QUERIES)
        if self.stealth.basic_enabled or self.stealth.strong_enabled:
            beats = self._plan(count, pool)
        else:
            return self._run_legacy(count, pool)
        completed = 0
        for index, beat in enumerate(beats, 1):
            if self.session.is_login_page():
                raise LoginRequired("执行搜索任务时登录失效，请先运行 --login。")
            try:
                self._perform(index, len(beats), beat)
                completed += 1
            except LoginRequired:
                raise
            except Exception as exc:  # noqa: BLE001 - 单次失败不该终止整轮
                self.log.warning(
                    "搜索 %s/%s 失败：%s",
                    index,
                    len(beats),
                    str(exc).splitlines()[0][:180],
                )
                try:
                    self.session.goto(self.host)
                except Exception:
                    pass
                time.sleep(sample_span(self.rng, 1.5, 4.0))
        self.log.info(
            "搜索任务结束：完成 %s/%s 次（剧本来源 %s）",
            completed,
            len(beats),
            self.last_report.source,
        )
        return completed

    # ---- 剧本 ----

    def _plan(self, count: int, pool: Sequence[str]) -> list[SearchBeat]:
        if self.stealth.strong_enabled:
            planner = StrongPlanner(self.cfg, self.log, self.rng)
            beats, report = planner.plan(count, pool)
            self.last_report = report
            for note in report.notes:
                self.log.info("强力防检测：%s", note)
            if report.total_tokens:
                self.log.info(
                    "强力防检测本轮 token 消耗：prompt=%s completion=%s total=%s",
                    report.prompt_tokens,
                    report.completion_tokens,
                    report.total_tokens,
                )
            if beats:
                self._dump_plan(beats, report)
                return beats
            self.log.warning("强力防检测没有拿到剧本，退回本地人类行为模拟。")
        beats = heuristic_plan(pool, count, self.cfg, self.rng)
        self.last_report = PlanReport(source="heuristic", notes=["本地人类行为模拟"])
        self._dump_plan(beats, self.last_report)
        return beats

    def _dump_plan(self, beats: Sequence[SearchBeat], report: PlanReport) -> None:
        path = self.cfg.general.state_dir / "stealth" / "last-plan.json"
        payload = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source": report.source,
            "cached": report.cached,
            "tokens": {
                "prompt": report.prompt_tokens,
                "completion": report.completion_tokens,
                "total": report.total_tokens,
            },
            "beats": [beat.to_json() for beat in beats],
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            self.log.debug("保存本轮搜索剧本失败：%s", exc)

    # ---- 单次搜索 ----

    def _perform(self, index: int, total: int, beat: SearchBeat) -> None:
        page = self.session.current_page
        if self.stealth.typing_enabled or self.stealth.mouse_jitter:
            self._prepare_home(page)
        typed = False
        if self.stealth.typing_enabled:
            typed = self._type_query(page, beat.query)
        if typed:
            page.keyboard.press("Enter")
            self._wait_results(page)
        else:
            url = f"{self.host}/search?q={quote_plus(beat.query)}&form=QBLH"
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(int(sample_span(self.rng, 500, 1_200)))
        self.log.info(
            "搜索 %s/%s：%s | 停留 %.1fs | 滚动 %s 次 | 悬停 %s | 点击结果 %s | 来源 %s",
            index,
            total,
            beat.query[:60],
            beat.dwell,
            beat.scroll,
            beat.hover,
            "是" if beat.click else "否",
            beat.source,
        )
        self._read_results(page, beat)

    def _prepare_home(self, page) -> None:
        """回到 Bing 首页，像真人那样从搜索框开始，而不是直接怼 URL。"""
        current = (urlparse(page.url).hostname or "").lower()
        if current != self.host_name:
            self.session.goto(self.host + "/")
            page = self.session.current_page
        try:
            page.mouse.move(
                self.rng.randint(220, 1_180),
                self.rng.randint(140, 760),
                steps=self.rng.randint(8, 26),
            )
        except PlaywrightError:
            pass
        self._pause(page, sample_span(self.rng, 0.6, 1.9))
        if self.stealth.basic_enabled:
            try:
                page.mouse.wheel(0, self.rng.randint(-120, 260))
            except PlaywrightError:
                pass
            self._pause(page, sample_span(self.rng, 0.25, 0.8))

    def _type_query(self, page, query: str) -> bool:
        locator = None
        for selector in _SEARCH_BOX_SELECTORS:
            try:
                candidate = page.locator(selector).first
                if candidate.count() == 0:
                    continue
                if not candidate.is_visible(timeout=800):
                    continue
                locator = candidate
                break
            except PlaywrightError:
                continue
        if locator is None:
            self.log.debug("找不到搜索框，退回直接跳转搜索 URL。")
            return False

        try:
            box = locator.bounding_box()
            if box:
                page.mouse.move(
                    box["x"] + box["width"] * self.rng.uniform(0.25, 0.75),
                    box["y"] + box["height"] * self.rng.uniform(0.3, 0.7),
                    steps=self.rng.randint(9, 22),
                )
                self._pause(page, sample_span(self.rng, 0.08, 0.28))
                page.mouse.down()
                self._pause(page, sample_span(self.rng, 0.05, 0.14))
                page.mouse.up()
            locator.click(timeout=3_000)
        except PlaywrightError as exc:
            self.log.debug("点击搜索框失败：%s", str(exc).splitlines()[0][:120])
        try:
            locator.fill("")
        except PlaywrightError:
            pass

        typo_done = False
        for char in query:
            if not typo_done and char.isalpha() and self.rng.random() < 0.06:
                typo_done = True
                wrong = self._wrong_char(char)
                if wrong:
                    page.keyboard.type(wrong)
                    self._pause(page, sample_span(self.rng, 0.10, 0.34))
                    page.keyboard.press("Backspace")
                    self._pause(page, sample_span(self.rng, 0.06, 0.20))
            page.keyboard.type(char)
            self._pause(page, typing_delay(self.rng))
        self._pause(page, sample_span(self.rng, 0.18, 0.65))
        return True

    def _wrong_char(self, char: str) -> str | None:
        lower = char.lower()
        neighbours = _KEY_NEIGHBOURS.get(lower)
        if not neighbours:
            return None
        wrong = self.rng.choice(neighbours)
        return wrong.upper() if char.isupper() else wrong

    def _wait_results(self, page) -> None:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=25_000)
        except Exception:
            pass
        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            try:
                if page.locator("#b_results").count() > 0:
                    break
            except PlaywrightError:
                break
            self._pause(page, 0.25)
        self._pause(page, sample_span(self.rng, 0.4, 1.3))

    def _read_results(self, page, beat: SearchBeat) -> None:
        """按剧本停留、滚动、悬停，偶尔点开一条结果再返回。"""
        self._pause_in_chunks(page, beat.dwell)
        for _ in range(max(0, beat.scroll)):
            try:
                page.mouse.wheel(0, self.rng.randint(180, 620))
            except PlaywrightError:
                break
            self._pause(page, sample_span(self.rng, 0.35, 1.6))
        for _ in range(max(0, beat.hover)):
            self._hover_result(page)
        if beat.click and self.cfg.stealth.click_result_probability > 0:
            if self.rng.random() < min(1.0, self.cfg.stealth.click_result_probability * 2.0):
                self._open_result(page)

    def _hover_result(self, page) -> None:
        locator = self._result_locator(page)
        if locator is None:
            return
        try:
            box = locator.bounding_box()
            if not box:
                return
            page.mouse.move(
                box["x"] + box["width"] * self.rng.uniform(0.2, 0.8),
                box["y"] + box["height"] * self.rng.uniform(0.2, 0.8),
                steps=self.rng.randint(7, 18),
            )
            self._pause(page, sample_span(self.rng, 0.4, 1.7))
        except PlaywrightError:
            pass

    def _open_result(self, page) -> None:
        locator = self._result_locator(page)
        if locator is None:
            return
        try:
            href = locator.get_attribute("href") or ""
            if not href.startswith(("http://", "https://")):
                return
            locator.click(timeout=6_000)
            self._pause(page, sample_span(self.rng, 1.6, 5.5))
            self.adopt_pages()
            page = self.session.current_page
            try:
                page.mouse.wheel(0, self.rng.randint(150, 520))
            except PlaywrightError:
                pass
            self._pause(page, sample_span(self.rng, 0.6, 2.2))
            page.go_back(wait_until="domcontentloaded", timeout=20_000)
            self._pause(page, sample_span(self.rng, 0.5, 1.4))
        except Exception as exc:  # noqa: BLE001
            self.log.debug("点开搜索结果后返回失败：%s", str(exc).splitlines()[0][:160])
            try:
                self.session.goto(self.host + "/")
            except Exception:
                pass

    def adopt_pages(self) -> None:
        try:
            self.session.adopt_new_pages()
        except Exception:
            pass

    def _result_locator(self, page):
        for selector in _RESULT_LINK_SELECTORS:
            try:
                locator = page.locator(selector)
                count = locator.count()
                if count == 0:
                    continue
                return locator.nth(self.rng.randrange(min(count, 7)))
            except PlaywrightError:
                continue
        return None

    # ---- 工具 ----

    def _pause(self, page, seconds: float) -> None:
        try:
            page.wait_for_timeout(max(1, int(seconds * 1000)))
        except PlaywrightError:
            time.sleep(max(0.01, seconds))

    def _pause_in_chunks(self, page, seconds: float) -> None:
        """把一次长停留拆成几段，中间穿插鼠标小动作。"""
        remaining = max(0.2, float(seconds))
        chunks = max(1, min(5, int(seconds // 1.6) + 1))
        for _ in range(chunks):
            part = remaining / chunks
            self._pause(page, part)
            if self.stealth.mouse_jitter:
                try:
                    page.mouse.move(
                        self.rng.randint(260, 1_200),
                        self.rng.randint(180, 780),
                        steps=self.rng.randint(5, 14),
                    )
                except PlaywrightError:
                    pass

    def _run_legacy(self, count: int, pool: Sequence[str]) -> int:
        """两种防检测都关闭时，保持原始行为（均匀随机间隔 + 直接跳 URL）。"""
        self.last_report = PlanReport(source="legacy", notes=["防检测未启用"])
        self.log.info("开始可选搜索任务：%s 次，搜索主机 %s（防检测未启用）", count, self.host)
        completed = 0
        rng = self.rng
        for index in range(1, count + 1):
            if self.session.is_login_page():
                raise LoginRequired("执行搜索任务时登录失效，请先运行 --login。")
            query = rng.choice(list(pool))
            if rng.random() < 0.6:
                query = f"{query} {rng.choice(_SUFFIXES)}"
            url = f"{self.host}/search?q={quote_plus(query)}&form=QBLH"
            try:
                page = self.session.current_page
                page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                delay = rng.uniform(
                    self.cfg.basic.search_delay_min, self.cfg.basic.search_delay_max
                )
                page.wait_for_timeout(int(delay * 1000))
                try:
                    page.mouse.wheel(0, rng.randint(120, 700))
                    page.wait_for_timeout(rng.randint(400, 900))
                except PlaywrightError:
                    pass
                completed += 1
                self.log.info("搜索 %s/%s：%s（等待 %.1f 秒）", index, count, query[:60], delay)
            except Exception as exc:  # noqa: BLE001
                self.log.warning(
                    "搜索 %s/%s 失败：%s",
                    index,
                    count,
                    str(exc).splitlines()[0][:180],
                )
                try:
                    self.session.goto(self.cfg.general.url)
                except Exception:
                    pass
                time.sleep(2)
        self.log.info("搜索任务结束：完成 %s/%s 次。", completed, count)
        return completed


def build_searcher(
    session: BrowserSession,
    cfg: AppConfig,
    log: logging.Logger | None = None,
) -> SearchRunner:
    """工厂：按配置决定用哪种强度的防检测（执行器本身是同一套）。"""
    return SearchRunner(session, cfg, log=log)


def describe_modes(cfg: StealthConfig) -> str:
    """给日志/UI 用的一行摘要。"""
    if cfg.strong_enabled:
        return "强力防检测（大模型规划 + 本地抖动）"
    if cfg.basic_enabled:
        return "基础防检测（查询扰动 + 人类化节奏）"
    return "关闭"
