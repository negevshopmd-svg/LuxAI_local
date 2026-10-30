"""Editable presets and folder changes survive reload without losing user data."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from luxai.command_registry import BUILTINS, CommandRegistry


class EditablePresetStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "commands.json"
        self.registry = CommandRegistry(self.path)
        self.telegram = self.registry.match("открой телеграм")
        self.game = self.registry.match("launch war thunder")

    def personal(self, **changes):
        record = {"id": "user_existing", "title": "Personal", "action": "time",
                  "phrases": ["personal clock"], "category": "Work"}
        record.update(changes)
        return record

    def edited(self, **changes):
        record = dict(self.telegram, title="My helper", action="time", target="",
                      phrases=["my helper"], optional_words=["please"],
                      hotkey="ctrl+alt+k", ask_before_run=True, allow_chaining=False)
        record.update(changes)
        return record

    def test_builtin_edit_round_trips_all_metadata_with_stable_identity(self):
        original_definitions = copy.deepcopy(BUILTINS)
        self.registry.save_custom(self.personal())
        saved = self.registry.save_command(self.edited())
        again = CommandRegistry(self.path)
        entry = again.match("please my helper")
        self.assertEqual(entry["id"], self.telegram["id"])
        self.assertTrue(entry["builtin"])
        self.assertTrue(entry["customized"])
        self.assertEqual(entry["title"], "My helper")
        self.assertEqual(entry["action"], "time")
        self.assertEqual(entry["hotkey"], "ctrl+alt+k")
        self.assertTrue(entry["ask_before_run"])
        self.assertFalse(entry["allow_chaining"])
        self.assertIsNone(again.match("открой телеграм"))
        self.assertTrue(again.disabled_match("открой телеграм"))
        self.assertFalse(again.disabled_match("please my helper"))
        self.assertEqual(again.custom[0]["id"], "user_existing")
        self.assertEqual(BUILTINS, original_definitions)
        self.assertEqual(saved["id"], self.telegram["id"])

    def test_deleted_default_stays_deleted_after_reload_and_unrelated_save(self):
        self.registry.save_custom(self.personal())
        self.registry.remove_command(self.telegram["id"])
        again = CommandRegistry(self.path)
        again.save_custom(self.personal(title="Changed personal"))
        again = CommandRegistry(self.path)
        self.assertNotIn(self.telegram["id"], {item["id"] for item in again.entries()})
        self.assertIsNone(again.match("открой телеграм"))
        self.assertTrue(again.disabled_match("открой телеграм"))
        self.assertIsNotNone(again.match("personal clock"))
        self.assertIn(self.telegram["id"], json.loads(self.path.read_text())["deleted_builtins"])
        with self.assertRaisesRegex(ValueError, "deleted"):
            again.save_command(self.telegram)  # A stale open editor cannot resurrect it.

    def test_original_presets_can_be_deleted_through_legacy_api(self):
        self.registry.remove_custom(self.telegram["id"])
        self.assertNotIn(self.telegram["id"], {item["id"] for item in self.registry.entries()})

    def test_edited_default_enable_state_round_trips_and_can_be_reenabled(self):
        self.registry.set_enabled(self.telegram["id"], False)
        disabled = next(item for item in self.registry.entries() if item["id"] == self.telegram["id"])
        self.registry.save_command(dict(disabled, title="Changed while disabled"))
        again = CommandRegistry(self.path)
        self.assertIsNone(again.match("открой телеграм"))
        again.set_enabled(self.telegram["id"], True)
        enabled = CommandRegistry(self.path).match("открой телеграм")
        self.assertEqual(enabled["title"], "Changed while disabled")
        self.assertTrue(enabled["enabled"])

    def test_active_personal_phrase_can_replace_a_deleted_or_edited_default(self):
        for deleted in (False, True):
            with self.subTest(deleted=deleted):
                path = Path(self.temp.name) / f"alias-{deleted}.json"
                registry = CommandRegistry(path)
                if deleted:
                    registry.remove_command(self.telegram["id"])
                else:
                    registry.save_command(self.edited())
                registry.save_command(self.personal(phrases=["открой телеграм"]))
                self.assertEqual(registry.match("открой телеграм")["id"], "user_existing")
                self.assertFalse(registry.disabled_match("открой телеграм"))

    def test_original_phrase_replaced_by_optional_word_rules_is_not_blocked(self):
        self.registry.save_command(self.edited(phrases=["телеграм"], optional_words=["открой"]))
        self.assertEqual(self.registry.match("открой телеграм")["id"], self.telegram["id"])
        self.assertFalse(self.registry.disabled_match("открой телеграм"))

    def test_voice_disabled_override_suppresses_both_old_and_new_voice_phrases(self):
        self.registry.save_command(self.edited(voice_enabled=False))
        self.assertIsNone(self.registry.match("my helper"))
        self.assertTrue(self.registry.disabled_match("my helper"))
        self.assertTrue(self.registry.disabled_match("открой телеграм"))

    def test_legacy_file_preserves_custom_records_disabled_defaults_and_groups(self):
        self.path.write_text(json.dumps({"version": 1, "disabled_builtins": [self.telegram["id"]],
                                        "commands": [self.personal()], "folders": ["Work"],
                                        "collections": ["Daily"]}), encoding="utf-8")
        again = CommandRegistry(self.path)
        self.assertIsNone(again.match("открой телеграм"))
        self.assertTrue(again.disabled_match("открой телеграм"))
        self.assertIsNotNone(again.match("personal clock"))
        again.save_command(self.edited())
        again = CommandRegistry(self.path)
        self.assertEqual(again.groups, {"folders": ["Work"], "collections": ["Daily"]})
        self.assertEqual(again.match("my helper")["id"], self.telegram["id"])

    def test_untrusted_overrides_still_obey_action_allowlist_and_id_boundary(self):
        with self.assertRaises(ValueError):
            self.registry.save_command(self.edited(action="shell", target="cmd.exe"))
        with self.assertRaises(ValueError):
            self.registry.save_command(self.personal(id="built_not_a_real_preset"))
        self.path.write_text(json.dumps({
            "commands": [self.personal(id=self.telegram["id"]), self.personal()],
            "builtin_overrides": {self.telegram["id"]: self.edited(action="shell"),
                                  "built_fake": self.personal(id="built_fake")},
        }), encoding="utf-8")
        again = CommandRegistry(self.path)
        self.assertEqual(len(again.custom), 1)
        self.assertEqual(again.match("открой телеграм")["action"], "open_app")
        self.assertFalse(again.builtin_overrides)

    def test_commands_field_malformed_json_does_not_break_preset_loading(self):
        for commands in (None, {}, "commands"):
            with self.subTest(commands=commands):
                self.path.write_text(json.dumps({"commands": commands}), encoding="utf-8")
                again = CommandRegistry(self.path)
                self.assertIsNotNone(again.match("открой телеграм"))
                self.assertEqual(again.custom, [])

    def test_returned_entries_and_saved_values_cannot_mutate_persistent_state(self):
        saved = self.registry.save_command(self.edited())
        saved["phrases"].append("outside mutation")
        entries = self.registry.entries()
        edited = next(item for item in entries if item["id"] == self.telegram["id"])
        edited["optional_words"].append("outside")
        self.assertIsNone(self.registry.match("outside mutation"))
        self.assertIsNone(self.registry.match("outside my helper"))

    def test_bulk_save_and_delete_persist_once_and_rollback_invalid_members(self):
        before = self.registry.entries()
        with mock.patch.object(self.registry, "_persist", wraps=self.registry._persist) as persist:
            self.registry.save_commands([self.edited(), self.personal()])
            persist.assert_called_once()
        after = self.registry.entries()
        with self.assertRaises(ValueError):
            self.registry.save_commands([self.edited(title="Would change"), self.personal(action="shell")])
        self.assertEqual(self.registry.entries(), after)
        with self.assertRaises(ValueError):
            self.registry.remove_commands([self.telegram["id"], "user_missing"])
        self.assertEqual(self.registry.entries(), after)
        with mock.patch.object(self.registry, "_persist", wraps=self.registry._persist) as persist:
            self.registry.remove_commands([self.telegram["id"], "user_existing"])
            persist.assert_called_once()
        self.assertEqual(len(self.registry.entries()), len(before) - 1)

    def test_disk_failure_rolls_back_edit_delete_and_toggle(self):
        self.registry.save_command(self.edited())
        original = self.registry.entries()
        for operation in (
            lambda: self.registry.save_command(self.edited(title="Unwritten")),
            lambda: self.registry.remove_command(self.telegram["id"]),
            lambda: self.registry.set_group_enabled([self.telegram["id"], self.game["id"]], False),
        ):
            with self.subTest(operation=operation), mock.patch.object(self.registry, "_persist", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    operation()
                self.assertEqual(self.registry.entries(), original)
                self.assertEqual(CommandRegistry(self.path).entries(), original)

    def test_group_toggle_is_atomic_and_updates_builtin_override_state(self):
        self.registry.save_commands([self.edited(), self.personal()])
        ids = [self.telegram["id"], self.game["id"], "user_existing"]
        with mock.patch.object(self.registry, "_persist", wraps=self.registry._persist) as persist:
            self.registry.set_group_enabled(ids, False)
            persist.assert_called_once()
        again = CommandRegistry(self.path)
        self.assertTrue(all(not item["enabled"] for item in again.entries() if item["id"] in ids))
        again.set_group_enabled(ids, True)
        self.assertTrue(all(item["enabled"] for item in CommandRegistry(self.path).entries() if item["id"] in ids))

    def test_rename_and_delete_folder_preserve_commands_and_builtin_edits(self):
        self.registry.add_group("Work")
        self.registry.save_commands([self.edited(category="Work"), self.personal()])
        self.registry.rename_group("Work", "Projects")
        again = CommandRegistry(self.path)
        self.assertEqual(again.groups["folders"], ["Projects"])
        moved = [item for item in again.entries() if item["id"] in (self.telegram["id"], "user_existing")]
        self.assertEqual({item["category"] for item in moved}, {"Projects"})
        again.remove_group("Projects")
        again = CommandRegistry(self.path)
        moved = [item for item in again.entries() if item["id"] in (self.telegram["id"], "user_existing")]
        self.assertEqual({item["category"] for item in moved}, {"Мои команды"})
        self.assertIsNotNone(again.match("my helper"))
        self.assertIsNotNone(again.match("personal clock"))
        self.assertFalse(again.groups["folders"])

    def test_failed_folder_operation_restores_names_and_categories(self):
        self.registry.add_group("Work")
        self.registry.save_custom(self.personal())
        for operation in (lambda: self.registry.rename_group("Work", "Unwritten"),
                          lambda: self.registry.remove_group("Work")):
            with mock.patch.object(self.registry, "_persist", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    operation()
            self.assertEqual(self.registry.groups["folders"], ["Work"])
            self.assertEqual(self.registry.custom[0]["category"], "Work")


if __name__ == "__main__":
    unittest.main()
