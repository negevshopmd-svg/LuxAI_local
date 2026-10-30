"""Selected collections survive export/import without activating or merging tasks."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from luxai.command_registry import CommandRegistry, MAX_USER_COMMANDS, checked_command, is_agent_command
from luxai.command_transfer import export_payload, import_payload


class CommandTransfer093dTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.source = CommandRegistry(self.folder / "source.json")
        self.destination = CommandRegistry(self.folder / "destination.json")

    def record(self, registry=None, identifier="user_original", **changes):
        raw = {
            "id": identifier, "title": "Daily report", "category": "Daily",
            "action": "open_app", "target": "notepad",
            "phrases": ["write daily report", "open my report"],
            "steps": [{"action": "open_app", "target": "notepad"},
                      {"action": "type_text", "target": "Report text"},
                      {"action": "hotkey", "target": "ctrl+s"}],
            "optional_words": ["please", "now"], "hotkey": "ctrl+alt+k",
            "schedule": {"mode": "daily", "time": "08:30"},
            "ask_before_run": True, "allow_chaining": False,
            "enabled": True,
        }
        raw.update(changes)
        return (registry or self.source).save_command(raw)

    def collection_payload(self):
        self.source.add_group("Daily", "collections")
        selected = [self.record(identifier="user_first"),
                    self.record(identifier="user_second", title="Second", phrases=["second report"])]
        self.record(identifier="user_unselected", title="Unselected", category="Other")
        payload = export_payload(self.source, group={
            "name": "Daily", "kind": "collections", "ids": [item["id"] for item in selected],
        })
        return selected, payload

    def test_selected_collection_round_trip_keeps_only_its_records_and_all_options(self):
        original, payload = self.collection_payload()
        before = copy.deepcopy(self.source.entries())
        imported = import_payload(self.destination, json.loads(json.dumps(payload)))
        self.assertEqual(self.source.entries(), before)
        self.assertEqual([item["title"] for item in imported], [item["title"] for item in original])
        self.assertEqual(len(self.destination.custom), 2)
        self.assertEqual(self.destination.groups["collections"], ["Daily"])
        for old, new in zip(original, imported):
            self.assertNotEqual(new["id"], old["id"])
            self.assertFalse(new["enabled"])
            self.assertFalse(new["builtin"])
            for key in ("title", "phrases", "category", "action", "target", "steps",
                        "optional_words", "voice_enabled", "hotkey", "schedule",
                        "ask_before_run", "allow_chaining"):
                self.assertEqual(new[key], old[key], key)
        fresh = CommandRegistry(self.destination.path)
        self.assertEqual(fresh.custom, imported)
        self.assertIsNone(fresh.match("write daily report"))

    def test_export_selected_command_does_not_include_other_library_records(self):
        first = self.record()
        self.record(identifier="user_other", category="Elsewhere")
        payload = export_payload(self.source, identifiers=[first["id"]])
        imported = import_payload(self.destination, payload)
        self.assertEqual(len(imported), 1)
        self.assertEqual(imported[0]["title"], first["title"])

    def test_empty_collection_metadata_is_not_lost(self):
        self.source.add_group("Empty collection", "collections")
        payload = export_payload(self.source, group={
            "name": "Empty collection", "kind": "collections", "ids": [],
        })
        self.assertEqual(import_payload(self.destination, payload), [])
        self.assertEqual(CommandRegistry(self.destination.path).groups["collections"], ["Empty collection"])

    def test_duplicate_import_creates_distinct_groups_and_ids(self):
        _, payload = self.collection_payload()
        first = import_payload(self.destination, payload)
        second = import_payload(self.destination, payload)
        self.assertEqual(len(self.destination.custom), 4)
        self.assertTrue(set(item["id"] for item in first).isdisjoint(item["id"] for item in second))
        self.assertEqual({item["category"] for item in first}, {"Daily"})
        self.assertEqual({item["category"] for item in second}, {"Daily (2)"})
        self.assertEqual(self.destination.groups["collections"], ["Daily", "Daily (2)"])

    def test_import_does_not_merge_with_an_implicit_category(self):
        _, payload = self.collection_payload()
        existing = self.record(self.destination, identifier="user_existing", phrases=["existing report"])
        imported = import_payload(self.destination, payload)
        self.assertEqual({item["category"] for item in imported}, {"Daily (2)"})
        self.assertEqual(next(item for item in self.destination.custom
                              if item["id"] == existing["id"]), existing)

    def test_invalid_later_record_rejects_entire_import_without_touching_disk(self):
        self.record(self.destination, identifier="user_existing", category="Unrelated")
        _, payload = self.collection_payload()
        payload["commands"].append({"id": "bad", "title": "Bad task", "phrases": ["bad"],
                                    "action": "arbitrary_executable", "target": "danger.exe"})
        before = self.destination.path.read_bytes()
        records_before = copy.deepcopy(self.destination.entries())
        groups_before = copy.deepcopy(self.destination.groups)
        with self.assertRaises(ValueError):
            import_payload(self.destination, payload)
        self.assertEqual(self.destination.path.read_bytes(), before)
        self.assertEqual(self.destination.entries(), records_before)
        self.assertEqual(self.destination.groups, groups_before)

    def test_failed_persist_rolls_back_imported_records_and_group_names(self):
        self.record(self.destination, identifier="user_existing", category="Unrelated")
        _, payload = self.collection_payload()
        before = self.destination.path.read_bytes()
        entries = copy.deepcopy(self.destination.entries())
        groups = copy.deepcopy(self.destination.groups)
        with mock.patch.object(self.destination, "_persist", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                import_payload(self.destination, payload)
        self.assertEqual(self.destination.entries(), entries)
        self.assertEqual(self.destination.groups, groups)
        self.assertEqual(self.destination.path.read_bytes(), before)

    def test_builtin_category_imports_as_disabled_personal_commands(self):
        builtins = self.source.entries()[:2]
        payload = export_payload(self.source, group={
            "name": "Default applications", "kind": None, "ids": [item["id"] for item in builtins],
        })
        imported = import_payload(self.destination, payload)
        self.assertEqual([item["target"] for item in imported], [item["target"] for item in builtins])
        self.assertTrue(all(not item["builtin"] and not item["enabled"] for item in imported))
        self.assertTrue(all(item["category"] == "Default applications" for item in imported))
        self.assertTrue(set(item["id"] for item in imported).isdisjoint(item["id"] for item in builtins))
        self.assertEqual(self.destination.builtin_overrides, {})

    def test_legacy_version_one_exports_remain_importable(self):
        old = self.record()
        for with_format in (False, True):
            with self.subTest(with_format=with_format):
                registry = CommandRegistry(self.folder / f"legacy-{with_format}.json")
                payload = {"version": 1, "commands": [old]}
                if with_format:
                    payload["format"] = "luxai-commands"
                imported = import_payload(registry, payload)
                self.assertEqual(imported[0]["title"], old["title"])
                self.assertFalse(imported[0]["enabled"])
                self.assertNotEqual(imported[0]["id"], old["id"])

    def test_unknown_transfer_format_or_version_fails_closed(self):
        old = self.record()
        for changes in ({"format": "another-program"}, {"version": 999},
                        {"commands": "not a command list"}):
            with self.subTest(changes=changes):
                payload = {"version": 1, "commands": [old]}
                payload.update(changes)
                with self.assertRaises(ValueError):
                    import_payload(self.destination, payload)
                self.assertFalse(self.destination.custom)
                self.assertFalse(self.destination.path.exists())

    def test_import_capacity_failure_keeps_existing_library(self):
        old = self.record()
        self.record(self.destination, identifier="user_existing", category="Existing")
        before = self.destination.path.read_bytes()
        with self.assertRaises(ValueError):
            import_payload(self.destination, {"version": 1, "commands": [old] * MAX_USER_COMMANDS})
        self.assertEqual(self.destination.path.read_bytes(), before)
        self.assertEqual(len(self.destination.custom), 1)

    def test_agent_scope_and_empty_groups_round_trip_without_user_groups(self):
        self.source.add_group("Agent workflows", "collections", agent=True)
        self.source.add_group("Empty agent folder", "folders", agent=True)
        self.source.add_group("Personal only", "folders")
        agent = self.record(identifier="user_agent", category="Agent workflows", agent=True)
        self.record(identifier="user_personal", category="Personal only")
        payload = export_payload(self.source, identifiers=[agent["id"]], agent=True)
        imported = import_payload(self.destination, payload)
        fresh = CommandRegistry(self.destination.path)
        self.assertEqual(len(imported), 1)
        self.assertTrue(is_agent_command(imported[0]))
        self.assertEqual(fresh.agent_groups["collections"], ["Agent workflows"])
        self.assertEqual(fresh.agent_groups["folders"], ["Empty agent folder"])
        self.assertNotIn("Personal only", fresh.groups["folders"])

    def test_explicit_import_scope_can_place_old_learned_record_in_my_commands(self):
        learned = self.record(identifier="learned_old", learned=True, agent=True)
        payload = {"version": 1, "commands": [learned]}
        personal = import_payload(self.destination, payload, agent=False)[0]
        self.assertFalse(is_agent_command(personal))
        self.assertFalse(personal["agent"])
        self.assertFalse(personal["learned"])

    def test_same_named_agent_and_personal_folder_are_renamed_independently(self):
        self.source.add_group("Work", agent=False)
        self.source.add_group("Work", agent=True)
        personal = self.record(identifier="user_personal", category="Work")
        agent = self.record(identifier="user_agent", category="Work", agent=True)
        self.source.rename_group("Work", "Agent work", agent=True)
        fresh = CommandRegistry(self.source.path)
        records = {item["id"]: item for item in fresh.custom}
        self.assertEqual(records[personal["id"]]["category"], "Work")
        self.assertEqual(records[agent["id"]]["category"], "Agent work")
        self.assertEqual(fresh.groups["folders"], ["Work"])
        self.assertEqual(fresh.agent_groups["folders"], ["Agent work"])

    def test_agent_metadata_is_boolean_and_legacy_learning_still_classifies(self):
        saved = self.record(agent=True)
        self.assertTrue(is_agent_command(CommandRegistry(self.source.path).custom[0]))
        legacy = dict(saved, agent=False, learned=True)
        self.assertTrue(is_agent_command(legacy))
        with self.assertRaises(ValueError):
            checked_command(dict(saved, agent="false"))

    def test_forced_tab_import_keeps_same_named_source_collections_apart(self):
        self.source.add_group("Work", "collections", agent=False)
        self.source.add_group("Work", "collections", agent=True)
        self.record(identifier="user_personal", category="Work")
        self.record(identifier="user_agent", category="Work", agent=True)
        payload = export_payload(self.source)
        imported = import_payload(self.destination, payload, agent=False)
        self.assertEqual([item["category"] for item in imported], ["Work", "Work (2)"])
        self.assertTrue(all(not is_agent_command(item) for item in imported))
        self.assertEqual(self.destination.groups["collections"], ["Work", "Work (2)"])

    def test_malformed_group_metadata_does_not_create_letter_named_folders(self):
        record = self.record()
        with self.assertRaises(ValueError):
            import_payload(self.destination, {"version": 1, "commands": [record],
                                              "groups": {"folders": "Work"}})
        self.assertFalse(self.destination.custom)
        self.assertFalse(self.destination.path.exists())


if __name__ == "__main__":
    unittest.main()
