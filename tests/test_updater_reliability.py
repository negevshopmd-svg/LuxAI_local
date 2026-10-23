"""Updater failures must preserve user data and restore the previous code."""
from contextlib import ExitStack
import json
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
from unittest import mock
import zipfile

import Update as updater


class UpdaterReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "installed"
        self.root.mkdir()
        self.source = self.base / "source"
        self.source.mkdir()
        self.backup = self.root / "backups" / "attempt"
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.multiple(
            updater, ROOT=self.root, BACKUP_ROOT=self.root / "backups",
            STATE_FILE=self.root / ".luxai_update_state.json",
        ))

    def staged(self, name, content):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path, Path(name)

    def installed(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def make_archive(self, entries):
        path = self.base / "source.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in entries:
                archive.writestr(name, data)
        return path

    def complete_archive(self, main="VALUE = 'new'\n"):
        return self.make_archive([
            ("project/main.py", main),
            ("project/launch_windows.py", "VALUE = 'launcher'\n"),
            ("project/luxai/voice.py", "VALUE = 'voice'\n"),
            ("project/requirements.txt", "PySide6>=6.7\n"),
            ("project/run_windows.bat", "@echo off\n"),
            ("project/config.json", '{"user": "must not overwrite"}'),
        ])

    def run_update(self, archive, dependencies=True):
        def download(_url, target):
            shutil.copyfile(archive, target)

        with mock.patch.object(updater, "request_json", return_value={"sha": "b" * 40}), mock.patch.object(
            updater, "download", side_effect=download,
        ), mock.patch.object(updater, "validate_staged_requirements"), mock.patch.object(
            updater, "upgrade_dependencies", return_value=dependencies,
        ) as packages, mock.patch.object(updater, "ensure_local_ai_backend", return_value=True):
            result = updater.perform_update()
        return result, packages

    def test_dependency_failure_restores_code_removes_new_files_and_keeps_state(self):
        self.installed("main.py", "VALUE = 'old'\n")
        self.installed("config.json", '{"personal": "keep"}')
        state = self.installed(".luxai_update_state.json", json.dumps({"commit": "a" * 40}))
        previous_state = state.read_bytes()
        result, _ = self.run_update(self.complete_archive(), dependencies=False)
        self.assertEqual(result, 1)
        self.assertEqual((self.root / "main.py").read_text(), "VALUE = 'old'\n")
        self.assertFalse((self.root / "launch_windows.py").exists())
        self.assertFalse((self.root / "luxai" / "voice.py").exists())
        self.assertEqual(state.read_bytes(), previous_state)
        self.assertEqual(json.loads((self.root / "config.json").read_text()), {"personal": "keep"})

    def test_success_updates_code_and_state_while_retaining_personal_configuration(self):
        self.installed("main.py", "VALUE = 'old'\n")
        self.installed("config.json", '{"personal": "keep"}')
        result, packages = self.run_update(self.complete_archive())
        self.assertEqual(result, 0)
        packages.assert_called_once()
        self.assertEqual((self.root / "main.py").read_text(), "VALUE = 'new'\n")
        self.assertEqual(json.loads(updater.STATE_FILE.read_text())["commit"], "b" * 40)
        self.assertEqual(json.loads((self.root / "config.json").read_text()), {"personal": "keep"})
        backups = list((self.root / "backups").glob("*/main.py"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "VALUE = 'old'\n")

    def test_invalid_staged_python_never_replaces_installed_files_or_runs_pip(self):
        self.installed("main.py", "VALUE = 'old'\n")
        result, packages = self.run_update(self.complete_archive("def invalid(:\n"))
        self.assertEqual(result, 1)
        packages.assert_not_called()
        self.assertEqual((self.root / "main.py").read_text(), "VALUE = 'old'\n")
        self.assertFalse(updater.STATE_FILE.exists())

    def test_failure_during_second_copy_restores_first_file(self):
        original = self.installed("main.py", "old")
        files = [self.staged("main.py", "new"), self.staged("second.py", "new second")]
        atomic_copy = updater._atomic_copy

        def fail_second(source, destination):
            if source == self.source / "second.py":
                raise PermissionError("file locked by another application")
            return atomic_copy(source, destination)

        with mock.patch.object(updater, "_atomic_copy", side_effect=fail_second):
            with self.assertRaises(PermissionError):
                with updater.file_transaction(files, self.backup):
                    self.fail("partially applied transaction must never start its body")
        self.assertEqual(original.read_text(), "old")
        self.assertFalse((self.root / "second.py").exists())

    def test_keyboard_interrupt_also_restores_previous_code(self):
        original = self.installed("main.py", "old")
        with self.assertRaises(KeyboardInterrupt):
            with updater.file_transaction([self.staged("main.py", "new")], self.backup):
                raise KeyboardInterrupt
        self.assertEqual(original.read_text(), "old")

    def test_rollback_failure_is_reported_and_original_backup_is_retained(self):
        self.installed("main.py", "old")
        atomic_copy = updater._atomic_copy

        def fail_restoration(source, destination):
            if source == self.backup / "main.py":
                raise PermissionError("file is now locked")
            return atomic_copy(source, destination)

        with mock.patch.object(updater, "_atomic_copy", side_effect=fail_restoration):
            with self.assertRaisesRegex(RuntimeError, "Restaurare incompletă"):
                with updater.file_transaction([self.staged("main.py", "new")], self.backup):
                    raise RuntimeError("failed package install")
        self.assertEqual((self.backup / "main.py").read_text(), "old")

    def test_destination_symlinks_cannot_overwrite_files_outside_checkout(self):
        outside = self.base / "outside"
        outside.mkdir()
        target = outside / "main.py"
        target.write_text("personal outside file")
        link = self.root / "linked"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("Creating symlinks requires Windows developer mode or privileges")
        with self.assertRaisesRegex(RuntimeError, "afara proiectului|legătură locală"):
            with updater.file_transaction([self.staged("linked/main.py", "new")], self.backup):
                self.fail("outside destination must be rejected before copying")
        self.assertEqual(target.read_text(), "personal outside file")

    def test_user_paths_are_preserved_case_insensitively(self):
        for name in (
            "Config.JSON", ".VENV/Lib/site-packages/local.py", ".luxai_data/commands.json",
            "config.local.json", "voices/custom.ONNX", "voices/custom.onnx.json",
            "models/custom.gguf", ".venv.old-personal/file.py", ".env.local",
            ".luxai_update_state.json",
        ):
            with self.subTest(name=name):
                self.assertTrue(updater.is_preserved(Path(name)))
        self.assertFalse(updater.is_preserved(Path("luxai/voice.py")))
        self.assertFalse(updater.is_preserved(Path("voices/README.md")))

    def test_traversal_and_windows_alias_paths_are_rejected_before_extraction(self):
        for name in ("../escape", "/absolute", "root/C:escape", "root/NUL.txt", "root/main.py."):
            with self.subTest(name=name):
                archive = self.make_archive([(name, "unsafe")])
                with self.assertRaises(RuntimeError):
                    updater.safe_extract(archive, self.base / "extracted")

    def test_case_aliases_and_archive_symlinks_are_rejected(self):
        archive = self.make_archive([("Root/main.py", "first"), ("root/MAIN.PY", "second")])
        with self.assertRaises(RuntimeError):
            updater.safe_extract(archive, self.base / "extracted")
        link = zipfile.ZipInfo("root/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive = self.make_archive([(link, "../../outside")])
        with self.assertRaises(RuntimeError):
            updater.safe_extract(archive, self.base / "extracted")

    def test_archive_expansion_limit_is_checked_before_decompression(self):
        archive = self.make_archive([("root/file.txt", "five!")])
        with mock.patch.object(updater, "MAX_EXTRACTED_BYTES", 4), mock.patch.object(
            zipfile.ZipFile, "testzip", side_effect=AssertionError("decompression must not start"),
        ):
            with self.assertRaisesRegex(RuntimeError, "limita"):
                updater.safe_extract(archive, self.base / "extracted")

    def test_state_write_failure_does_not_truncate_previous_state(self):
        state = self.installed(".luxai_update_state.json", '{"commit":"old"}')
        with mock.patch.object(updater.os, "replace", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                updater.write_update_state("b" * 40)
        self.assertEqual(state.read_text(), '{"commit":"old"}')
        self.assertFalse(list(self.root.glob(".luxai-state-*")))

    def test_second_updater_is_rejected_and_crash_free_lock_can_be_reused(self):
        with updater.updater_lock():
            with self.assertRaisesRegex(RuntimeError, "rulează deja"):
                with updater.updater_lock():
                    self.fail("a second updater must not run concurrently")
        with updater.updater_lock():
            pass


if __name__ == "__main__":
    unittest.main()
