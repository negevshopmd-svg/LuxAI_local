"""Offline tool-planning and diagnostic guard regressions."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from luxai.adaptive_tasks import ToolChoice, _validate_choice, _validate_diagnostic, run_safe_diagnostic
from luxai.online_agent import OnlinePlanner


class AdaptiveTests(unittest.TestCase):
    def test_json_repair(self):
        parse = OnlinePlanner._read_json_content
        self.assertEqual(parse('Sure: {action:"click",target:"Store"}'),
                         {"action": "click", "target": "Store"})
        self.assertEqual(parse('{"verified":true}'), {"verified": True})
        with self.assertRaises(ValueError):
            parse("not a json object")

    def test_open_app_must_be_spoken(self):
        self.assertEqual(
            _validate_choice({"mode": "open_app", "target": "discord"},
                             "Открой дискорд").target, "discord"
        )
        with self.assertRaises(ValueError):
            _validate_choice({"mode": "open_app", "target": "cmd"},
                             "Открой Discord")
        with self.assertRaises(ValueError):
            _validate_choice({"mode": "open_settings", "target": "unknown"},
                             "Открой параметры")

    def test_clarification_requires_one_explicit_question(self):
        decision = _validate_choice(
            {"mode": "ask", "target": "Какую программу открыть?"},
            "Открой приложение",
        )
        self.assertEqual(decision.mode, "ask")
        with self.assertRaises(ValueError):
            _validate_choice({"mode": "ask", "target": ""}, "Открой")

    def test_safe_readonly_diagnostics_and_no_shell(self):
        self.assertEqual(_validate_diagnostic("whoami"), ["whoami.exe"])
        self.assertEqual(_validate_diagnostic("ipconfig /all"),
                         ["ipconfig.exe", "/all"])
        for bad in (
            "shutdown /s /t 0", "format C:", "whoami & del x",
            "powershell -enc x", "taskkill /f /im Discord.exe",
            "cmd /c whoami", "ping example.org && whoami",
        ):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                _validate_diagnostic(bad)
        with (mock.patch("luxai.adaptive_tasks.sys.platform", "win32"),
              mock.patch("luxai.adaptive_tasks.subprocess.run") as runner):
            runner.return_value.stdout = "PC"
            runner.return_value.stderr = ""
            runner.return_value.returncode = 0
            self.assertIn("PC", run_safe_diagnostic("hostname"))
            self.assertFalse(runner.call_args.kwargs["shell"])

    def test_verified_private_history_only(self):
        import luxai.agent_experience as history
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "h.json"
            with mock.patch.object(history, "_store", return_value=dest):
                history.remember("сделай скриншот", ToolChoice("screen_capture"))
                self.assertEqual(history.recall("сделай скриншот").mode, "screen_capture")
                self.assertNotIn("скриншот", dest.read_text(encoding="utf-8"))
                history.remember("отправь сообщение", ToolChoice("visual"))
                self.assertIsNone(history.recall("отправь сообщение"))


if __name__ == "__main__":
    unittest.main()
