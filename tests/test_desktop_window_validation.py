"""Validate Windows 10/11 shell icon hosts without touching a desktop."""
from __future__ import annotations

import os
import unittest
from unittest import mock

import psutil

from luxai.screen_interact import _valid_external_window
from luxai.visual_reasoner import _desktop_window


class DesktopWindowValidationTests(unittest.TestCase):
    def make_user32(self, classname="WorkerW", child=42):
        user32 = mock.Mock()
        user32.IsWindow.return_value = True
        user32.IsWindowVisible.return_value = True
        user32.GetClassNameW.side_effect = lambda hwnd, buffer, length: setattr(buffer, "value", classname)
        user32.FindWindowExW.return_value = child
        return user32

    def validate(self, *, classname="WorkerW", child=42, process="explorer.exe", title="", pid=None):
        user32 = self.make_user32(classname, child)
        with (
            mock.patch("luxai.screen_interact.sys.platform", "win32"),
            mock.patch("luxai.screen_interact.get_user32", return_value=user32),
            mock.patch("luxai.screen_interact._window_pid", return_value=pid or os.getpid() + 100),
            mock.patch("luxai.screen_interact._window_title", return_value=title),
            mock.patch.object(psutil, "Process") as process_type,
        ):
            process_type.return_value.name.return_value = process
            return _valid_external_window(81)

    def test_titleless_actual_workerw_desktop_is_usable(self):
        pid, title = self.validate()
        self.assertEqual(pid, os.getpid() + 100)
        self.assertEqual(title, "Windows desktop")

    def test_unknown_titleless_window_is_still_refused(self):
        for kwargs in (
            {"classname": "Unknown"}, {"child": 0},
            {"process": "python.exe"}, {"pid": os.getpid()},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.validate(**kwargs)

    def test_sensitive_title_is_refused_even_on_shell_class(self):
        with self.assertRaises(ValueError):
            self.validate(title="Windows Security")

    def test_ambiguous_shell_icon_hosts_are_not_guessed(self):
        user32 = mock.Mock()
        user32.FindWindowW.return_value = 0
        def enumerate_windows(callback, argument):
            callback(81, argument)
            callback(84, argument)
        user32.EnumWindows.side_effect = enumerate_windows
        with (
            mock.patch("luxai.win32.get_user32", return_value=user32),
            mock.patch("luxai.screen_interact._is_shell_desktop_window", return_value=True),
            mock.patch("luxai.screen_interact._valid_external_window", return_value=(100, "Windows desktop")),
        ):
            with self.assertRaises(ValueError):
                _desktop_window()


if __name__ == "__main__":
    unittest.main()
