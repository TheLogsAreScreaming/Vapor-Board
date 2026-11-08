"""Alert rate limiting and the macOS notification command (nothing is shown)."""
import unittest
from unittest import mock
from vapor_board import alerts


class AlertTests(unittest.TestCase):
    def test_one_alert_per_cooldown(self):
        now = [100.0]
        gate = alerts.AlertGate(cooldown=30, clock=lambda: now[0])
        self.assertTrue(gate.ready())
        now[0] += 29
        self.assertFalse(gate.ready())
        now[0] += 2
        self.assertTrue(gate.ready())

    def test_text_is_passed_as_data_not_script(self):
        hostile = 'Shop" & do shell script "rm -rf ~'
        command = alerts.banner_command(hostile, "New customer message")
        self.assertEqual(command[-2:], [hostile, "New customer message"])
        self.assertFalse(any(hostile in part for part in command[:-2]))

    def test_a_missing_osascript_is_ignored(self):
        with mock.patch.object(alerts.sys, "platform", "darwin"), \
                mock.patch.object(alerts.subprocess, "Popen", side_effect=OSError("missing")) as popen:
            alerts.show_banner("Shop", "Hello")
        popen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
