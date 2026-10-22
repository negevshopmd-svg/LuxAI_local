"""Prevent malformed dependencies from breaking Update.bat on Windows."""
from pathlib import Path
import unittest
from pip._vendor.packaging.requirements import Requirement, InvalidRequirement


ROOT = Path(__file__).resolve().parents[1]


class RequirementsTests(unittest.TestCase):
    def test_each_line_parses_as_exactly_one_pep508_requirement(self):
        filename = ROOT / "requirements.txt"
        seen = set()
        for number, raw_line in enumerate(filename.read_text(encoding="utf-8").splitlines(), 1):
            entry = raw_line.split("#", 1)[0].strip()
            if not entry:
                continue
            with self.subTest(line=number, requirement=entry):
                try:
                    spec = Requirement(entry)
                except InvalidRequirement as error:
                    self.fail(f"requirements.txt:{number}: {error}")
                self.assertNotIn(spec.name.casefold(), seen, f"Duplicate package: {spec.name}")
                seen.add(spec.name.casefold())
        for package in ("pyautogui", "pycaw", "comtypes", "Send2Trash"):
            self.assertIn(package.casefold(), seen)


if __name__ == "__main__":
    unittest.main()
