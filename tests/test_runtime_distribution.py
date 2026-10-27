"""Runtime installation omits development sources and preserves personal files."""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

import Update as updater


REPO = Path(__file__).resolve().parents[1]


class RuntimeDistributionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "installed"
        self.root.mkdir()
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.multiple(
            updater, ROOT=self.root, BACKUP_ROOT=self.root / "backups",
            STATE_FILE=self.root / ".luxai_update_state.json",
        ))

    def put(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))
        return path

    def catalog(self, entries):
        data = {"format": 1, "files": {
            name: [hashlib.sha256(value.encode("utf-8")).hexdigest() for value in versions]
            for name, versions in entries.items()
        }}
        self.put(updater.CLEANUP_MANIFEST, json.dumps(data))
        return data

    def archive(self):
        path = self.base / "runtime.zip"
        with zipfile.ZipFile(path, "w") as archive:
            entries = {
                "main.py": "VALUE = 'new'\n", "launch_windows.py": "pass\n",
                "luxai/voice.py": "pass\n", "requirements.txt": "PySide6>=6.7\n",
                "run_windows.bat": "@echo off\n", "README.md": "User instructions\n",
                "README_RO.txt": "Instrucțiuni\n", "config.json": '{"default":true}',
                "tests/test_new.py": "invalid Python excluded from runtime!",
                "scripts/test_update_batch_windows.py": "raise AssertionError\n",
                ".github/workflows/check.yml": "development workflow\n",
                "PROJECT_HANDOFF.md": "new developer guide\n",
                "luxai/assets/icons/ui/README.md": "developer asset guide\n",
                updater.CLEANUP_MANIFEST: (self.root / updater.CLEANUP_MANIFEST).read_text(),
            }
            for name, content in entries.items():
                archive.writestr("project/" + name, content)
        return path

    def update(self, archive, dependencies=True, current=False):
        if current:
            self.put(".luxai_update_state.json", json.dumps({"commit": "b" * 40}))
        with (
            mock.patch.object(updater, "request_json", return_value={"sha": "b" * 40}),
            mock.patch.object(updater, "download", side_effect=lambda _url, target: shutil.copyfile(archive, target)) as download,
            mock.patch.object(updater, "validate_staged_requirements"),
            mock.patch.object(updater, "upgrade_dependencies", return_value=dependencies),
            mock.patch.object(updater, "ensure_local_ai_backend", return_value=True),
        ):
            result = updater.perform_update()
        return result, download

    def test_update_filters_development_files_cleans_historical_copies_and_keeps_personal_data(self):
        self.catalog({"PROJECT_HANDOFF.md": ["old guide\n", "new developer guide\n"],
                      "tests/test_old.py": ["old test\n"]})
        self.put("PROJECT_HANDOFF.md", "old guide\n")
        self.put("tests/test_old.py", "old test\n")
        self.put("tests/my-notes.txt", "personal notes")
        self.put("tests/test_custom.py", "my custom test")
        self.put("config.json", '{"personal":true}')
        self.put("settings.json", '{"volume":42}')
        self.put("models/private.gguf", "personal model")
        self.put("recordings/my-voice.wav", "personal recording")
        self.put(".luxai_secrets/key.bin", "private key fixture")
        result, _ = self.update(self.archive())
        self.assertEqual(result, 0)
        for name in ("PROJECT_HANDOFF.md", "tests/test_old.py", "tests/test_new.py",
                     "scripts/test_update_batch_windows.py", ".github/workflows/check.yml",
                     "luxai/assets/icons/ui/README.md"):
            self.assertFalse((self.root / name).exists(), name)
        self.assertTrue((self.root / "README.md").is_file())
        self.assertTrue((self.root / "README_RO.txt").is_file())
        for name, value in (("tests/my-notes.txt", "personal notes"),
                            ("tests/test_custom.py", "my custom test"),
                            ("config.json", '{"personal":true}'),
                            ("settings.json", '{"volume":42}'),
                            ("models/private.gguf", "personal model"),
                            ("recordings/my-voice.wav", "personal recording"),
                            (".luxai_secrets/key.bin", "private key fixture")):
            self.assertEqual((self.root / name).read_text(), value)

    def test_modified_known_files_and_unknown_markdown_remain(self):
        self.catalog({"PROJECT_HANDOFF.md": ["original"], "tests/test_old.py": ["original test"]})
        self.put("PROJECT_HANDOFF.md", "my edited guide")
        self.put("tests/test_old.py", "my edited test")
        self.put("tests/personal.md", "my notes")
        updater.cleanup_development_files()
        self.assertEqual((self.root / "PROJECT_HANDOFF.md").read_text(), "my edited guide")
        self.assertEqual((self.root / "tests/test_old.py").read_text(), "my edited test")
        self.assertEqual((self.root / "tests/personal.md").read_text(), "my notes")

    def test_failed_update_keeps_old_development_files(self):
        self.catalog({"PROJECT_HANDOFF.md": ["old guide"]})
        self.put("PROJECT_HANDOFF.md", "old guide")
        self.put("main.py", "VALUE = 'old'\n")
        result, _ = self.update(self.archive(), dependencies=False)
        self.assertEqual(result, 1)
        self.assertEqual((self.root / "PROJECT_HANDOFF.md").read_text(), "old guide")
        self.assertEqual((self.root / "main.py").read_text(), "VALUE = 'old'\n")

    def test_already_current_update_retries_cleanup_without_download(self):
        self.catalog({"tests/test_old.py": ["old test"]})
        self.put("tests/test_old.py", "old test")
        result, download = self.update(self.base / "not-needed.zip", current=True)
        self.assertEqual(result, 0)
        download.assert_not_called()
        self.assertFalse((self.root / "tests").exists())
        updater.cleanup_development_files()  # Idempotent after empty-directory removal.

    def test_cleanup_command_handles_fresh_install_without_network(self):
        shutil.copyfile(REPO / "Update.py", self.root / "Update.py")
        self.catalog({"PROJECT_HANDOFF.md": ["bundled guide"], "tests/test_old.py": ["bundled test"]})
        self.put("PROJECT_HANDOFF.md", "bundled guide")
        self.put("tests/test_old.py", "bundled test")
        self.put("README.md", "User help")
        result = subprocess.run([sys.executable, str(self.root / "Update.py"), "--clean-installation"],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "PROJECT_HANDOFF.md").exists())
        self.assertFalse((self.root / "tests").exists())
        self.assertEqual((self.root / "README.md").read_text(), "User help")
        installer = (REPO / "scripts/install_windows.ps1").read_text()
        self.assertIn("@('Update.py', '--clean-installation')", installer)

    def test_actual_fresh_bundle_removes_all_current_development_sources(self):
        shutil.copyfile(REPO / "Update.py", self.root / "Update.py")
        shutil.copyfile(REPO / updater.CLEANUP_MANIFEST, self.root / updater.CLEANUP_MANIFEST)
        sources = [REPO / "PROJECT_HANDOFF.md", *list((REPO / "tests").glob("*.py")),
                   *list((REPO / ".github/workflows").glob("*")),
                   REPO / "scripts/test_update_batch_windows.py",
                   *list((REPO / "luxai/assets/icons").glob("*/README.md"))]
        for source in sources:
            target = self.root / source.relative_to(REPO)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        for help_file in ("README.md", "README_RO.md", "README_RO.txt", "CHANGELOG.md",
                          "COMMANDS.md", "ONLINE_AI.md", "VOICE_TOOLS.md", "voices/README.md"):
            target = self.root / help_file
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / help_file, target)
        result = subprocess.run([sys.executable, str(self.root / "Update.py"), "--clean-installation"],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        for source in sources:
            self.assertFalse((self.root / source.relative_to(REPO)).exists(), str(source))
        for help_file in ("README.md", "README_RO.md", "README_RO.txt", "CHANGELOG.md",
                          "COMMANDS.md", "ONLINE_AI.md", "VOICE_TOOLS.md", "voices/README.md"):
            self.assertEqual((self.root / help_file).read_bytes(), (REPO / help_file).read_bytes())

    def test_git_directory_or_worktree_file_preserves_sources(self):
        self.catalog({"PROJECT_HANDOFF.md": ["bundled guide"]})
        self.put("PROJECT_HANDOFF.md", "bundled guide")
        git = self.root / ".git"
        git.mkdir()
        updater.cleanup_development_files()
        self.assertTrue((self.root / "PROJECT_HANDOFF.md").exists())
        git.rmdir()
        git.write_text("gitdir: elsewhere")
        updater.cleanup_development_files()
        self.assertTrue((self.root / "PROJECT_HANDOFF.md").exists())

    def test_rejects_entire_unsafe_catalog_before_deleting_any_file(self):
        self.put("PROJECT_HANDOFF.md", "guide")
        for unsafe in ("../outside.txt", "/outside.txt", "tests/../../config.json",
                       "tests/config.json", "models/model.gguf", "config.json",
                       "tests/file.py.", "tests/CON.py", "tests\\file.py", "tests/file\0.py"):
            with self.subTest(path=unsafe):
                self.catalog({"PROJECT_HANDOFF.md": ["guide"], unsafe: ["personal"]})
                updater.cleanup_development_files()
                self.assertTrue((self.root / "PROJECT_HANDOFF.md").exists())

    def test_symlink_or_reparse_ancestor_never_reaches_external_files(self):
        self.catalog({"tests/test_old.py": ["old test"]})
        self.put("tests/test_old.py", "old test")
        real_is_link = updater._is_link
        with mock.patch.object(updater, "_is_link", side_effect=lambda path: path == self.root / "tests" or real_is_link(path)):
            updater.cleanup_development_files()
        self.assertTrue((self.root / "tests/test_old.py").exists())
        shutil.rmtree(self.root / "tests")
        external = self.base / "external"
        external.mkdir()
        (external / "test_old.py").write_text("old test")
        try:
            (self.root / "tests").symlink_to(external, target_is_directory=True)
        except OSError:
            return  # Windows runners may lack symlink privilege; reparse case ran above.
        updater.cleanup_development_files()
        self.assertEqual((external / "test_old.py").read_text(), "old test")

    def test_manifested_legacy_backup_cannot_delete_protected_data(self):
        saved = "backups/20261020-112233-123456-aaaaaaaaaaaa"
        self.put(saved + "/config.json", "personal settings")
        self.put(saved + ".manifest.json", json.dumps({"overwritten": ["config.json"], "new": []}))
        updater.cleanup_legacy_backups()
        self.assertEqual((self.root / saved / "config.json").read_text(), "personal settings")

    def test_catalog_covers_current_development_sources_and_historical_files(self):
        data = json.loads((REPO / updater.CLEANUP_MANIFEST).read_text())
        sources = [REPO / "PROJECT_HANDOFF.md", *list((REPO / "tests").glob("*.py")),
                   *list((REPO / ".github/workflows").glob("*")),
                   REPO / "scripts/test_update_batch_windows.py",
                   *list((REPO / "luxai/assets/icons").glob("*/README.md"))]
        for path in sources:
            rel = path.relative_to(REPO).as_posix()
            with self.subTest(path=rel):
                self.assertIn(hashlib.sha256(path.read_bytes()).hexdigest(), data["files"].get(rel, []),
                              "Refresh catalog with python tests/build_runtime_manifest.py")
        self.assertGreater(len(data["files"]["PROJECT_HANDOFF.md"]), 2)


if __name__ == "__main__":
    unittest.main()
