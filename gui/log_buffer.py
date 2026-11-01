from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime
from typing import Any


class LogBuffer(logging.Handler):
    """线程安全的日志环形缓冲，供本地前端轮询。"""

    def __init__(self, capacity: int = 1200) -> None:
        super().__init__(logging.DEBUG)
        self._items: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._seq = 0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            if record.exc_info:
                message += "\n" + logging.Formatter().formatException(record.exc_info)
            with self._lock:
                self._seq += 1
                self._items.append(
                    {
                        "seq": self._seq,
                        "time": datetime.fromtimestamp(record.created)
                        .astimezone()
                        .isoformat(timespec="seconds"),
                        "level": record.levelname.lower(),
                        "name": record.name.replace("rewards_bot.", ""),
                        "message": message,
                    }
                )
        except Exception:
            self.handleError(record)

    def since(self, after: int = 0, limit: int = 300) -> tuple[list[dict[str, Any]], int]:
        with self._lock:
            items = [item for item in self._items if item["seq"] > after]
            last_seq = self._seq
        return items[-limit:], last_seq
