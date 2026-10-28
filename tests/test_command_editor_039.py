"""Command drafts round-trip real triggers and support safe, usable editing."""
import tempfile
import sys
from types import SimpleNamespace
from pathlib import Path
import unittest
from unittest import mock

from PySide6.QtCore import QPoint, QTime, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton

from luxai.command_registry import CommandRegistry, checked_command
from luxai.styles import build_styles
from luxai.ui_command_editor import CommandEditor
from luxai.ui_commands import CommandsPage
from luxai.ui_i18n import get_ui_language, set_ui_language, tr


class CommandEditor039Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        previous = get_ui_language()
        set_ui_language("ru")
        self.addCleanup(set_ui_language, previous)

    def make_editor(self, command=None):
        editor = CommandEditor(command)
        self.addCleanup(editor.close)
        return editor

    def ready_editor(self):
        editor = self.make_editor()
        editor.title_field.setText("My work")
        editor.phrase_field.setText("start work, begin work")
        editor.steps = [{"action": "open_app", "target": "telegram", "location": "desktop"}]
        editor._refresh_steps()
        return editor

    def test_phrase_chips_enter_remove_and_optional_words_use_real_matcher(self):
        editor = self.ready_editor()
        editor.show()
        editor.phrase_field.setFocus()
        QTest.keyClick(editor.phrase_field, Qt.Key.Key_Return)
        self.assertEqual(editor.result(), QDialog.DialogCode.Rejected)
        self.assertTrue(editor.isVisible())
        self.assertEqual(editor.phrase_field.text(), "")
        self.assertEqual(editor.get_data()["phrases"], ["start work", "begin work"])
        editor.optional_words.setText("please")
        editor.test_phrase.setText("Jarvis please begin work please")
        self.assertEqual(editor.match_feedback.text(), tr("Фраза подходит"))
        editor.test_phrase.setText("do not begin work")
        self.assertEqual(editor.match_feedback.text(), tr("Фраза не подходит"))
        next(button for button in editor.phrase_chips.chips.findChildren(QPushButton) if button.objectName() == "PhraseChip").click()
        self.assertEqual(editor.get_data()["phrases"], ["begin work"])
        editor.voice_enabled.setChecked(False)
        self.assertEqual(editor.match_feedback.text(), tr("Голосовой запуск выключен."))

    def test_trigger_controls_persist_and_reopen_without_changing_steps(self):
        editor = self.ready_editor()
        editor.optional_words.setText("please, kindly")
        editor.hotkey_toggle.setChecked(True)
        editor.hotkey.setKeySequence(QKeySequence("Ctrl+Alt+T"))
        editor.schedule_toggle.setChecked(True)
        editor.schedule_mode.setCurrentIndex(editor.schedule_mode.findData("weekly"))
        editor.schedule_time.setTime(QTime(8, 45))
        for index, button in enumerate(editor.weekday_buttons):
            button.setChecked(index in (1, 3))
        editor.event_toggle.setChecked(True)
        editor.event_app.setCurrentIndex(editor.event_app.findData("discord"))
        editor.ask_before_run.setChecked(True)
        editor.allow_chaining.setChecked(False)
        with tempfile.TemporaryDirectory() as folder:
            registry = CommandRegistry(Path(folder) / "commands.json")
            saved = registry.save_custom(editor.get_data())
            registry.reload()
            reopened = self.make_editor(registry.custom[0])
            self.assertEqual(checked_command(reopened.get_data()), saved)
            self.assertEqual(saved["hotkey"], "ctrl+alt+t")
            self.assertEqual(saved["schedule"], {"mode": "weekly", "time": "08:45", "weekdays": [1, 3]})
            self.assertEqual(saved["event"], {"type": "app_started", "app": "discord"})
            self.assertTrue(saved["ask_before_run"])
            self.assertFalse(saved["allow_chaining"])
            self.assertEqual(len(saved["steps"]), 1)

    def test_sidebar_run_emits_unsaved_exact_draft_once_and_never_saves_registry(self):
        with tempfile.TemporaryDirectory() as folder:
            registry = CommandRegistry(Path(folder) / "commands.json")
            page = CommandsPage(registry)
            self.addCleanup(page.close)
            editor = page._configure_editor(self.ready_editor())
            emitted, saved_runs = [], []
            page.run_entry_requested.connect(emitted.append)
            page.run_requested.connect(saved_runs.append)
            editor.run_button.click()
            self.assertEqual(len(emitted), 1)
            self.assertEqual(saved_runs, [])
            self.assertEqual(emitted[0]["title"], "My work")
            self.assertEqual(emitted[0]["steps"][0]["target"], "telegram")
            self.assertEqual(registry.custom, [])
            self.assertFalse(registry.path.exists())

    def test_inline_actions_edit_move_delete_and_reject_unvalidated_ai_output(self):
        editor = self.ready_editor()
        editor.steps.append({"action": "wait_seconds", "target": "2", "location": "desktop"})
        editor._refresh_steps()
        second = editor.actions_list.itemWidget(editor.actions_list.item(1))
        next(button for button in second.findChildren(QPushButton) if button.toolTip() == tr("Выше")).click()
        self.assertEqual(editor.steps[0]["action"], "wait_seconds")
        with mock.patch("luxai.ui_command_editor.ActionOptionsDialog") as options:
            options.return_value.exec.return_value = QDialog.DialogCode.Accepted
            options.return_value.data = {"action": "wait_seconds", "target": "3", "location": "desktop"}
            editor.edit_action()
        self.assertEqual(editor.steps[0]["target"], "3")
        first = editor.actions_list.itemWidget(editor.actions_list.item(0))
        next(button for button in first.findChildren(QPushButton) if button.toolTip() == tr("Удалить")).click()
        self.assertEqual(len(editor.steps), 1)
        before = list(editor.steps)
        editor._ai_prompt = "open Telegram"
        editor.apply_ai_result({"steps": [{"action": "run_cmd", "target": "echo forbidden"}]})
        self.assertEqual(editor.steps, before)
        editor.apply_ai_result({"steps": [{"action": "open_app", "target": "telegram"}]})
        self.assertEqual(len(editor.steps), 2)
        self.assertTrue(editor.ai_button.isEnabled())

    def test_recording_stop_appends_validated_steps_and_cancel_always_releases_hook(self):
        editor = self.ready_editor()
        recorder = mock.Mock(error="", active=True)
        recorder.start.return_value = True
        recorder.stop.return_value = [{"action": "press_key", "target": "f2", "location": "desktop"}]
        factory = mock.Mock(return_value=recorder)
        with mock.patch.dict(sys.modules, {"luxai.command_recording": SimpleNamespace(ActionRecorder=factory)}):
            self.assertFalse(editor.record_game_keys.isChecked())
            editor.record_button.click()
            factory.assert_called_with(max_actions=7, record_game_keys=False)
            self.assertFalse(editor.record_game_keys.isEnabled())
            self.assertFalse(editor.save_button.isEnabled())
            self.assertTrue(editor.record_timer.isActive())
            editor.record_button.click()
            recorder.stop.assert_called_once_with()
            self.assertEqual(editor.steps[-1]["target"], "f2")
            self.assertTrue(editor.save_button.isEnabled())
            self.assertFalse(editor.record_timer.isActive())
            before = list(editor.steps)
            editor.record_game_keys.setChecked(True)
            editor.record_button.click()
            factory.assert_called_with(max_actions=6, record_game_keys=True)
            editor.reject()
            self.assertEqual(recorder.stop.call_count, 2)
            self.assertEqual(editor.steps, before)
            self.assertFalse(editor.record_timer.isActive())

    def test_ai_button_forwards_description_and_applies_only_reviewable_steps(self):
        editor = self.ready_editor()
        requests = []
        editor.ai_requested.connect(lambda description, target: requests.append((description, target)))
        with mock.patch("luxai.ui_command_editor.QInputDialog.getMultiLineText", return_value=("open Telegram", True)):
            editor.ai_button.click()
        self.assertEqual(requests, [("open Telegram", editor)])
        self.assertFalse(editor.ai_button.isEnabled())
        editor.apply_ai_result({"steps": [{"action": "open_app", "target": "telegram"}]})
        self.assertTrue(editor.ai_button.isEnabled())
        self.assertEqual(len(editor.steps), 2)

    def test_legacy_verified_steam_command_keeps_appid_and_can_edit_phrases(self):
        original = {"id": "learned_game", "title": "Special game", "category": "Выученные команды",
                    "action": "steam_verified", "target": "Special game", "appid": 1234,
                    "location": "desktop", "phrases": ["start special"], "steps": [],
                    "learned": True, "enabled": True}
        editor = self.make_editor(original)
        self.assertTrue(editor._legacy)
        self.assertFalse(editor.add_button.isEnabled())
        editor.phrase_field.setText("open special")
        self.assertEqual(editor.get_data()["appid"], 1234)
        self.assertEqual(editor.get_data()["phrases"], ["start special", "open special"])
        editor._validate_accept()
        self.assertEqual(editor.result(), QDialog.DialogCode.Accepted)

    def test_manual_only_ready_and_bad_weekly_schedule_disables_save(self):
        editor = self.ready_editor()
        editor.phrase_field.clear()
        self.assertFalse(editor.save_button.isEnabled())
        editor.voice_enabled.setChecked(False)
        self.assertTrue(editor.save_button.isEnabled())
        editor.schedule_toggle.setChecked(True)
        editor.schedule_mode.setCurrentIndex(editor.schedule_mode.findData("weekly"))
        for button in editor.weekday_buttons:
            button.setChecked(False)
        self.assertFalse(editor.save_button.isEnabled())
        editor.weekday_buttons[4].setChecked(True)
        self.assertTrue(editor.save_button.isEnabled())

    def test_narrow_dialog_keeps_sidebar_and_footer_visible_without_horizontal_scroll(self):
        editor = self.ready_editor()
        editor.setStyleSheet(editor.styleSheet() + build_styles("dark", "#873eff"))
        editor.resize(760, 620)
        editor.show()
        self.app.processEvents()
        self.assertTrue(editor.windowFlags() & Qt.WindowType.FramelessWindowHint)
        self.assertEqual(editor.main_scroll.verticalScrollBar().value(), 0)
        self.assertGreaterEqual(editor.title_field.mapTo(editor.main_scroll.viewport(), QPoint()).y(), 0)
        self.assertEqual(editor.main_scroll.horizontalScrollBar().maximum(), 0)
        for widget in (editor.sidebar, editor.cancel_button, editor.save_button, editor.run_button):
            point = widget.mapTo(editor, QPoint())
            self.assertGreaterEqual(point.x(), 0)
            self.assertGreaterEqual(point.y(), 0)
            self.assertLessEqual(point.x() + widget.width(), editor.width())
            self.assertLessEqual(point.y() + widget.height(), editor.height())
