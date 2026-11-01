from __future__ import annotations

import unittest
from types import SimpleNamespace

from gui.tray import (
    TrayActions,
    TrayController,
    low_power_label,
    scheduler_label,
    tray_icon_path,
    tray_status,
)


class _Job:
    def __init__(self, running: bool = False) -> None:
        self.running = running
        self.calls: list[dict] = []

    def start(self, mode=None, trigger="manual"):
        self.calls.append({"mode": mode, "trigger": trigger})
        return True, "任务已开始。"


class _Scheduler:
    def __init__(self, running: bool = False) -> None:
        self.running = running
        self.started = 0
        self.stopped = 0
        self.catch_ups: list[bool | None] = []

    def start(self, catch_up=None):
        self.running = True
        self.started += 1
        self.catch_ups.append(catch_up)
        return True, "每日调度已启动。"

    def stop(self):
        self.running = False
        self.stopped += 1
        return True, "每日调度已停止。"


class _Power:
    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self.activations = 0
        self.deactivations = 0

    def activate(self, close_apps=None):
        self.enabled = True
        self.activations += 1
        return {"enabled": True}

    def deactivate(self):
        self.enabled = False
        self.deactivations += 1
        return {"enabled": False}


class _Runtime:
    def __init__(self, *, job=None, scheduler=None, power=None, login_active=False) -> None:
        self.job = job or _Job()
        self.scheduler = scheduler or _Scheduler()
        self.power = power or _Power()
        self.login = SimpleNamespace(active=login_active)


def _actions(runtime, calls=None, exit_result=(True, "应用正在退出。"), confirm=None):
    calls = calls if calls is not None else []
    return TrayActions(
        runtime,
        open_console=lambda: calls.append("console"),
        request_exit=lambda: exit_result,
        open_logs=lambda: calls.append("logs"),
        confirm_run=confirm or (lambda title, message: True),
    )


class TrayLabelTests(unittest.TestCase):
    def test_bilingual_labels_and_icon(self):
        self.assertIn("已开启", scheduler_label(True))
        self.assertIn("已关闭", scheduler_label(False))
        self.assertIn("已开启", low_power_label(True))
        self.assertIn("已关闭", low_power_label(False))
        self.assertTrue(tray_icon_path().is_file())

    def test_status_prefers_running_job_then_low_power_then_scheduler(self):
        runtime = _Runtime(
            job=_Job(running=True),
            scheduler=_Scheduler(running=True),
            power=_Power(enabled=True),
        )
        self.assertIn("任务运行中", tray_status(runtime))
        runtime.job.running = False
        self.assertIn("低功耗", tray_status(runtime))
        runtime.power.enabled = False
        self.assertIn("调度已开启", tray_status(runtime))
        runtime.scheduler.running = False
        self.assertIn("空闲", tray_status(runtime))


class _FakeMenuItem:
    def __init__(self, text, action=None, **kwargs) -> None:
        self.text = text
        self.action = action
        self.default = bool(kwargs.get("default", False))
        self.checked = kwargs.get("checked")
        self.enabled = kwargs.get("enabled")


class _FakeMenu:
    SEPARATOR = object()

    def __init__(self, *items) -> None:
        self.items = items


class _FakePystray:
    Menu = _FakeMenu
    MenuItem = _FakeMenuItem


def _text(item) -> str:
    return item.text(item) if callable(item.text) else item.text


class TrayMenuTests(unittest.TestCase):
    def test_right_click_menu_has_basic_actions(self):
        controller = TrayController(_actions(_Runtime()))
        menu = controller._build_menu(_FakePystray)
        items = menu.items

        self.assertEqual(_text(items[0]), "打开控制台")
        self.assertTrue(items[0].default)
        self.assertEqual(_text(items[1]), "立即运行一次")
        self.assertTrue(items[1].enabled())
        self.assertEqual(_text(items[3]), "每日调度：已关闭")
        self.assertFalse(items[3].checked())
        self.assertEqual(_text(items[4]), "低功耗挂机：已关闭")
        self.assertFalse(items[4].checked())
        self.assertEqual(_text(items[6]), "打开日志文件夹")
        self.assertEqual(_text(items[7]), "退出 Rewards Pilot")
        self.assertEqual(items[2], _FakeMenu.SEPARATOR)
        self.assertEqual(items[5], _FakeMenu.SEPARATOR)

    def test_menu_reflects_running_states(self):
        runtime = _Runtime(
            job=_Job(running=True),
            scheduler=_Scheduler(running=True),
            power=_Power(enabled=True),
            login_active=True,
        )
        controller = TrayController(_actions(runtime))
        items = controller._build_menu(_FakePystray).items

        self.assertFalse(items[1].enabled())
        self.assertEqual(_text(items[3]), "每日调度：已开启")
        self.assertTrue(items[3].checked())
        self.assertEqual(_text(items[4]), "低功耗挂机：已开启")
        self.assertTrue(items[4].checked())


class TrayActionTests(unittest.TestCase):
    def test_run_now_uses_tray_trigger(self):
        runtime = _Runtime()
        ok, message = _actions(runtime).run_now()
        self.assertTrue(ok)
        self.assertIn("任务已开始", message)
        self.assertEqual(runtime.job.calls, [{"mode": None, "trigger": "tray"}])

    def test_run_now_rejects_running_job_or_login(self):
        busy = _Runtime(job=_Job(running=True))
        ok, message = _actions(busy).run_now()
        self.assertFalse(ok)
        self.assertIn("已有任务", message)
        self.assertEqual(busy.job.calls, [])

        login = _Runtime(login_active=True)
        ok, message = _actions(login).run_now()
        self.assertFalse(ok)
        self.assertIn("登录窗口", message)
        self.assertEqual(login.job.calls, [])

    def test_run_now_requires_confirmation(self):
        runtime = _Runtime()
        prompts: list[tuple[str, str]] = []

        def deny(title: str, message: str) -> bool:
            prompts.append((title, message))
            return False

        ok, message = _actions(runtime, confirm=deny).run_now()
        self.assertFalse(ok)
        self.assertIn("已取消", message)
        self.assertEqual(runtime.job.calls, [])
        self.assertEqual(len(prompts), 1)
        self.assertIn("真实任务", prompts[0][1])

    def test_scheduler_toggle_starts_and_stops(self):
        runtime = _Runtime()
        ok, message = _actions(runtime).toggle_scheduler()
        self.assertTrue(ok)
        self.assertIn("已开启", message)
        self.assertEqual(runtime.scheduler.started, 1)
        self.assertEqual(runtime.scheduler.catch_ups, [False])

        ok, message = _actions(runtime).toggle_scheduler()
        self.assertTrue(ok)
        self.assertIn("已暂停", message)
        self.assertEqual(runtime.scheduler.stopped, 1)

    def test_low_power_toggle_activates_and_deactivates(self):
        runtime = _Runtime()
        ok, message = _actions(runtime).toggle_low_power()
        self.assertTrue(ok)
        self.assertIn("已开启", message)
        self.assertEqual(runtime.power.activations, 1)

        ok, message = _actions(runtime).toggle_low_power()
        self.assertTrue(ok)
        self.assertIn("已关闭", message)
        self.assertEqual(runtime.power.deactivations, 1)

    def test_quit_delegates_to_shutdown(self):
        runtime = _Runtime()
        ok, message = _actions(runtime, exit_result=(False, "任务仍在运行")).quit()
        self.assertFalse(ok)
        self.assertEqual(message, "任务仍在运行")

    def test_callbacks_are_separate(self):
        calls: list[str] = []
        actions = _actions(_Runtime(), calls=calls)
        actions.open_console()
        actions.open_logs()
        self.assertEqual(calls, ["console", "logs"])


if __name__ == "__main__":
    unittest.main()
