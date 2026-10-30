"""Real tab controls and file dialogs preserve only the selected collection."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog
from luxai.command_registry import CommandRegistry, is_agent_command
from luxai.ui_commands import CommandsPage, GROUP_ROLE
from luxai.ui_i18n import get_ui_language, set_ui_language


class CommandWorkspace093dTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.addCleanup(set_ui_language, get_ui_language())
        set_ui_language('ru')
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.registry = CommandRegistry(self.root/'commands.json')
        self.registry.add_group('Morning', 'collections')
        self.registry.add_group('Unrelated', 'folders')
        self.clock = self.registry.save_command({'title': 'Morning clock', 'action': 'time',
            'phrases': ['morning clock'], 'category': 'Morning', 'hotkey': 'ctrl+alt+k',
            'optional_words': ['please'], 'ask_before_run': True, 'allow_chaining': False})
        self.other = self.registry.save_command({'title': 'Other', 'action': 'time',
            'phrases': ['other time'], 'category': 'Unrelated'})
        self.page = self.make_page(self.registry)

    def make_page(self, registry):
        page = CommandsPage(registry)
        self.addCleanup(page.close)
        return page

    def select_group(self, name):
        item = next(item for item in self.page._iter_nodes()
                    if (item.data(0, GROUP_ROLE) or {}).get('name') == name)
        self.page.tree.setCurrentItem(item)
        return item

    def test_selected_collection_file_roundtrip_excludes_other_commands(self):
        self.select_group('Morning')
        export = self.root/'Morning.json'
        neighbor = self.root/'Morning.json.tmp'
        neighbor.write_text('User file, never replace this')
        with mock.patch.object(QFileDialog, 'getSaveFileName', return_value=(str(export), 'JSON')):
            self.page.export_button.click()
        payload = json.loads(export.read_text(encoding='utf-8'))
        self.assertEqual([item['title'] for item in payload['commands']], ['Morning clock'])
        self.assertEqual(payload['groups'], [{'name': 'Morning', 'kind': 'collections', 'agent': False}])
        self.assertEqual(neighbor.read_text(), 'User file, never replace this')
        target = CommandRegistry(self.root/'fresh.json')
        target_page = self.make_page(target)
        ran = []
        target_page.run_requested.connect(ran.append)
        with mock.patch.object(QFileDialog, 'getOpenFileName', return_value=(str(export), 'JSON')):
            target_page.import_button.click()
        fresh = CommandRegistry(target.path)
        self.assertEqual(fresh.groups['collections'], ['Morning'])
        self.assertEqual(len(fresh.custom), 1)
        imported = fresh.custom[0]
        self.assertNotEqual(imported['id'], self.clock['id'])
        self.assertFalse(imported['enabled'])
        for key in ('title', 'phrases', 'hotkey', 'optional_words', 'action', 'ask_before_run', 'allow_chaining'):
            self.assertEqual(imported[key], self.clock[key])
        self.assertEqual(ran, [])

    def test_empty_selected_collection_is_exported_and_imported(self):
        self.registry.add_group('Empty', 'collections')
        self.page.refresh()
        self.select_group('Empty')
        export = self.root/'empty.json'
        with mock.patch.object(QFileDialog, 'getSaveFileName', return_value=(str(export), 'JSON')):
            self.page.export_commands()
        payload = json.loads(export.read_text())
        self.assertEqual(payload['commands'], [])
        self.assertEqual(payload['groups'][0]['name'], 'Empty')
        target = CommandRegistry(self.root/'empty-target.json')
        target_page = self.make_page(target)
        with mock.patch.object(QFileDialog, 'getOpenFileName', return_value=(str(export), 'JSON')):
            target_page.import_commands()
        self.assertEqual(CommandRegistry(target.path).groups['collections'], ['Empty'])

    def test_agent_tab_is_exclusive_and_has_real_empty_chat_action(self):
        opened = []
        self.page.chat_requested.connect(lambda: opened.append(True))
        self.page.show()
        self.page.agent_tab.click()
        self.app.processEvents()
        self.assertTrue(self.page._agent_mode)
        self.assertTrue(self.page.agent_tab.isChecked())
        self.assertFalse(self.page.my_tab.isChecked())
        self.assertTrue(self.page.agent_empty.isVisible())
        self.assertFalse(self.page.tree.isVisible())
        description = self.page.agent_empty_description
        self.assertGreaterEqual(description.contentsRect().height(), 3 * description.fontMetrics().height())
        self.page.open_chat_button.click()
        self.assertEqual(opened, [True])
        self.page.agent_tab.setFocus()
        QTest.keyClick(self.page.agent_tab, Qt.Key.Key_Space)
        self.assertTrue(self.page.agent_tab.isChecked())
        self.page.my_tab.click()
        self.assertFalse(self.page._agent_mode)
        self.assertTrue(self.page.my_tab.isChecked())

    def test_agent_commands_and_legacy_learned_are_visible_only_on_agent_tab(self):
        self.registry.save_command({'title': 'Agent task', 'action': 'time', 'phrases': ['agent task'], 'agent': True})
        self.registry.save_command({'title': 'Legacy learned', 'action': 'time', 'phrases': ['learned task'], 'learned': True})
        self.page.refresh()
        self.assertFalse(any(is_agent_command(item) for item in self.page._visible_entries()))
        selected = self.select_group('Morning')
        selected.setExpanded(True)
        self.page.agent_tab.click()
        self.assertEqual({item['title'] for item in self.page._visible_entries()}, {'Agent task', 'Legacy learned'})
        self.assertEqual(len(list(self.page._iter_leaves())), 2)
        self.page.search.setText('Legacy')
        visible = [item.text(0) for item in self.page._iter_leaves() if not item.isHidden()]
        self.assertEqual(visible, ['Legacy learned'])
        self.page.my_tab.click()
        self.assertEqual(self.page.tree.currentItem().text(0), 'Morning')
        self.assertTrue(self.page.tree.currentItem().isExpanded())

    def test_agent_new_command_and_folder_persist_in_agent_scope(self):
        self.page.agent_tab.click()
        with mock.patch('luxai.ui_commands.QInputDialog.getText', return_value=('Agent folder', True)):
            self.page.create_group('folders')
        self.select_group('Agent folder')
        data = {'title': 'Reviewed AI steps', 'action': 'time', 'phrases': ['reviewed agent command']}
        with mock.patch('luxai.ui_commands.CommandEditor') as editor:
            editor.return_value.exec.return_value = QDialog.DialogCode.Accepted
            editor.return_value.get_data.return_value = data
            self.page.create_button.click()
        fresh = CommandRegistry(self.registry.path)
        saved = next(item for item in fresh.custom if item['title'] == data['title'])
        self.assertTrue(saved['agent'])
        self.assertFalse(saved['learned'])
        self.assertEqual(saved['category'], 'Agent folder')
        self.assertIn('Agent folder', fresh.agent_groups['folders'])
        self.assertNotIn('Agent folder', fresh.groups['folders'])

    def test_invalid_import_is_atomic_and_dialog_cancellation_changes_nothing(self):
        before = self.registry.path.read_bytes()
        export = self.root/'bad.json'
        export.write_text(json.dumps({'version': 1, 'commands': [
            {'title': 'Valid', 'action': 'time', 'phrases': ['valid']},
            {'title': 'Invalid', 'action': 'run_arbitrary_script', 'phrases': ['invalid']},
        ]}))
        with (mock.patch.object(QFileDialog, 'getOpenFileName', return_value=(str(export), 'JSON')),
              mock.patch.object(self.page, '_show_error') as error):
            self.page.import_commands()
        error.assert_called_once()
        self.assertEqual(self.registry.path.read_bytes(), before)
        with mock.patch.object(QFileDialog, 'getSaveFileName', return_value=('', 'JSON')):
            self.page.export_commands()
        with mock.patch.object(QFileDialog, 'getOpenFileName', return_value=('', 'JSON')):
            self.page.import_commands()
        self.assertEqual(self.registry.path.read_bytes(), before)

    def test_deep_or_oversized_json_file_is_reported_without_registry_changes(self):
        before = self.registry.path.read_bytes()
        export = self.root/'unreadable.json'
        for content in ('[' * 1500 + '0' + ']' * 1500, ' ' * (4 * 1024 * 1024 + 1)):
            export.write_text(content)
            with (mock.patch.object(QFileDialog, 'getOpenFileName', return_value=(str(export), 'JSON')),
                  mock.patch.object(self.page, '_show_error') as error):
                self.page.import_commands()
            error.assert_called_once()
            self.assertEqual(self.registry.path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
