"""Settings edits persist, scoped reset is cancellable, and discovery reveals controls."""
import unittest
from unittest import mock

from PySide6.QtWidgets import QApplication, QDialog
from luxai.settings_panel import SettingsPanel
from luxai.ui_i18n import get_ui_language, set_ui_language


class SettingsControls039gTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def panel(self, config=None):
        language = get_ui_language()
        self.addCleanup(set_ui_language, language)
        set_ui_language('ru')
        saved = []
        with mock.patch('sounddevice.query_devices', return_value=[]):
            panel = SettingsPanel({'microphone_enabled': False, **(config or {})},
                                  lambda: saved.append(panel.collect()), lambda: None, lambda: None)
        self.addCleanup(panel.close)
        return panel, saved

    def test_new_preferences_save_together_and_restore_after_reopen(self):
        panel, saved = self.panel()
        panel.listen_mode.setCurrentIndex(panel.listen_mode.findData('hold'))
        panel.listen_hotkey.setCurrentIndex(panel.listen_hotkey.findData('f9'))
        panel.recognition_sensitivity.setValue(72)
        panel.understand_paraphrases.setChecked(True)
        panel.quiet_mode_phrases.setText('liniște, silent please')
        panel.command_stop_phrases.setText('ajunge')
        panel.font_family.setCurrentIndex(panel.font_family.findData('Arial'))
        panel.enhanced_accuracy.setChecked(True)
        panel.flush_auto_save()
        self.assertEqual(len(saved), 1)
        restored, calls = self.panel(saved[0])
        self.assertEqual(restored.collect(), saved[0])
        self.assertTrue(restored.listen_hotkey.isEnabled())
        self.assertTrue(restored.enhanced_accuracy.isChecked())
        self.assertEqual(restored.collect()['whisper_beam_size'], 4)
        self.assertEqual(calls, [])

    def test_voice_reset_cancel_preserves_all_preferences(self):
        panel, saved = self.panel({'voice_volume': 15, 'language': 'ro', 'voice_id': 'en_US-lessac-medium'})
        before = panel.collect()
        with mock.patch('luxai.settings_panel.SettingsResetDialog') as dialog:
            dialog.return_value.exec.return_value = QDialog.DialogCode.Rejected
            panel.voice_reset.click()
        panel.flush_auto_save()
        self.assertEqual(panel.collect(), before)
        self.assertEqual(saved, [])

    def test_confirmed_voice_reset_keeps_input_commands_and_credentials(self):
        panel, saved = self.panel({'voice_volume': 15, 'tts_enabled': False, 'language': 'ro',
                                   'response_language': 'en', 'voice_id': 'en_US-lessac-medium',
                                   'confirmation_timeout': 95, 'ui_font_family': 'Arial'})
        panel.api_key_entry.setText('unsaved-key-draft')
        panel.fish_api_key.setText('unsaved-fish-draft')
        with mock.patch('luxai.settings_panel.SettingsResetDialog') as dialog:
            dialog.return_value.exec.return_value = QDialog.DialogCode.Accepted
            panel.voice_reset.click()
        panel.flush_auto_save()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]['voice_volume'], 80)
        self.assertEqual(saved[0]['voice_id'], '')
        self.assertEqual(saved[0]['response_language'], 'auto')
        self.assertTrue(saved[0]['tts_enabled'])
        self.assertEqual(saved[0]['language'], 'ro')
        self.assertEqual(saved[0]['confirmation_timeout'], 95)
        self.assertEqual(saved[0]['ui_font_family'], 'Arial')
        self.assertEqual(panel.api_key_entry.text(), 'unsaved-key-draft')
        self.assertEqual(panel.fish_api_key.text(), 'unsaved-fish-draft')
        self.assertEqual(panel.api_key_ready_for_save(), '')

    def test_search_finds_hidden_advanced_setting_without_saving(self):
        panel, saved = self.panel()
        self.assertTrue(panel.commands_advanced.isHidden())
        panel.search.setText('Остановить всю цепочку')
        self.assertFalse(panel.sections[2].isHidden())
        self.assertFalse(panel.commands_advanced.isHidden())
        panel.flush_auto_save()
        self.assertEqual(saved, [])
