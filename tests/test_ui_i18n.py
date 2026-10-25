"""UI language switching must not change commands, values or speech settings."""
import unittest

from PySide6.QtWidgets import (
    QApplication, QComboBox, QLabel, QLineEdit, QPushButton, QSpinBox,
    QTreeWidget, QVBoxLayout, QWidget,
)

from luxai.ui_i18n import (
    LANGUAGES, get_ui_language, set_ui_language, translate_widgets, tr,
)
from luxai.ui_sidebar import NavigationSidebar


class UiI18nTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        set_ui_language("ru")

    def tearDown(self):
        set_ui_language("ru")

    def test_native_language_options_and_safe_default(self):
        self.assertEqual([code for _, code in LANGUAGES], ["ru", "en", "ro"])
        self.assertEqual(tr("Настройки", "en"), "Settings")
        self.assertEqual(tr("Настройки", "ro"), "Setări")
        self.assertEqual(tr("Настройки", "ru"), "Настройки")
        self.assertEqual(tr("Настройки", "unknown"), "Настройки")

    def test_widget_language_change_is_reversible_and_keeps_user_values(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        label = QLabel("Настройки")
        button = QPushButton("＋  Новая команда")
        combo = QComboBox()
        combo.addItem("Тёмное", "dark")
        combo.addItem("Светлое", "light")
        combo.setCurrentIndex(1)
        entry = QLineEdit("My custom command - do NOT translate")
        entry.setPlaceholderText("Напишите сообщение или команду…")
        language_box = QComboBox()
        language_box.setObjectName("UiLanguageCombo")
        for name, code in LANGUAGES:
            language_box.addItem(name, code)
        language_box.setCurrentIndex(2)
        time = QSpinBox()
        time.setSuffix(" сек")
        tree = QTreeWidget()
        tree.setHeaderLabels(["Название команды", "Состояние"])
        for item in (label, button, combo, entry, language_box, time, tree):
            layout.addWidget(item)

        translate_widgets(root, "en")
        self.assertEqual(label.text(), "Settings")
        self.assertEqual(button.text(), "＋  New command")
        self.assertEqual(combo.itemText(0), "Dark")
        self.assertEqual(combo.currentData(), "light")
        self.assertEqual(language_box.currentText(), "Română")
        self.assertEqual(entry.text(), "My custom command - do NOT translate")
        self.assertEqual(entry.placeholderText(), "Type a message or command…")
        self.assertEqual(tree.headerItem().text(0), "Command name")
        self.assertEqual(time.suffix(), " sec")

        translate_widgets(root, "ro")
        self.assertEqual(label.text(), "Setări")
        self.assertEqual(button.text(), "＋  Comandă nouă")
        self.assertEqual(combo.itemText(0), "Întunecat")
        self.assertEqual(combo.currentData(), "light")
        self.assertEqual(tree.headerItem().text(0), "Numele comenzii")
        self.assertEqual(time.suffix(), " s")

        translate_widgets(root, "ru")
        self.assertEqual(label.text(), "Настройки")
        self.assertEqual(button.text(), "＋  Новая команда")
        self.assertEqual(combo.itemText(0), "Тёмное")
        self.assertEqual(combo.currentData(), "light")
        self.assertEqual(tree.headerItem().text(0), "Название команды")
        self.assertEqual(time.suffix(), " сек")
        root.close()

    def test_sidebar_translates_without_changing_page_ids(self):
        rail = NavigationSidebar()
        rail.set_language("ro")
        self.assertIn("Acasă", rail.nav_buttons[0].text())
        self.assertIn("Setări", rail.nav_buttons[4].text())
        rail.toggle_collapsed()
        self.assertEqual(rail.nav_buttons[4].text(), "")
        self.assertFalse(rail.nav_buttons[4].icon().isNull())
        self.assertEqual(rail.nav_buttons[4].toolTip(), "Setări")
        rail.toggle_collapsed()
        self.assertIn("Setări", rail.nav_buttons[4].text())
        rail.set_language("en")
        self.assertIn("Settings", rail.nav_buttons[4].text())
        rail.set_language("ru")
        self.assertIn("Настройки", rail.nav_buttons[4].text())
        rail.close()

    def test_voice_language_setting_is_not_replaced(self):
        from pathlib import Path
        settings = (Path(__file__).resolve().parents[1] / "luxai" / "settings_panel.py").read_text(encoding="utf-8")
        self.assertIn('"ui_language": self.ui_language.currentData()', settings)
        self.assertIn('"language": self.language.currentData()', settings)


if __name__ == "__main__":
    unittest.main()
