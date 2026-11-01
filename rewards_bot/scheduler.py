from __future__ import annotations

import json
import logging
import threading
import time
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Callable

from .config import GeneralConfig


class DailyScheduler:
    """每天在配置的本地时间运行一次任务；进程需要保持运行。"""

    def __init__(self, cfg: GeneralConfig) -> None:
        self.cfg = cfg
        self.log = logging.getLogger("rewards_bot.scheduler")
        self.state_file = cfg.state_dir / "last_run.json"
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.next_run_at: datetime | None = None

    def _read_last_date(self) -> date | None:
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            return date.fromisoformat(str(data.get("date")))
        except (OSError, ValueError, TypeError):
            return None

    def _mark_attempted(self, run_date: date) -> None:
        payload = {
            "date": run_date.isoformat(),
            "saved_at": datetime.now(self.cfg.tzinfo).isoformat(timespec="seconds"),
        }
        tmp = self.state_file.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.state_file)
        except OSError as exc:
            self.log.warning("无法写入调度状态文件：%s", exc)

    def _scheduled_datetime(self, day: date) -> datetime:
        hour, minute = self.cfg.run_hour_minute
        return datetime.combine(day, dt_time(hour=hour, minute=minute), tzinfo=self.cfg.tzinfo)

    def _next_run(self, now: datetime) -> datetime:
        run_time = self._scheduled_datetime(now.date())
        if now >= run_time:
            run_time = self._scheduled_datetime(now.date() + timedelta(days=1))
        return run_time

    def run(
        self,
        job: Callable[[], bool],
        stop_event: threading.Event | None = None,
    ) -> None:
        stop = stop_event or threading.Event()
        try:
            now = datetime.now(self.cfg.tzinfo)
            today = now.date()
            last_date = self._read_last_date()
            today_run = self._scheduled_datetime(today)

            if last_date == today:
                next_run = self._next_run(now)
            elif self.cfg.catch_up and now >= today_run:
                self.log.info(
                    "今天 %s 的定时任务尚未执行，立即补跑一次（catch_up=true）。",
                    self.cfg.run_at,
                )
                self._invoke(job, today)
                if stop.is_set():
                    return
                next_run = self._next_run(datetime.now(self.cfg.tzinfo))
            else:
                next_run = today_run if now < today_run else self._next_run(now)

            while not stop.is_set():
                self.next_run_at = next_run
                remaining = (next_run - datetime.now(self.cfg.tzinfo)).total_seconds()
                if remaining > 0:
                    self.log.info(
                        "下一次运行：%s（约 %.1f 小时后），保持本进程运行。",
                        next_run.strftime("%Y-%m-%d %H:%M %Z"),
                        remaining / 3600,
                    )
                    if not self._wait_until(next_run, stop):
                        return
                if stop.is_set():
                    return

                run_date = next_run.date()
                self._invoke(job, run_date)
                if stop.is_set():
                    return
                next_run = self._next_run(datetime.now(self.cfg.tzinfo))
                if stop.wait(5):
                    return
        finally:
            self.next_run_at = None

    def _wait_until(self, target: datetime, stop: threading.Event) -> bool:
        while not stop.is_set():
            remaining = (target - datetime.now(self.cfg.tzinfo)).total_seconds()
            if remaining <= 0:
                return True
            if stop.wait(min(remaining, 300)):
                return False
        return False

    def _invoke(self, job: Callable[[], bool], run_date: date) -> None:
        started = time.monotonic()
        self.log.info("=" * 70)
        self.log.info("定时任务开始：%s", datetime.now(self.cfg.tzinfo).isoformat(timespec="seconds"))
        try:
            ok = bool(job())
            self.log.info(
                "定时任务结束：%s，用时 %.1f 秒。",
                "成功" if ok else "失败",
                time.monotonic() - started,
            )
        except KeyboardInterrupt:
            self.log.info("收到 Ctrl+C，停止调度。")
            raise
        except Exception:
            self.log.exception("定时任务发生未处理异常，调度器继续等待下一天。")
        finally:
            self._mark_attempted(run_date)
