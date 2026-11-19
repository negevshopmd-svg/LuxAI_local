"""0.4.1z: Jarvis.exe — Task Manager shows "Jarvis" with its icon, not "Python"."""
from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from luxai import jarvis_exe as je


def version_blob(description="Python", product="Python") -> bytes:
    parts = []
    for key, value in (("FileDescription", description), ("FileVersion", "3.11.9"), ("ProductName", product),
                       ("OriginalFilename", "pythonw.exe"), ("CompanyName", "Python Software Foundation")):
        parts.append(key.encode("utf-16-le") + b"\0\0" + b"\0\0" + value.encode("utf-16-le") + b"\0\0")
    return b"VS_VERSION".join(parts)


class BuilderTests(unittest.TestCase):
    def test_only_description_and_product_change_and_size_stays(self):
        blob = version_blob()
        renamed = je.rename_version(blob)
        self.assertEqual(len(renamed), len(blob))
        text = renamed.decode("utf-16-le", "replace")
        self.assertIn("FileDescription\0\0Jarvis", text)
        self.assertIn("ProductName\0\0Jarvis", text)
        self.assertIn("Python Software Foundation", text)  # other strings untouched
        self.assertIn("pythonw.exe", text)

    def test_icon_directory_points_at_icons(self):
        images = [(16, b"a" * 10), (256, b"b" * 20)]
        data = je.group_icon(images)
        self.assertEqual(struct.unpack("<HHH", data[:6]), (0, 1, 2))
        first = struct.unpack("<BBBBHHIH", data[6:20])
        last = struct.unpack("<BBBBHHIH", data[20:34])
        self.assertEqual(first, (16, 16, 0, 0, 1, 32, 10, 1))
        self.assertEqual(last, (0, 0, 0, 0, 1, 32, 20, 2))  # 0 = 256 px

    def test_reads_base_python_from_venv(self):
        venv = Path(tempfile.mkdtemp())
        (venv / "pyvenv.cfg").write_text("home = C:\\Python311\ninclude-system-site-packages = false\n", encoding="utf-8")
        self.assertEqual(je.base_python(venv), Path("C:\\Python311"))
        self.assertIsNone(je.base_python(Path(tempfile.mkdtemp())))

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_up_to_date_exe_is_not_rebuilt_and_failure_keeps_pythonw(self):
        root = Path(tempfile.mkdtemp())
        scripts = root / ".venv" / "Scripts"
        scripts.mkdir(parents=True)
        home = root / "base"
        home.mkdir()
        (home / "pythonw.exe").write_bytes(b"MZ fake")
        (root / ".venv" / "pyvenv.cfg").write_text(f"home = {home}\n", encoding="utf-8")
        key = f"{je.BUILD}|{je._digest(home / 'pythonw.exe')}|{je._digest(je.ICON_SVG)}|{je.theme_accent(root)}"
        (scripts / "Jarvis.exe").write_bytes(b"MZ built")
        (scripts / "Jarvis.exe.stamp").write_text(key, encoding="utf-8")
        with mock.patch.object(je, "patch_resources") as patch:
            self.assertEqual(je.ensure_jarvis_exe(root, log=lambda _: None), scripts / "Jarvis.exe")
        patch.assert_not_called()
        # A new Python version: rebuild; if the test start fails, nothing is replaced.
        (scripts / "Jarvis.exe.stamp").unlink()
        (scripts / "Jarvis.exe").unlink()
        with mock.patch.object(je, "patch_resources"), mock.patch.object(je, "icon_images", return_value=[]), \
                mock.patch.object(je, "works", return_value=False):
            self.assertIsNone(je.ensure_jarvis_exe(root, log=lambda _: None))
        self.assertFalse((scripts / "Jarvis.exe").exists())
        self.assertFalse((scripts / "Jarvis.new.exe").exists())

    def test_exe_icon_follows_the_theme_accent(self):
        root = Path(tempfile.mkdtemp())
        self.assertEqual(je.theme_accent(root), "#3978f6")  # no config yet
        (root / "config.json").write_text('{"ui_accent": "#f97316"}', encoding="utf-8")
        self.assertEqual(je.theme_accent(root), "#f97316")

    def test_helpers_treat_jarvis_exe_like_pythonw(self):
        from luxai.local_ai_setup import runtime_python
        folder = Path(tempfile.mkdtemp())
        (folder / "python.exe").write_bytes(b"")
        self.assertEqual(Path(runtime_python(folder / "Jarvis.exe")).name, "python.exe")

    def test_run_windows_starts_through_jarvis_exe_with_fallback(self):
        bat = (Path(__file__).resolve().parents[1] / "run_windows.bat").read_text(encoding="utf-8")
        self.assertIn("-m luxai.jarvis_exe", bat)
        # 0.4.2r: one start line; Jarvis.exe replaces the pythonw default when it is ready.
        self.assertLess(bat.index('set "JARVIS_EXE=.venv\\Scripts\\pythonw.exe"'),
                        bat.index('set "JARVIS_EXE=.venv\\Scripts\\Jarvis.exe"'))
        self.assertIn('start "" "%JARVIS_EXE%" "%~dp0launch_windows.py"', bat)


if __name__ == "__main__":
    unittest.main()
