from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .browser import BrowserSession
from .config import AppConfig
from .dom import is_rewards_home_url

# 积分证据必须来自真实页面：余额、未完成任务卡片上的 +N，都只读取当前 DOM。
# 读不到就返回空值，由调用方标记为“未确认”，绝不使用本地估值补齐。
POINTS_SNAPSHOT_JS = r"""
() => {
  const norm = (value) => (value || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    if (rect.width < 4 || rect.height < 4) return false;
    const style = getComputedStyle(el);
    return style.visibility !== 'hidden' && style.display !== 'none' && Number(style.opacity || '1') > 0.05;
  };
  const parseNumber = (text) => {
    const raw = norm(text);
    if (!raw || raw.length > 20) return null;
    const grouped = /^\d{1,3}(?:[,，\s\u00a0']\d{3})+$/.test(raw);
    const plain = /^\d{1,7}$/.test(raw);
    if (!grouped && !plain) return null;
    const digits = raw.replace(/[,，\s\u00a0']/g, '');
    if (!/^\d{1,7}$/.test(digits)) return null;
    return { value: Number(digits), raw: raw };
  };

  const sectionOf = (el) => {
    const section = el.closest(
      'mee-rewards-daily-set-section, mee-rewards-more-activities-section, ' +
      '[id*="dailyset" i], [id*="daily" i], [id*="moreactivit" i], ' +
      '[id*="weekly" i], [id*="monthly" i], ' +
      '[class*="dailyset" i], [class*="daily" i], [class*="more-activit" i], ' +
      '[class*="moreActivit" i], [class*="weekly" i], [class*="monthly" i], section'
    );
    if (!section) return 'unknown';
    let signature = '';
    try {
      signature = (
        (section.id || '') + ' ' +
        (typeof section.className === 'string' ? section.className : '') + ' ' +
        (section.tagName || '')
      ).toLowerCase();
    } catch (err) {
      return 'unknown';
    }
    if (/month|monthly|每月/.test(signature)) return 'monthly';
    if (/week|weekly|每周/.test(signature)) return 'weekly';
    if (/more|更多/.test(signature)) return 'more';
    if (/daily|每日/.test(signature)) return 'daily';
    return 'unknown';
  };

  // 余额候选打分：必须有奖章图标、明确的 balance/points 标签或顶部栏上下文，
  // 单纯一个数字（任务徽标、日期、进度）不会被当成账户余额。
  const balanceContextScore = (el) => {
    let score = 0;
    let ctx = el;
    for (let depth = 0; ctx && depth < 5; depth += 1, ctx = ctx.parentElement) {
      let label = '';
      try {
        label = norm(
          (ctx.getAttribute('aria-label') || '') + ' ' +
          (ctx.getAttribute('title') || '') + ' ' +
          (typeof ctx.className === 'string' ? ctx.className : '')
        );
      } catch (err) {
        label = '';
      }
      if (/balance|available.?points|积分余额|積分餘額/i.test(label)) {
        score = Math.max(score, 9);
      } else if (/points|score|积分|積分|點數|点数/i.test(label)) {
        score = Math.max(score, 5);
      }
      try {
        if (ctx.tagName === 'HEADER' || ctx.getAttribute('role') === 'banner') score += 3;
        if (ctx.tagName === 'NAV' || ctx.getAttribute('role') === 'navigation') score += 2;
      } catch (err) {}
      let media = [];
      try {
        media = Array.from(ctx.querySelectorAll('img, svg'));
      } catch (err) {
        media = [];
      }
      for (const node of media) {
        const signature =
          (node.getAttribute('src') || '') + ' ' +
          (node.getAttribute('alt') || '') + ' ' +
          (node.getAttribute('aria-label') || '');
        if (/medal|勋章|獎章|奖章|points|积分|積分|omr/i.test(signature)) {
          score += 6;
          break;
        }
      }
    }
    try {
      const cardish = el.closest('mee-card, [class*="card" i], li, article');
      if (cardish && !el.closest('header, [role="banner"]')) score -= 10;
    } catch (err) {}
    return score;
  };

  let bestBalance = null;
  let balanceCandidates = 0;
  const numericNodes = document.querySelectorAll('p, span, strong, b, div, a, button');
  for (const el of numericNodes) {
    if (!visible(el)) continue;
    let text = '';
    try {
      text = norm(el.innerText || el.getAttribute('aria-label') || '');
    } catch (err) {
      continue;
    }
    const parsed = parseNumber(text);
    if (!parsed) continue;
    let sameChild = false;
    try {
      sameChild = Array.from(el.children).some(
        (child) => norm(child.innerText || '') === text
      );
    } catch (err) {}
    if (sameChild) continue;
    const score = balanceContextScore(el);
    if (score < 6) continue;
    if (parsed.value > 1000000) continue;
    let top = 0;
    try {
      top = el.getBoundingClientRect().top;
    } catch (err) {}
    balanceCandidates += 1;
    const candidate = { value: parsed.value, raw: parsed.raw, score: score, top: top };
    if (
      !bestBalance ||
      candidate.score > bestBalance.score ||
      (candidate.score === bestBalance.score && candidate.top < bestBalance.top)
    ) {
      bestBalance = candidate;
    }
  }

  const badgeRe = /^[+＋]\s*(\d{1,4})(?:\s*(?:分|积分|積分|points?|pts?))?$/i;
  const riskyRe = /(兑换|兌換|redeem|购买|購買|购物|購物|shop|catalog|payment|支付|订阅|訂閱)/i;
  const doneRe = /(已完成|已领取|已領取|completed|claimed|已兑换|已兌換)/i;
  const cardOf = (el) => el.closest('mee-card, [class*="card" i], li, article');
  const countedCards = new Set();
  const cardPoints = [];
  for (const el of document.querySelectorAll('p, span, strong, b, div')) {
    if (!visible(el)) continue;
    let text = '';
    try {
      text = norm(el.innerText || '');
    } catch (err) {
      continue;
    }
    const match = text.match(badgeRe);
    if (!match) continue;
    let sameChild = false;
    try {
      sameChild = Array.from(el.children).some(
        (child) => badgeRe.test(norm(child.innerText || ''))
      );
    } catch (err) {}
    if (sameChild) continue;
    const card = cardOf(el);
    if (!card || !visible(card)) continue;
    if (card.closest('header, nav, footer, [role="banner"], [role="navigation"], [role="contentinfo"]')) continue;
    if (countedCards.has(card)) continue;
    let cardText = '';
    try {
      cardText = norm(card.innerText || '').slice(0, 600);
    } catch (err) {
      continue;
    }
    if (riskyRe.test(cardText) || doneRe.test(cardText)) continue;
    const actionable = card.querySelector('a[href], button, [role="button"]');
    if (!actionable) continue;
    let href = '';
    try {
      href = actionable.href || '';
    } catch (err) {}
    if (href && !/bing\.com|rewards\.bing\.com/i.test(href)) continue;
    const points = Number(match[1]);
    if (!Number.isFinite(points) || points <= 0 || points > 2000) continue;
    countedCards.add(card);
    cardPoints.push({ points: points, section: sectionOf(card) });
  }

  const sectionTotals = {};
  let remainingPoints = 0;
  for (const item of cardPoints) {
    remainingPoints += item.points;
    sectionTotals[item.section] = (sectionTotals[item.section] || 0) + item.points;
  }
  let hasScope = false;
  try {
    hasScope = cardPoints.length > 0 || document.querySelectorAll(
      'mee-card, mee-rewards-daily-set-section, mee-rewards-more-activities-section'
    ).length > 0;
  } catch (err) {
    hasScope = cardPoints.length > 0;
  }
  const remaining = hasScope
    ? {
        points: remainingPoints,
        task_count: cardPoints.length,
        sections: sectionTotals,
        source: 'visible_task_cards'
      }
    : null;

  return {
    url: location.href,
    balance: bestBalance
      ? { value: bestBalance.value, raw: bestBalance.raw, source: 'page_header' }
      : null,
    balance_candidates: balanceCandidates,
    remaining: remaining
  };
}
"""

# 仅用于读取“今天还能获得”时加载懒加载卡片；逐任务余额截图不需要全页滚动。
POINTS_SCROLL_JS = r"""
async () => {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const currentHeight = () =>
    Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
  const step = Math.max(320, Math.round(window.innerHeight * 0.8));
  let height = currentHeight();
  let y = 0;
  for (let i = 0; i < 24; i += 1) {
    window.scrollTo(0, y);
    await sleep(110);
    if (y >= height + step) break;
    y += step;
    height = Math.max(height, currentHeight());
  }
  window.scrollTo(0, 0);
  await sleep(320);
}
"""

DAY_TASK_STATUSES = {
    "confirmed",
    "unchanged",
    "decreased",
    "missing_balance",
    "missing_screenshot",
}


def _now_iso(tz: ZoneInfo | None = None) -> str:
    if tz is None:
        return datetime.now().astimezone().isoformat(timespec="seconds")
    return datetime.now(tz).isoformat(timespec="seconds")


def _day_key(tz: ZoneInfo | None = None) -> str:
    if tz is None:
        return datetime.now().astimezone().date().isoformat()
    return datetime.now(tz).date().isoformat()


def _zone(timezone: str) -> ZoneInfo | None:
    try:
        return ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _as_int(value: Any, *, minimum: int = 0, maximum: int = 100_000_000) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number < minimum or number > maximum:
        return None
    return number


def _text(value: Any, limit: int = 160) -> str:
    return str(value or "").replace("\x00", "").strip()[:limit]


def normalize_snapshot(raw: Any) -> dict[str, Any]:
    """把浏览器返回值收敛成固定结构，任何异常字段都当作缺失。"""

    snapshot: dict[str, Any] = {
        "balance": None,
        "remaining": None,
        "url": "",
        "at": "",
        "shot": None,
    }
    if not isinstance(raw, dict):
        return snapshot
    snapshot["url"] = _text(raw.get("url"), 300)

    balance_raw = raw.get("balance")
    if isinstance(balance_raw, dict):
        points = _as_int(balance_raw.get("value"))
        if points is not None:
            snapshot["balance"] = {
                "points": points,
                "raw": _text(balance_raw.get("raw"), 32),
                "source": _text(balance_raw.get("source"), 40) or "page_header",
            }

    remaining_raw = raw.get("remaining")
    if isinstance(remaining_raw, dict):
        points = _as_int(remaining_raw.get("points"))
        task_count = _as_int(remaining_raw.get("task_count"))
        if points is not None and task_count is not None:
            sections: dict[str, int] = {}
            sections_raw = remaining_raw.get("sections")
            if isinstance(sections_raw, dict):
                for key, value in list(sections_raw.items())[:8]:
                    section_points = _as_int(value)
                    if section_points is None:
                        continue
                    name = _text(key, 20) or "unknown"
                    sections[name] = section_points
            snapshot["remaining"] = {
                "points": points,
                "task_count": task_count,
                "sections": sections,
                "source": _text(remaining_raw.get("source"), 40)
                or "visible_task_cards",
            }
    return snapshot


def evaluate_task_evidence(
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    before_shot: Any,
    after_shot: Any,
) -> dict[str, Any]:
    """按“两个余额读数 + 两张截图”判定单任务收益。

    只有 after > before 且开始、结束截图都存在时才标记 confirmed；
    其余情况保留读数，但绝不把差额当作本次任务收益。
    """

    before_points = None
    after_points = None
    if isinstance(before, dict) and isinstance(before.get("balance"), dict):
        before_points = _as_int(before["balance"].get("points"))
    if isinstance(after, dict) and isinstance(after.get("balance"), dict):
        after_points = _as_int(after["balance"].get("points"))
    has_shots = bool(before_shot) and bool(after_shot)

    if before_points is None or after_points is None:
        return {
            "status": "missing_balance",
            "before": before_points,
            "after": after_points,
            "delta": None,
            "has_shots": has_shots,
        }

    delta = after_points - before_points
    if not has_shots:
        status = "missing_screenshot"
    elif delta > 0:
        status = "confirmed"
    elif delta == 0:
        status = "unchanged"
    else:
        status = "decreased"
    return {
        "status": status,
        "before": before_points,
        "after": after_points,
        "delta": delta,
        "has_shots": has_shots,
    }


def _shot_ref(path: Path | None, cfg: AppConfig) -> dict[str, str] | None:
    if path is None:
        return None
    try:
        resolved = Path(path).resolve()
        root = (cfg.general.state_dir / "screenshots").resolve()
        if root not in resolved.parents or not resolved.is_file():
            return None
        return {"run": resolved.parent.name, "name": resolved.name}
    except OSError:
        return None


def _shot_payload(ref: Any) -> dict[str, str] | None:
    if not isinstance(ref, dict):
        return None
    run_id = _text(ref.get("run"), 64)
    name = _text(ref.get("name"), 128)
    if not run_id or not name or not name.endswith(".png"):
        return None
    return {
        "run": run_id,
        "name": name,
        "url": f"/api/screenshots/{quote(run_id)}/{quote(name)}",
    }


def _shot_name(ref: Any) -> str:
    if not isinstance(ref, dict):
        return ""
    return _text(ref.get("name"), 128)


def _format_points(value: int | None) -> str:
    if value is None:
        return "—"
    return f"{value:,}"


class PointsLedger:
    """把读数与截图索引保存在 state/points/ledger.json，只留在本机。"""

    VERSION = 1
    KEEP_DAYS = 30
    KEEP_RUNS = 40
    KEEP_READINGS = 120

    def __init__(self, state_dir: Path, timezone: str = "Asia/Shanghai") -> None:
        self.state_dir = Path(state_dir)
        self.path = self.state_dir / "points" / "ledger.json"
        self.timezone = timezone
        self.tz = _zone(timezone)
        self.log = logging.getLogger("rewards_bot.points")
        self._lock = threading.RLock()

    def _empty(self) -> dict[str, Any]:
        return {"version": self.VERSION, "days": {}, "runs": []}

    def _load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return self._empty()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.log.warning("积分账本读取失败，将使用空账本：%s", exc)
            return self._empty()
        if not isinstance(raw, dict):
            return self._empty()
        days = raw.get("days")
        runs = raw.get("runs")
        return {
            "version": self.VERSION,
            "days": days if isinstance(days, dict) else {},
            "runs": runs if isinstance(runs, list) else [],
        }

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self.path)

    def _prune(self, data: dict[str, Any]) -> None:
        days = data.get("days")
        if isinstance(days, dict):
            keep = sorted(days.keys())[-self.KEEP_DAYS :]
            for key in list(days.keys()):
                if key not in keep:
                    days.pop(key, None)
            for record in days.values():
                if not isinstance(record, dict):
                    continue
                readings = record.get("readings")
                if isinstance(readings, list) and len(readings) > self.KEEP_READINGS:
                    record["readings"] = readings[-self.KEEP_READINGS :]
        runs = data.get("runs")
        if isinstance(runs, list) and len(runs) > self.KEEP_RUNS:
            data["runs"] = runs[-self.KEEP_RUNS :]

    def record_reading(
        self,
        phase: str,
        snapshot: dict[str, Any],
        run_id: str,
    ) -> None:
        if not isinstance(snapshot, dict):
            return
        if snapshot.get("balance") is None and snapshot.get("remaining") is None:
            # 没有任何读数时不写空记录，避免把旧值覆盖掉。
            return
        with self._lock:
            data = self._load()
            today = _day_key(self.tz)
            day = data["days"].setdefault(today, {})
            if not isinstance(day, dict):
                day = {}
                data["days"][today] = day
            readings = day.setdefault("readings", [])
            if not isinstance(readings, list):
                readings = []
                day["readings"] = readings
            readings.append(
                {
                    "phase": _text(phase, 20),
                    "run_id": _text(run_id, 64),
                    "at": _text(snapshot.get("at"), 40) or _now_iso(self.tz),
                    "balance": snapshot.get("balance"),
                    "remaining": snapshot.get("remaining"),
                    "shot": snapshot.get("shot"),
                }
            )
            self._prune(data)
            self._save(data)

    def record_task(self, record: dict[str, Any]) -> None:
        with self._lock:
            data = self._load()
            today = _day_key(self.tz)
            day = data["days"].setdefault(today, {})
            if not isinstance(day, dict):
                day = {}
                data["days"][today] = day
            tasks = day.setdefault("tasks", [])
            if not isinstance(tasks, list):
                tasks = []
                day["tasks"] = tasks
            tasks.append(record)
            self._prune(data)
            self._save(data)

    def record_run(self, record: dict[str, Any]) -> None:
        with self._lock:
            data = self._load()
            runs = data.setdefault("runs", [])
            if not isinstance(runs, list):
                runs = []
                data["runs"] = runs
            runs.append(record)
            self._prune(data)
            self._save(data)

    def summary(self) -> dict[str, Any]:
        with self._lock:
            data = self._load()
        today = _day_key(self.tz)
        day = data.get("days", {}).get(today)
        if not isinstance(day, dict):
            day = {}
        tasks = [item for item in day.get("tasks", []) if isinstance(item, dict)]
        readings = [
            item for item in day.get("readings", []) if isinstance(item, dict)
        ]

        confirmed_tasks = [item for item in tasks if item.get("status") == "confirmed"]
        today_confirmed = 0
        for item in confirmed_tasks:
            delta = _as_int(item.get("delta"))
            if delta is not None and delta > 0:
                today_confirmed += delta
        unconfirmed_count = len(tasks) - len(confirmed_tasks)

        latest_balance = None
        latest_balance_at = None
        latest_balance_shot = None
        latest_remaining = None
        latest_remaining_at = None
        latest_remaining_shot = None
        first_balance = None
        first_balance_at = None
        last_balance = None
        last_balance_at = None

        for reading in readings:
            balance = reading.get("balance")
            if isinstance(balance, dict):
                points = _as_int(balance.get("points"))
                if points is not None:
                    at = _text(reading.get("at"), 40)
                    shot = _shot_payload(reading.get("shot"))
                    if first_balance is None:
                        first_balance = points
                        first_balance_at = at
                    last_balance = points
                    last_balance_at = at
                    latest_balance = points
                    latest_balance_at = at
                    latest_balance_shot = shot
            remaining = reading.get("remaining")
            if isinstance(remaining, dict):
                points = _as_int(remaining.get("points"))
                if points is not None:
                    latest_remaining = {
                        "points": points,
                        "task_count": _as_int(remaining.get("task_count")) or 0,
                        "sections": remaining.get("sections")
                        if isinstance(remaining.get("sections"), dict)
                        else {},
                        "source": _text(remaining.get("source"), 40)
                        or "visible_task_cards",
                    }
                    latest_remaining_at = _text(reading.get("at"), 40)
                    latest_remaining_shot = _shot_payload(reading.get("shot"))

        # 账本里还没有读数时，退回使用最后一个任务的结束读数（同样是真实值）。
        if latest_balance is None:
            for task in reversed(tasks):
                points = _as_int(task.get("after"))
                if points is None:
                    continue
                latest_balance = points
                latest_balance_at = _text(task.get("at"), 40)
                latest_balance_shot = _shot_payload(task.get("after_shot"))
                if last_balance is None:
                    last_balance = points
                    last_balance_at = latest_balance_at
                break

        net_change = None
        if first_balance is not None and last_balance is not None:
            net_change = last_balance - first_balance

        runs = [item for item in data.get("runs", []) if isinstance(item, dict)]
        last_run = None
        if runs:
            last_run = self._run_payload(runs[-1])

        updated_at = latest_balance_at or latest_remaining_at
        if tasks:
            updated_at = _text(tasks[-1].get("at"), 40) or updated_at

        return {
            "available": bool(tasks or readings or runs),
            "today": today,
            "balance": (
                {
                    "points": latest_balance,
                    "at": latest_balance_at,
                    "shot": latest_balance_shot,
                }
                if latest_balance is not None
                else None
            ),
            "remaining": (
                {
                    **latest_remaining,
                    "at": latest_remaining_at,
                    "shot": latest_remaining_shot,
                }
                if latest_remaining is not None
                else None
            ),
            "today_confirmed": today_confirmed,
            "today_confirmed_tasks": len(confirmed_tasks),
            "today_unconfirmed_tasks": unconfirmed_count,
            "today_net": net_change,
            "today_first_balance": first_balance,
            "today_last_balance": last_balance,
            "last_run": last_run,
            "updated_at": updated_at,
        }

    def _task_payload(self, task: dict[str, Any]) -> dict[str, Any]:
        status = _text(task.get("status"), 24)
        if status not in DAY_TASK_STATUSES:
            status = "missing_balance"
        return {
            "at": _text(task.get("at"), 40),
            "label": _text(task.get("label"), 150),
            "index": _as_int(task.get("index")) or 0,
            "status": status,
            "before": _as_int(task.get("before")),
            "after": _as_int(task.get("after")),
            "delta": _as_int(task.get("delta"), minimum=-100_000),
            "note": _text(task.get("note"), 160),
            "before_shot": _shot_payload(task.get("before_shot")),
            "after_shot": _shot_payload(task.get("after_shot")),
        }

    def _run_payload(self, run: dict[str, Any]) -> dict[str, Any]:
        tasks = [item for item in run.get("tasks", []) if isinstance(item, dict)]
        return {
            "id": _text(run.get("id"), 64),
            "started_at": _text(run.get("started_at"), 40),
            "finished_at": _text(run.get("finished_at"), 40),
            "mode": _text(run.get("mode"), 20),
            "before": _as_int(run.get("before")),
            "after": _as_int(run.get("after")),
            "delta": _as_int(run.get("delta"), minimum=-100_000),
            "confirmed": _as_int(run.get("confirmed")) or 0,
            "unconfirmed": _as_int(run.get("unconfirmed")) or 0,
            "status": _text(run.get("status"), 24) or "missing",
            "start_shot": _shot_payload(run.get("start_shot")),
            "end_shot": _shot_payload(run.get("end_shot")),
            "tasks": [self._task_payload(item) for item in tasks],
        }


class PointsTracker:
    """在一次运行中采集余额截图，并把“真实差额”写入账本与日志。"""

    def __init__(
        self,
        session: BrowserSession,
        cfg: AppConfig,
        *,
        mode: str = "basic",
    ) -> None:
        self.session = session
        self.cfg = cfg
        self.mode = mode
        self.log = logging.getLogger("rewards_bot.points")
        self.ledger = PointsLedger(cfg.general.state_dir, cfg.general.timezone)
        self.tz = cfg.general.tzinfo
        self.run_id = session.artifacts_dir.name
        self.started_at = _now_iso(self.tz)
        self.start_snapshot: dict[str, Any] | None = None
        self.end_snapshot: dict[str, Any] | None = None
        self.tasks: list[dict[str, Any]] = []

    # ---------- 采集 ----------

    def _capture(self, name: str) -> Path | None:
        try:
            path = self.session.screenshot(name)
        except Exception as exc:
            self.log.warning("积分证据截图失败（%s）：%s", name, exc)
            return None
        if path is None:
            return None
        try:
            resolved = Path(path)
            return resolved if resolved.is_file() else None
        except OSError:
            return None

    def _scroll(self, full: bool) -> None:
        page = self.session.current_page
        try:
            if full:
                page.evaluate(POINTS_SCROLL_JS)
            else:
                page.evaluate("() => window.scrollTo(0, 0)")
                page.wait_for_timeout(220)
        except Exception as exc:
            self.log.debug("滚动积分页面失败：%s", exc)

    def read_snapshot(
        self,
        shot_name: str,
        *,
        reload: bool = False,
        full: bool = False,
    ) -> dict[str, Any]:
        snapshot: dict[str, Any] | None = None
        try:
            page = self.session.current_page
            if reload or not is_rewards_home_url(page.url, self.cfg.general.url):
                self.session.open_dashboard()
                page = self.session.current_page
            page.wait_for_timeout(600)
            self._scroll(full)
            raw = page.evaluate(POINTS_SNAPSHOT_JS)
            snapshot = normalize_snapshot(raw)
            if snapshot["balance"] is None and not reload:
                page.wait_for_timeout(1_400)
                self._scroll(full)
                snapshot = normalize_snapshot(page.evaluate(POINTS_SNAPSHOT_JS))
        except Exception as exc:
            self.log.warning("读取积分快照失败：%s", str(exc).splitlines()[0][:220])

        if snapshot is None:
            snapshot = normalize_snapshot(None)
        shot = self._capture(shot_name)
        snapshot["at"] = _now_iso(self.tz)
        snapshot["shot"] = _shot_ref(shot, self.cfg)
        return snapshot

    def _log_reading(self, phase: str, snapshot: dict[str, Any]) -> None:
        balance = snapshot.get("balance") if isinstance(snapshot, dict) else None
        remaining = snapshot.get("remaining") if isinstance(snapshot, dict) else None
        if isinstance(balance, dict):
            self.log.info(
                "积分证据 · %s：账户余额 %s 分（页面实时读取）｜截图：%s",
                phase,
                _format_points(balance.get("points")),
                _shot_name(snapshot.get("shot")) or "截图缺失",
            )
        else:
            self.log.warning(
                "积分证据 · %s：未能从页面读取账户余额，相关收益将标记为未确认。",
                phase,
            )
        if isinstance(remaining, dict):
            self.log.info(
                "今日剩余（页面可见卡片）：%s 分 · %s 个未完成任务。",
                _format_points(remaining.get("points")),
                remaining.get("task_count") or 0,
            )

    # ---------- 运行 / 任务 ----------

    def begin_run(self) -> None:
        self.started_at = _now_iso(self.tz)
        snapshot = self.read_snapshot("points-run-start", full=True)
        self.start_snapshot = snapshot
        self.ledger.record_reading("run_start", snapshot, self.run_id)
        self._log_reading("开始", snapshot)

    def before_task(self, index: int, label: str) -> dict[str, Any]:
        try:
            task_index = max(1, int(index))
        except (TypeError, ValueError):
            task_index = len(self.tasks) + 1
        shot_name = f"points-task-{task_index:02d}-before"
        snapshot = self.read_snapshot(shot_name, full=False)
        return {
            "index": task_index,
            "label": _text(label, 150),
            "before": snapshot,
            "before_shot": snapshot.get("shot"),
        }

    def cancel_task(self, context: dict[str, Any] | None, reason: str) -> None:
        if not context:
            return
        self.log.debug(
            "任务积分证据作废（%s），本次未执行任务，不计入收益：%s",
            reason,
            context.get("label") or "",
        )

    def finish_task(self, context: dict[str, Any] | None) -> dict[str, Any]:
        if not context:
            return {"status": "missing_balance", "page_reloaded": False}
        index = int(context.get("index") or (len(self.tasks) + 1))
        label = _text(context.get("label"), 150)
        before = context.get("before") if isinstance(context.get("before"), dict) else {}
        after = self.read_snapshot(
            f"points-task-{index:02d}-after", full=False
        )
        page_reloaded = False

        before_points = (
            _as_int(before.get("balance", {}).get("points"))
            if isinstance(before.get("balance"), dict)
            else None
        )
        after_points = (
            _as_int(after.get("balance", {}).get("points"))
            if isinstance(after.get("balance"), dict)
            else None
        )

        if before_points is not None:
            # 前端余额可能滞后：先短暂等待再读一次，仍没有增加或仍读不到时刷新页面。
            if after_points is None or after_points <= before_points:
                try:
                    self.session.current_page.wait_for_timeout(1_500)
                except Exception:
                    pass
                after = self.read_snapshot(
                    f"points-task-{index:02d}-after", full=False
                )
                after_points = (
                    _as_int(after.get("balance", {}).get("points"))
                    if isinstance(after.get("balance"), dict)
                    else None
                )
            if after_points is None or after_points <= before_points:
                after = self.read_snapshot(
                    f"points-task-{index:02d}-after", reload=True, full=False
                )
                page_reloaded = True
                after_points = (
                    _as_int(after.get("balance", {}).get("points"))
                    if isinstance(after.get("balance"), dict)
                    else None
                )

        evaluation = evaluate_task_evidence(
            before,
            after,
            context.get("before_shot"),
            after.get("shot"),
        )
        status = evaluation["status"]
        notes = {
            "confirmed": "",
            "unchanged": "任务期间余额未变化",
            "decreased": "任务期间余额下降，未计入收益",
            "missing_balance": "缺少开始或结束余额读数",
            "missing_screenshot": "缺少开始或结束余额截图",
        }
        record = {
            "at": _now_iso(self.tz),
            "run_id": self.run_id,
            "index": index,
            "label": label,
            "status": status,
            "before": evaluation["before"],
            "after": evaluation["after"],
            "delta": evaluation["delta"],
            "note": notes.get(status, "无法确认"),
            "before_shot": context.get("before_shot"),
            "after_shot": after.get("shot"),
        }
        self.ledger.record_task(record)
        self.tasks.append(record)
        self._log_task(record, before, after)
        return {**record, "page_reloaded": page_reloaded}

    def _log_task(
        self,
        record: dict[str, Any],
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> None:
        label = _text(record.get("label"), 110)
        status = record.get("status")
        before_points = record.get("before")
        after_points = record.get("after")
        if status == "confirmed":
            self.log.info(
                "任务积分实测：+%s 分（%s → %s）｜任务：%s｜开始/结束截图：%s / %s",
                _format_points(record.get("delta")),
                _format_points(before_points),
                _format_points(after_points),
                label,
                _shot_name(record.get("before_shot")) or "缺失",
                _shot_name(record.get("after_shot")) or "缺失",
            )
        elif status == "unchanged":
            self.log.info(
                "任务积分实测：0 分（%s → %s），本次任务期间未检测到余额增加｜任务：%s｜截图：%s / %s",
                _format_points(before_points),
                _format_points(after_points),
                label,
                _shot_name(record.get("before_shot")) or "缺失",
                _shot_name(record.get("after_shot")) or "缺失",
            )
        elif status == "decreased":
            delta = record.get("delta")
            self.log.warning(
                "任务积分实测：余额下降 %s 分（%s → %s），下降不计入获得积分｜任务：%s｜截图：%s / %s",
                _format_points(abs(delta) if isinstance(delta, int) else None),
                _format_points(before_points),
                _format_points(after_points),
                label,
                _shot_name(record.get("before_shot")) or "缺失",
                _shot_name(record.get("after_shot")) or "缺失",
            )
        elif status == "missing_screenshot":
            self.log.warning(
                "任务积分未确认：缺少开始或结束截图，不猜测本次获得分数（余额 %s → %s）｜任务：%s",
                _format_points(before_points),
                _format_points(after_points),
                label,
            )
        else:
            self.log.warning(
                "任务积分未确认：缺少开始或结束余额读数，不推测本次获得分数｜任务：%s",
                label,
            )

    def finish_run(self) -> dict[str, Any]:
        try:
            snapshot = self.read_snapshot("points-run-end", reload=True, full=True)
        except Exception as exc:
            self.log.warning("读取结束积分快照失败：%s", str(exc).splitlines()[0][:220])
            snapshot = normalize_snapshot(None)
            snapshot["at"] = _now_iso(self.tz)
            shot = self._capture("points-run-end")
            snapshot["shot"] = _shot_ref(shot, self.cfg)
        self.end_snapshot = snapshot
        self.ledger.record_reading("run_end", snapshot, self.run_id)

        start = self.start_snapshot or {}
        before = (
            _as_int(start.get("balance", {}).get("points"))
            if isinstance(start.get("balance"), dict)
            else None
        )
        after = (
            _as_int(snapshot.get("balance", {}).get("points"))
            if isinstance(snapshot.get("balance"), dict)
            else None
        )
        delta = after - before if before is not None and after is not None else None
        start_shot = start.get("shot")
        end_shot = snapshot.get("shot")
        has_shots = bool(start_shot) and bool(end_shot)
        if before is None or after is None:
            status = "missing"
        elif has_shots:
            status = "confirmed"
        else:
            status = "partial"

        confirmed_total = 0
        for task in self.tasks:
            if task.get("status") != "confirmed":
                continue
            value = _as_int(task.get("delta"))
            if value is not None and value > 0:
                confirmed_total += value
        unconfirmed_count = sum(
            1 for task in self.tasks if task.get("status") != "confirmed"
        )
        finished_at = _now_iso(self.tz)
        record = {
            "id": self.run_id,
            "started_at": self.started_at,
            "finished_at": finished_at,
            "mode": self.mode,
            "before": before,
            "after": after,
            "delta": delta,
            "confirmed": confirmed_total,
            "unconfirmed": unconfirmed_count,
            "status": status,
            "start_shot": start_shot,
            "end_shot": end_shot,
            "tasks": self.tasks,
        }
        self.ledger.record_run(record)

        if delta is not None:
            self.log.info(
                "本次运行积分结算：账户余额 %s → %s（%s）｜逐任务确认 +%s 分｜未确认任务 %s 个。",
                _format_points(before),
                _format_points(after),
                f"{'+' if delta > 0 else ''}{_format_points(delta)}",
                _format_points(confirmed_total),
                unconfirmed_count,
            )
            if not has_shots:
                self.log.warning(
                    "本次运行缺少开始或结束余额截图，整轮变化仅供排查，不作为完整证据。"
                )
            else:
                self.log.info(
                    "运行级证据截图：%s / %s",
                    _shot_name(start_shot) or "缺失",
                    _shot_name(end_shot) or "缺失",
                )
        else:
            self.log.warning(
                "本次运行积分未确认：开始或结束余额未同时读取，未推测本次获得分数。"
                "逐任务确认 +%s 分，未确认任务 %s 个。",
                _format_points(confirmed_total),
                unconfirmed_count,
            )
        remaining = snapshot.get("remaining")
        if isinstance(remaining, dict):
            self.log.info(
                "今日剩余（页面可见卡片）：%s 分 · %s 个未完成任务。",
                _format_points(remaining.get("points")),
                remaining.get("task_count") or 0,
            )
        return record


def read_points_summary(state_dir: Path, timezone: str = "Asia/Shanghai") -> dict[str, Any]:
    """供 /api/state 使用；任何异常都退化为空读数，不影响界面其他部分。"""

    try:
        return PointsLedger(state_dir, timezone).summary()
    except Exception:
        logging.getLogger("rewards_bot.points").exception("生成积分摘要失败")
        tz = _zone(timezone)
        return {
            "available": False,
            "today": _day_key(tz),
            "balance": None,
            "remaining": None,
            "today_confirmed": 0,
            "today_confirmed_tasks": 0,
            "today_unconfirmed_tasks": 0,
            "today_net": None,
            "today_first_balance": None,
            "today_last_balance": None,
            "last_run": None,
            "updated_at": None,
        }
