from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gui import power_mode
from gui.power_mode import (
    KNOWN_PLANS,
    SAFE_BACKGROUND_APPS,
    LowPowerService,
    close_safe_background_apps,
    parse_active_plan_output,
    parse_tasklist_csv,
)


class PowerParsingTests(unittest.TestCase):
    def test_parse_active_plan_known_and_custom(self) -> None:
        output = (
            "Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced)"
        )
        self.assertEqual(
            parse_active_plan_output(output),
            ("381b4222-f694-41f0-9685-ff5bb260df2e", "Balanced"),
        )
        custom = (
            "电源方案 GUID: 85921fdf-1565-4d30-812b-23e50aaaf1d8  (我的计划)"
        )
        self.assertEqual(
            parse_active_plan_output(custom),
            ("85921fdf-1565-4d30-812b-23e50aaaf1d8", "我的计划"),
        )
        self.assertIsNone(parse_active_plan_output("not a plan"))

    def test_parse_tasklist_csv(self) -> None:
        text = (
            '"QQ.exe","100","Console","1","123,456 K"\n'
            '"python.exe","101","Console","1","9,000 K"\n'
            "malformed\n"
        )
        processes = parse_tasklist_csv(text)
        self.assertEqual(len(processes), 2)
        self.assertEqual(processes[0]["exe"], "QQ.exe")
        self.assertEqual(processes[0]["pid"], 100)
        self.assertAlmostEqual(processes[0]["memory_mb"], 120.6, places=1)

    def test_safe_app_allowlist_never_contains_system_or_browser(self) -> None:
        forbidden = {
            "explorer.exe",
            "svchost.exe",
            "lsass.exe",
            "csrss.exe",
            "winlogon.exe",
            "services.exe",
            "system",
            "msedge.exe",
            "chrome.exe",
            "rewardsPilot.exe".lower(),
            "python.exe",
        }
        self.assertFalse(forbidden & set(SAFE_BACKGROUND_APPS))
        self.assertIn("wechat.exe", SAFE_BACKGROUND_APPS)
        self.assertIn("a1841308-3541-4fab-bc81-f71556f20b4a", KNOWN_PLANS)

    def test_close_ignores_arbitrary_names(self) -> None:
        with patch.object(power_mode, "_run") as run, patch.object(
            power_mode, "list_processes"
        ) as list_processes:
            self.assertEqual(close_safe_background_apps(["lsass.exe", "svchost.exe"]), [])
            run.assert_not_called()
            list_processes.assert_not_called()


@unittest.skipUnless(os.name == "nt", "低功耗模式仅支持 Windows")
class LowPowerServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.before = ("custom-guid", "自定义计划")
        self.saver = (
            "a1841308-3541-4fab-bc81-f71556f20b4a",
            "节能",
        )

    def _service(self) -> LowPowerService:
        return LowPowerService(lambda: self.base, is_busy=lambda: False)

    def test_activate_and_deactivate_restore_previous_plan(self) -> None:
        service = self._service()
        with patch.object(
            power_mode, "get_active_plan", side_effect=[self.before, self.saver]
        ), patch.object(power_mode, "set_active_plan", return_value=(True, "")) as setter, patch.object(
            power_mode,
            "set_process_efficiency",
            return_value={"priority": True, "eco_qos": True, "detail": ""},
        ), patch.object(service._awake, "start", return_value=True), patch.object(
            service._awake, "stop"
        ), patch.object(power_mode, "close_safe_background_apps", return_value=[]):
            state = service.activate([])
            self.assertTrue(state["enabled"])
            self.assertTrue(state["hold_awake"])
            self.assertTrue(state["power_plan"]["changed"])
            self.assertTrue((self.base / "power_mode.json").exists())
            setter.assert_called_with(power_mode.POWER_SAVER_ALIAS)

            stopped = service.deactivate()
            self.assertFalse(stopped["enabled"])
            self.assertFalse((self.base / "power_mode.json").exists())
            setter.assert_called_with(self.before[0])
            self.assertEqual(stopped["power_plan"]["active"], self.before[0])
            self.assertEqual(stopped["power_plan"]["active_name"], self.before[1])
            self.assertFalse(stopped["power_plan"]["changed"])

    def test_activate_skips_app_cleanup_when_busy(self) -> None:
        busy = LowPowerService(lambda: self.base, is_busy=lambda: True)
        with patch.object(
            power_mode, "get_active_plan", side_effect=[self.before, self.saver]
        ), patch.object(power_mode, "set_active_plan", return_value=(True, "")), patch.object(
            power_mode,
            "set_process_efficiency",
            return_value={"priority": True, "eco_qos": True, "detail": ""},
        ), patch.object(busy._awake, "start", return_value=True), patch.object(
            power_mode, "close_safe_background_apps"
        ) as cleanup:
            state = busy.activate(["wechat.exe"])
            cleanup.assert_not_called()
            self.assertTrue(any("跳过关闭后台应用" in item for item in state["warnings"]))
            busy.deactivate()

    def test_activate_without_plan_change_does_not_write_recovery(self) -> None:
        service = self._service()
        with patch.object(
            power_mode, "get_active_plan", return_value=self.saver
        ), patch.object(power_mode, "set_active_plan") as setter, patch.object(
            power_mode,
            "set_process_efficiency",
            return_value={"priority": True, "eco_qos": True, "detail": ""},
        ), patch.object(service._awake, "start", return_value=True), patch.object(
            service._awake, "stop"
        ):
            state = service.activate([])
            setter.assert_not_called()
            self.assertFalse(state["power_plan"]["changed"])
            self.assertFalse((self.base / "power_mode.json").exists())
            service.deactivate()

    def test_recover_stale_session_restores_saved_plan(self) -> None:
        payload = {
            "original_plan": "85921fdf-1565-4d30-812b-23e50aaaf1d8",
            "original_plan_name": "我的计划",
        }
        (self.base / "power_mode.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        service = self._service()
        with patch.object(
            power_mode,
            "get_active_plan",
            return_value=(power_mode.POWER_SAVER_ALIAS, "节能"),
        ), patch.object(power_mode, "set_active_plan", return_value=(True, "")) as setter:
            service.recover_stale_session()
        setter.assert_called_once_with(payload["original_plan"])
        self.assertFalse((self.base / "power_mode.json").exists())


if __name__ == "__main__":
    unittest.main()
