"""Windows installer inventory and up-to-date dependency policy regression tests."""
from pathlib import Path
import unittest


class WindowsInstallPolicyTests(unittest.TestCase):
    def test_all_supported_python_minors_are_checked(self):
        root = Path(__file__).resolve().parents[1]
        setup = (root / "scripts" / "install_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("foreach ($minor in @(11, 12, 13, 14))", setup)
        self.assertIn("function Get-InstalledPythonInventory", setup)
        self.assertIn("function Find-PreferredPython", setup)
        self.assertIn("Find-CompatiblePython -MaxMinor 14 -StableOnly", setup)
        self.assertIn("Show-PythonCompatibility", setup)
        self.assertIn("[switch]$InventoryOnly", setup)

    def test_upgrade_already_installed_packages_without_crossing_requirements(self):
        root = Path(__file__).resolve().parents[1]
        setup = (root / "scripts" / "install_windows.ps1").read_text(encoding="utf-8")
        updater = (root / "Update.py").read_text(encoding="utf-8")
        for source in (setup, updater):
            self.assertIn("'--upgrade'", source)
            self.assertIn("'--upgrade-strategy'", source)
            self.assertIn("'only-if-needed'", source)
            self.assertIn("'pip'", source)
            self.assertIn("'check'", source)
            self.assertIn("requirements", source)
        self.assertIn("if current_sha == latest_sha:", updater)
        self.assertIn("if not upgrade_dependencies():", updater)
        self.assertIn("def upgrade_dependencies()", updater)

    def test_wheels_can_be_upgraded_when_already_installed(self):
        root = Path(__file__).resolve().parents[1]
        ai_setup = (root / "luxai" / "local_ai_setup.py").read_text(encoding="utf-8")
        self.assertIn('"--upgrade"', ai_setup)
        self.assertIn('"--only-binary=:all:"', ai_setup)


if __name__ == "__main__":
    unittest.main()
