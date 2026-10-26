"""Updater failures must preserve user data and restore the previous code."""
from contextlib import ExitStack
import io
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
        self.assertFalse((self.root / "backups").exists())

    def legacy_backup(self, name="20261020-112233-123456-aaaaaaaaaaaa", *, manifest=True):
        saved = self.root / "backups" / name
        saved.mkdir(parents=True)
        (saved / "main.py").write_text("old application code")
        if manifest:
            saved.with_name(saved.name + ".manifest.json").write_text(json.dumps({
                "overwritten": ["main.py"], "new": ["luxai/extra.py"],
            }))
        return saved

    def test_success_removes_generated_legacy_backups_and_bootstrap_but_keeps_user_files(self):
        saved = self.legacy_backup()
        old = self.legacy_backup("20260901-112233-initial", manifest=False)
        manual = self.installed("backups/my-notes/important.txt", "personal")
        bootstrap = self.installed(".luxai_data/updater-bootstrap/Update.py.previous", "old updater")
        model = self.installed(".luxai_data/ocr/custom-model.dat", "keep model")
        result, _ = self.run_update(self.complete_archive())
        self.assertEqual(result, 0)
        self.assertFalse(saved.exists())
        self.assertFalse(saved.with_name(saved.name + ".manifest.json").exists())
        self.assertFalse(old.exists())
        self.assertFalse(bootstrap.exists())
        self.assertFalse(bootstrap.parent.exists())
        self.assertEqual(manual.read_text(), "personal")
        self.assertEqual(model.read_text(), "keep model")

    def test_already_current_update_removes_empty_backup_directory_and_known_copies(self):
        saved = self.legacy_backup()
        self.installed(".luxai_update_state.json", json.dumps({"commit": "b" * 40}))
        with mock.patch.object(updater, "request_json", return_value={"sha": "b" * 40}), mock.patch.object(
            updater, "upgrade_dependencies", return_value=True,
        ), mock.patch.object(updater, "ensure_local_ai_backend", return_value=True), mock.patch.object(
            updater, "download",
        ) as download:
            self.assertEqual(updater.perform_update(), 0)
        download.assert_not_called()
        self.assertFalse(saved.exists())
        self.assertFalse((self.root / "backups").exists())

    def test_cleanup_preserves_unrecognized_or_modified_backup_folders(self):
        modified = self.legacy_backup()
        (modified / "private-notes.txt").write_text("personal")
        unknown = self.legacy_backup("my-manual-backup")
        unmarked = self.legacy_backup("20261020-112233-123456-bbbbbbbbbbbb", manifest=False)
        old_with_data = self.legacy_backup("20260901-112233-initial", manifest=False)
        (old_with_data / "config.json").write_text('{"personal":true}')
        updater.cleanup_legacy_backups()
        for saved in (modified, unknown, unmarked, old_with_data):
            self.assertTrue((saved / "main.py").is_file())
        self.assertEqual((modified / "private-notes.txt").read_text(), "personal")

    def test_cleanup_never_traverses_a_windows_reparse_directory(self):
        saved = self.legacy_backup()
        ordinary_check = updater._is_link
        def is_reparse(path):
            return path == saved or ordinary_check(path)
        with mock.patch.object(updater, "_is_link", side_effect=is_reparse), mock.patch.object(
            updater.os, "walk", side_effect=AssertionError("Must not walk a reparse directory"),
        ):
            updater.cleanup_legacy_backups()
        self.assertTrue((saved / "main.py").exists())

    def test_cleanup_refuses_nested_links_and_invalid_manifests(self):
        saved = self.legacy_backup()
        nested = saved / "luxai"
        nested.mkdir()
        (nested / "voice.py").write_text("keep linked code")
        ordinary_check = updater._is_link
        def nested_reparse(path):
            return path == nested or ordinary_check(path)
        with mock.patch.object(updater, "_is_link", side_effect=nested_reparse):
            updater.cleanup_legacy_backups()
        self.assertTrue((saved / "main.py").exists())
        other = self.legacy_backup("20261020-112233-000000-bbbbbbbbbbbb")
        other.with_name(other.name + ".manifest.json").write_text('{"overwritten":["../outside"],"new":[]}')
        updater.cleanup_legacy_backups()
        self.assertTrue((other / "main.py").exists())

    def test_successful_transaction_discards_temporary_originals(self):
        self.installed("main.py", "old")
        created = []
        real_mkdtemp = tempfile.mkdtemp
        def mkdtemp(*args, **kwargs):
            path = Path(real_mkdtemp(*args, **kwargs))
            created.append(path)
            return str(path)
        with mock.patch.object(updater.tempfile, "mkdtemp", side_effect=mkdtemp):
            with updater.file_transaction([self.staged("main.py", "new")]):
                self.assertEqual(len(created), 1)
                self.assertEqual((created[0] / "main.py").read_text(), "old")
        self.assertFalse(created[0].exists())
        self.assertFalse((self.root / "backups").exists())

    def test_managed_failed_restore_retains_only_emergency_recovery_files(self):
        self.installed("main.py", "old")
        atomic_copy = updater._atomic_copy
        def fail_restore(source, destination):
            if source.parent.name.startswith("luxai_rollback_"):
                raise PermissionError("file is locked during restoration")
            return atomic_copy(source, destination)
        with mock.patch.object(updater, "_atomic_copy", side_effect=fail_restore):
            with self.assertRaisesRegex(RuntimeError, "Restaurare incompletă"):
                with updater.file_transaction([self.staged("main.py", "new")]):
                    raise RuntimeError("dependency installation failed")
        recoveries = list((self.root / ".luxai_data" / "update-recovery").glob("*/main.py"))
        self.assertEqual(len(recoveries), 1)
        self.assertEqual(recoveries[0].read_text(), "old")
        self.assertFalse((self.root / "backups").exists())

    def test_failed_recovery_move_keeps_original_temporary_files(self):
        self.installed("main.py", "old")
        atomic_copy = updater._atomic_copy
        original = []
        def fail_restore(source, destination):
            if source.parent.name.startswith("luxai_rollback_"):
                original.append(source)
                raise PermissionError("file is locked during restoration")
            return atomic_copy(source, destination)
        with mock.patch.object(updater, "_atomic_copy", side_effect=fail_restore), mock.patch.object(
            updater.shutil, "move", side_effect=OSError("Recovery directory unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "Restaurare incompletă"):
                with updater.file_transaction([self.staged("main.py", "new")]):
                    raise RuntimeError("dependency installation failed")
        self.assertEqual(len(original), 1)
        self.addCleanup(shutil.rmtree, original[0].parent)
        self.assertEqual(original[0].read_text(), "old")

    def test_update_success_and_rollback_survive_strict_cp1252_stdout(self):
        for dependencies in (True, False):
            with self.subTest(dependencies=dependencies):
                self.installed("main.py", "VALUE = 'old'\n")
                self.installed("config.json", '{"personal": "keep"}')
                self.installed(".luxai_update_state.json", json.dumps({"commit": "a" * 40}))
                raw = io.BytesIO()
                stream = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
                try:
                    with mock.patch.object(updater.sys, "stdout", stream):
                        result, packages = self.run_update(self.complete_archive(), dependencies=dependencies)
                    stream.flush()
                    output = raw.getvalue().decode("cp1252")
                finally:
                    stream.close()
                self.assertEqual(result, 0 if dependencies else 1)
                packages.assert_called_once()
                expected_code = "VALUE = 'new'\n" if dependencies else "VALUE = 'old'\n"
                self.assertEqual((self.root / "main.py").read_text(), expected_code)
                self.assertEqual(json.loads((self.root / "config.json").read_text()), {"personal": "keep"})
                expected_sha = "b" * 40 if dependencies else "a" * 40
                self.assertEqual(json.loads(updater.STATE_FILE.read_text())["commit"], expected_sha)
                self.assertIn("Actualizare automat", output)
                if not dependencies:
                    self.assertIn("restaurate la versiunea anterioar", output)

    def test_unicode_output_is_preserved_on_utf8_stream(self):
        raw = io.BytesIO()
        # Disable Windows CRLF conversion: this test verifies Unicode bytes,
        # not the operating system's preferred line separator.
        stream = io.TextIOWrapper(raw, encoding="utf-8", errors="strict", newline="\n")
        message = "Fișierele au fost păstrate. Привет!"
        try:
            with mock.patch.object(updater.sys, "stdout", stream):
                updater.report(message)
            stream.flush()
            self.assertEqual(raw.getvalue().decode("utf-8"), message + "\n")
        finally:
            stream.close()

    def test_broken_stdout_uses_stderr_without_masking_rollback_exception(self):
        original = self.installed("main.py", "old")
        broken_stdout = mock.Mock()
        broken_stdout.write.side_effect = BrokenPipeError("redirected output was closed")
        stderr = io.StringIO()
        with mock.patch.object(updater.sys, "stdout", broken_stdout), mock.patch.object(
            updater.sys, "stderr", stderr,
        ):
            with self.assertRaisesRegex(RuntimeError, "original update failure"):
                with updater.file_transaction([self.staged("main.py", "new")], self.backup):
                    raise RuntimeError("original update failure")
        self.assertEqual(original.read_text(), "old")
        self.assertIn("restaurate", stderr.getvalue())

    def test_unavailable_console_does_not_interrupt_rollback(self):
        original = self.installed("main.py", "old")
        with mock.patch.object(updater.sys, "stdout", None), mock.patch.object(updater.sys, "stderr", None):
            with self.assertRaisesRegex(RuntimeError, "original update failure"):
                with updater.file_transaction([self.staged("main.py", "new")], self.backup):
                    raise RuntimeError("original update failure")
        self.assertEqual(original.read_text(), "old")

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
