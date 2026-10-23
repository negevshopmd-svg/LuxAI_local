"""Selected-text copying, clipboard safety and Gemini/local summary regression.

Never touches the real system clipboard or opens a browser. Windows clipboard
and Ctrl+C are mocked, so these tests run in GitHub's Linux CI as well.
"""
from __future__ import annotations

import ctypes
import sys
import types
import unittest
from unittest import mock

from luxai.selection import (
    selected_text_intent, capture_clipboard, copy_selected_text,
    finish_selected_copy, extractive_fallback,
)
from luxai.online_agent import OnlinePlanner
from luxai.agent import LocalAgent


class SelectionIntentTests(unittest.TestCase):
    def test_selection_summarize_and_read_in_russian_and_english(self):
        phrases = {
            "Жарвис, сделай краткий пересказ текста, который я выделил": "summarize",
            "Сделай краткий пересказ по тексту, который я выделил": "summarize",
            "Я выделил нужные фрагменты": "summarize",
            "прочти выделенный текст": "read",
            "прочитай, пожалуйста, выделенный текст": "read",
            "Read highlighted text": "read",
            "Summarize selected text": "summarize",
            "Сделай краткий пересказ выделенного на экране текста": "summarize",
            "Жарвис, сделай краткий пересказ": "summarize",
            "Дай резюме текста": "summarize",
            "Сделай пересказ": "summarize",
        }
        for text, expected in phrases.items():
            with self.subTest(text=text):
                self.assertEqual(selected_text_intent(text), expected)

    def test_no_unintended_clipboard_access(self):
        for text in (
            "привет", "сколько времени", "Открой браузер",
            "прочитай экран", "сделай скриншот",
            "посмотри текст в браузере", "нажми Ctrl+C",
            "сделай пересказ о моём детстве", "пересказ книги Война и мир",
        ):
            self.assertIsNone(selected_text_intent(text))

    def test_honest_fallback_never_claims_summary(self):
        result = extractive_fallback("Текст " * 180)
        self.assertIn("без автоматического пересказа", result)
        self.assertIn("Начало текста", result)


class MockMimeData:
    def __init__(self, data):
        self._data = dict(data)

    def formats(self):
        return list(self._data)

    def data(self, fmt):
        return self._data[fmt]


class MockClipboard:
    def __init__(self, selected):
        self.mime = MockMimeData({"text/plain": b"original"})
        self.selected = selected
        self.restored = None
        self.text_value = "previous clipboard"

    def mimeData(self):
        return self.mime

    def text(self):
        return self.text_value

    def setMimeData(self, mime):
        self.restored = mime

    def clear(self):
        self.restored = "clear"


class SelectedClipboardTests(unittest.TestCase):
    def test_mime_formats_snapshot_without_touching_clipboard(self):
        fake = MockClipboard("")
        fake.mime = MockMimeData({
            "text/plain": b"abc",
            "text/html": b"<p>abc</p>",
        })
        self.assertEqual(
            capture_clipboard(fake),
            {"text/plain": b"abc", "text/html": b"<p>abc</p>"},
        )

    def test_huge_clipboard_refuses_copy_without_data_loss(self):
        fake = MockClipboard("")
        fake.mime = MockMimeData({
            "image/big": b"z" * (13 * 1024 * 1024),
        })
        keyboard = mock.Mock()
        with mock.patch("luxai.screen_interact._valid_external_window"), mock.patch(
            "luxai.selection.clipboard_sequence", return_value=10
        ):
            with self.assertRaisesRegex(RuntimeError, "слишком большие"):
                copy_selected_text(
                    fake, 15, keyboard=keyboard, foreground=lambda: 15
                )
        keyboard.assert_not_called()

    def test_copy_only_targets_original_foreground_window(self):
        fake = MockClipboard("")
        keyboard = mock.Mock()
        with mock.patch("luxai.screen_interact._valid_external_window"):
            with self.assertRaisesRegex(RuntimeError, "Активное окно изменилось"):
                copy_selected_text(
                    fake, 15, keyboard=keyboard, foreground=lambda: 99,
                )
        keyboard.assert_not_called()

    def test_copy_preserves_original_mime_data_and_injects_ctrl_c_only(self):
        fake = MockClipboard("")
        keys = mock.Mock()
        with mock.patch("luxai.screen_interact._valid_external_window"), mock.patch(
            "luxai.selection.clipboard_sequence", return_value=11
        ):
            marker, before, saved = copy_selected_text(
                fake, 15, keyboard=keys, foreground=lambda: 15,
            )
        self.assertEqual(marker, "pending")
        self.assertEqual(before, 11)
        self.assertEqual(saved, {"text/plain": b"original"})
        keys.assert_called_once_with("ctrl", "c", interval=0.06)

    def test_clipboard_not_updated_does_not_reuse_old_text(self):
        fake = MockClipboard("")
        with mock.patch("luxai.selection.clipboard_sequence", return_value=123):
            with self.assertRaisesRegex(RuntimeError, "Не удалось скопировать"):
                finish_selected_copy(
                    fake, 7, 123, {"text/plain": b"original"},
                    foreground=lambda: 7,
                )

    def test_focus_change_refuses_stale_selection(self):
        fake = MockClipboard("")
        fake.text_value = "selected text copied from different program"
        with mock.patch("luxai.selection.clipboard_sequence", return_value=124), mock.patch(
            "luxai.selection.restore_clipboard"
        ) as restore:
            with self.assertRaisesRegex(RuntimeError, "Фокус окна изменился"):
                finish_selected_copy(
                    fake, 7, 123, {"text/plain": b"original"},
                    foreground=lambda: 88,
                )
        restore.assert_called_once()

    def test_successful_copy_restores_previous_clipboard(self):
        fake = MockClipboard("")
        fake.text_value = "This article explains cloud API providers."
        with mock.patch("luxai.selection.clipboard_sequence", return_value=124), mock.patch(
            "luxai.selection.restore_clipboard"
        ) as restore:
            selected = finish_selected_copy(
                fake, 7, 123, {"text/plain": b"original"},
                foreground=lambda: 7,
            )
        self.assertEqual(selected, "This article explains cloud API providers.")
        restore.assert_called_once()

    def test_no_restore_after_another_program_updates_clipboard(self):
        fake = MockClipboard("")
        fake.text_value = "Copied selection"
        with mock.patch(
            "luxai.selection.clipboard_sequence", side_effect=[15, 16]
        ), mock.patch("luxai.selection.restore_clipboard") as restore:
            self.assertEqual(
                finish_selected_copy(
                    fake, 7, 14, {"text/plain": b"original"},
                    foreground=lambda: 7,
                ), "Copied selection"
            )
        restore.assert_not_called()


class SummaryTests(unittest.TestCase):
    def test_gemini_summary_never_generates_system_actions(self):
        planner = OnlinePlanner({"online_provider": "gemini", "online_agent_enabled": True})
        response = {
            "choices": [{"message": {
                "content": '{"action":"reply","target":"","reply":"Статья перечисляет шесть сервисов API."}'
            }}],
        }
        with mock.patch.object(planner, "enabled", return_value=True), mock.patch(
            "luxai.online_agent.get_api_key", return_value="fake"
        ), mock.patch.object(planner, "_request", return_value=response) as request:
            answer = planner.summarize_selection("API router providers\nFree quota")
        self.assertEqual(answer, "Статья перечисляет шесть сервисов API.")
        request.assert_called_once()
        self.assertIn("API router providers", request.call_args.args[3][-1]["content"])
        self.assertEqual(request.call_args.args[3][0]["role"], "system")

    def test_cloud_error_gracefully_falls_back(self):
        planner = OnlinePlanner({"online_provider": "gemini", "online_agent_enabled": True})
        with mock.patch.object(planner, "enabled", return_value=True), mock.patch(
            "luxai.online_agent.get_api_key", return_value="fake"
        ), mock.patch.object(planner, "_request", side_effect=TimeoutError):
            self.assertIsNone(planner.summarize_selection("Selected text"))

    def test_local_summary_uses_selected_text_not_previous_history(self):
        fake_model = mock.Mock()
        fake_model.create_chat_completion.return_value = {
            "choices": [{"message": {"content": "Текст рассказывает о шести сервисах API."}}]
        }
        agent = LocalAgent({"language": "ru"})
        with mock.patch.object(agent, "_load_llm", return_value=fake_model):
            response = agent.summarize_selection("OrcaRouter and other six providers")
        self.assertIn("шести сервисах", response)
        args = fake_model.create_chat_completion.call_args.kwargs["messages"]
        self.assertEqual(len(args), 2)
        self.assertIn("OrcaRouter", args[-1]["content"])


if __name__ == "__main__":
    unittest.main()
