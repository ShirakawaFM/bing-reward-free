from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

MARKER_VERSION = 1
MARKER_NAME = "onboarding.json"
ONBOARDING_ACTIONS = frozenset({"completed", "skipped"})


class OnboardingStore:
    """记录初始化教程是否已经看过，不保存任何账号或 Key 信息。

    标记文件放在状态目录中：
    `state/onboarding.json`。用户删除它或更换状态目录后，教程会重新出现。
    """

    def __init__(self, state_dir: Callable[[], Path]) -> None:
        self._state_dir = state_dir
        self._lock = threading.Lock()
        self.log = logging.getLogger("rewards_bot.gui.onboarding")

    def _marker_path(self) -> Path:
        return Path(self._state_dir()).expanduser().resolve() / MARKER_NAME

    def _read(self) -> dict[str, Any] | None:
        try:
            path = self._marker_path()
        except Exception as exc:
            self.log.warning("无法定位初始化教程状态目录：%s", exc)
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            self.log.warning("初始化教程状态文件无法读取，将重新显示教程。")
            return None
        return raw if isinstance(raw, dict) else None

    def _snapshot(self) -> dict[str, Any]:
        data = self._read()
        try:
            version = int(data.get("version", 0)) if data else 0
        except (TypeError, ValueError):
            version = 0
        seen = bool(
            data
            and data.get("completed") is True
            and version >= MARKER_VERSION
        )
        action = data.get("action") if seen else None
        completed_at = data.get("completed_at") if seen else None
        return {
            "seen": seen,
            "show": not seen,
            "version": MARKER_VERSION,
            "completed_at": completed_at if isinstance(completed_at, str) else None,
            "action": action if action in ONBOARDING_ACTIONS else None,
        }

    def snapshot(self) -> dict[str, Any]:
        """返回教程状态。读取失败时不让整个控制台接口失败。"""

        with self._lock:
            return self._snapshot()

    def complete(self, action: str = "completed") -> dict[str, Any]:
        """将教程标记为完成或跳过。不会改动任何配置项。"""

        if action not in ONBOARDING_ACTIONS:
            raise ValueError("初始化教程状态无效。")
        with self._lock:
            path = self._marker_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": MARKER_VERSION,
                "completed": True,
                "completed_at": datetime.now().astimezone().isoformat(
                    timespec="seconds"
                ),
                "action": action,
            }
            tmp = path.with_name(path.name + ".tmp")
            try:
                tmp.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                tmp.replace(path)
            finally:
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
            self.log.info(
                "初始化教程已%s。",
                "完成" if action == "completed" else "跳过",
            )
            return self._snapshot()
