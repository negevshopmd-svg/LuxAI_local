"""Command popovers, editable defaults and folder operations use persisted data."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from luxai.command_registry import CommandRegistry
from luxai.ui_commands import CommandsPage, GROUP_ROLE
from luxai.icons import refresh_icons


class CommandLibrary093cTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.registry = CommandRegistry(Path(folder.name) / "commands.json")
        self.page = CommandsPage(self.registry)
        self.addCleanup(self.page.close)

    def select(self, identifier):
        item = next(item for item in self.page._iter_leaves()
                    if item.data(0, Qt.ItemDataRole.UserRole) == identifier)
        self.page.tree.setCurrentItem(item)
        return item

    def group(self, name):
        return next(item for item in self.page._iter_nodes()
                    if (item.data(0, GROUP_ROLE) or {}).get("name") == name)

    def test_command_popover_matches_reference_order_and_has_real_icons(self):
        entry = self.registry.entries()[0]
        menu = self.page.build_context_menu(self.select(entry["id"]))
        actions = menu.actions()
        self.assertEqual([action.text() for action in actions if not action.isSeparator()], [
            "Открыть", "Добавить обязательную фразу", "Добавить необязательную фразу",
            "Отключить", "Клонировать", "Копировать", "Копировать как JSON", "Удалить",
        ])
        self.assertEqual([i for i, action in enumerate(actions) if action.isSeparator()], [3, 8])
        self.assertTrue(all(not action.icon().isNull() for action in actions if not action.isSeparator()))
        self.assertTrue(actions[-1].data()["danger"])
        self.assertIn("border-radius:12px", menu.styleSheet())
        self.assertEqual(self.page._menu_widgets[entry["id"]].text(), "")
        self.assertFalse(self.page._menu_widgets[entry["id"]].icon().isNull())

    def test_builtin_opens_same_id_and_saved_edits_survive_reload(self):
        original = self.registry.entries()[0]
        self.select(original["id"])
        edited = dict(original, title="My default", phrases=["my exact phrase"])
        with mock.patch("luxai.ui_commands.CommandEditor") as editor:
            editor.return_value.exec.return_value = QDialog.DialogCode.Accepted
            editor.return_value.get_data.return_value = edited
            self.page.open_selected()
        self.assertEqual(editor.call_args.args[0]["id"], original["id"])
        fresh = CommandRegistry(self.registry.path)
        saved = next(record for record in fresh.entries() if record["id"] == original["id"])
        self.assertEqual(saved["title"], "My default")
        self.assertEqual(saved["phrases"], ["my exact phrase"])
        self.assertTrue(saved["builtin"])
        self.assertEqual(fresh.custom, [])

    def test_builtin_delete_is_confirmed_and_does_not_resurrect(self):
        original = self.registry.entries()[0]
        self.select(original["id"])
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.page.delete_selected()
        self.assertIn(original["id"], [record["id"] for record in self.registry.entries()])
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.page.delete_selected()
        self.assertNotIn(original["id"], [record["id"] for record in CommandRegistry(self.registry.path).entries()])

    def test_phrase_menu_edits_default_in_place(self):
        identifier = self.registry.entries()[0]["id"]
        with mock.patch("luxai.ui_commands.QInputDialog.getText", return_value=("custom launch", True)):
            self.page.build_context_menu(self.select(identifier)).actions()[1].trigger()
        with mock.patch("luxai.ui_commands.QInputDialog.getText", return_value=("please", True)):
            self.page.build_context_menu(self.select(identifier)).actions()[2].trigger()
        entry = next(record for record in CommandRegistry(self.registry.path).entries() if record["id"] == identifier)
        self.assertIn("custom launch", entry["phrases"])
        self.assertIn("please", entry["optional_words"])

    def test_clone_is_distinct_disabled_and_copy_preserves_validated_data(self):
        original = self.registry.entries()[0]
        self.select(original["id"])
        self.page.duplicate_selected()
        cloned = self.registry.custom[0]
        self.assertNotEqual(cloned["id"], original["id"])
        self.assertFalse(cloned["builtin"])
        self.assertFalse(cloned["enabled"])
        self.assertEqual(cloned["phrases"], original["phrases"])
        self.page._copy_records([original], original["title"])
        mime = QApplication.clipboard().mimeData()
        self.assertEqual(mime.text(), original["title"])
        copied = json.loads(bytes(mime.data("application/x-luxai-commands+json")))
        self.assertEqual(copied["commands"][0]["id"], original["id"])
        self.page._copy_records([original], original["title"], as_json=True)
        self.assertEqual(json.loads(QApplication.clipboard().text())["commands"][0]["phrases"], original["phrases"])

    def test_folder_has_context_menu_and_atomic_power_and_preserves_expansion(self):
        category = self.group("Управление Windows")
        category.setExpanded(True)
        group = category.data(0, GROUP_ROLE)
        self.assertIn(group["key"], self.page._menu_widgets)
        menu = self.page.build_context_menu(category)
        self.assertEqual(menu.actions()[0].text(), "Открыть")
        menu.actions()[4].trigger()
        records = [record for record in self.registry.entries() if record["id"] in group["ids"]]
        self.assertTrue(records)
        self.assertTrue(all(not record["enabled"] for record in records))
        self.assertTrue(self.group("Управление Windows").isExpanded())

    def test_user_folder_rename_and_delete_keep_commands(self):
        self.registry.add_group("Working set")
        record = self.registry.save_command({"title": "Work", "action": "time", "phrases": ["work time"], "category": "Working set"})
        self.page.refresh()
        with mock.patch("luxai.ui_commands.QInputDialog.getText", return_value=("Renamed", True)):
            self.page._rename_group(self.group("Working set").data(0, GROUP_ROLE))
        self.assertEqual(next(item for item in self.registry.entries() if item["id"] == record["id"])["category"], "Renamed")
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.page._delete_group(self.group("Renamed").data(0, GROUP_ROLE))
        fresh = CommandRegistry(self.registry.path)
        kept = next(item for item in fresh.entries() if item["id"] == record["id"])
        self.assertEqual(kept["category"], "Мои команды")

    def test_group_prefix_keeps_distinct_required_phrases_and_manual_only_state(self):
        records = self.registry.entries()[:2]
        before = [list(record["phrases"]) for record in records]
        with mock.patch("luxai.ui_commands.QInputDialog.getText", return_value=("assistant", True)):
            self.page._add_phrase(records, False, group=True)
        fresh = {record["id"]: record for record in CommandRegistry(self.registry.path).entries()}
        for index, record in enumerate(records):
            self.assertEqual(fresh[record["id"]]["phrases"], ["assistant " + phrase for phrase in before[index]])

    def test_popover_and_library_follow_light_theme(self):
        self.page.set_context(config={"ui_theme": "light", "ui_accent": "#009900"})
        menu = self.page.build_context_menu(self.select(self.registry.entries()[0]["id"]))
        self.assertEqual(menu.colors["surface"], "#ffffff")
        self.assertEqual(menu.colors["accent"], "#009900")
        self.assertIn("#ffffff", self.page.styleSheet())

    def test_menu_keyboard_and_hover_icons_remain_correct_after_theme_refresh(self):
        first, second = list(self.page._iter_leaves())[:2]
        self.page.tree.setCurrentItem(first)
        refresh_icons(self.page, "light", "#3978f6")
        first_key = first.data(0, Qt.ItemDataRole.UserRole)
        second_key = second.data(0, Qt.ItemDataRole.UserRole)
        self.assertFalse(self.page._menu_widgets[first_key].icon().isNull())
        self.assertTrue(self.page._menu_widgets[second_key].icon().isNull())
        menu = self.page.build_context_menu(first)
        menu.popup(self.page.mapToGlobal(QPoint(0, 0)))
        self.app.processEvents()
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as confirm:
            menu.setActiveAction(menu.actions()[-1])
            QTest.keyClick(menu, Qt.Key.Key_Return)
        confirm.assert_called_once()
        self.assertEqual(len(self.registry.entries()), 20)

    def test_folder_clone_disables_new_records_and_preserves_originals(self):
        group = self.group("Управление Windows").data(0, GROUP_ROLE)
        originals = self.page._group_entries(group)
        self.page._duplicate_group(group)
        clones = self.registry.custom
        self.assertEqual(len(clones), len(originals))
        self.assertTrue(all(not entry["enabled"] for entry in clones))
        self.assertTrue(all(not entry["builtin"] for entry in clones))
        self.assertTrue(all(entry["id"] not in group["ids"] for entry in clones))
        self.assertEqual([entry["phrases"] for entry in clones], [entry["phrases"] for entry in originals])
        self.assertTrue(all(entry["enabled"] for entry in self.page._group_entries(group)))


if __name__ == "__main__":
    unittest.main()
