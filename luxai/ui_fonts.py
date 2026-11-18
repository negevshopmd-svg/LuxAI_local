"""Register bundled UI fonts locally and normalize saved font preferences."""
from pathlib import Path

from PySide6.QtGui import QFontDatabase, QGuiApplication


ROOT = Path(__file__).resolve().parents[1]
PROJECT_FONT = "Fuzzy Bubbles"
# Fuzzy Bubbles has no Cyrillic letters. Pangolin is a similar hand-written font
# with Russian and Romanian letters, so Russian text keeps the same look
# instead of switching to Onest in the middle of the interface.
CYRILLIC_COMPANION = "Pangolin"


def normalize_font_family(value):
    if value == "Arial":
        return PROJECT_FONT
    return value if value in ("Onest", PROJECT_FONT, "system") else "Onest"


def register_project_fonts():
    """Load the shipped font files once per application, without downloads."""
    app = QGuiApplication.instance()
    if app is None:
        return False
    registered = list(app.property("luxaiRegisteredFontFiles") or [])
    families = list(app.property("luxaiRegisteredFontFamilies") or [])
    paths = [ROOT / "luxai" / "assets" / "fonts" / "Onest.ttf"]
    paths.extend(ROOT / "assets" / "fonts" / name for name in
                 ("FuzzyBubbles-Regular.ttf", "FuzzyBubbles-Bold.ttf", "Pangolin-Regular.ttf"))
    for path in paths:
        if str(path) in registered or not path.is_file():
            continue
        identifier = QFontDatabase.addApplicationFont(str(path))
        if identifier >= 0:
            registered.append(str(path))
            families.extend(QFontDatabase.applicationFontFamilies(identifier))
    app.setProperty("luxaiRegisteredFontFiles", registered)
    app.setProperty("luxaiRegisteredFontFamilies", sorted(set(families)))
    return PROJECT_FONT in families


def font_families(value):
    """Ordered families: Qt takes each letter from the first one that has it."""
    family = normalize_font_family(value)
    return {
        PROJECT_FONT: [PROJECT_FONT, CYRILLIC_COMPANION, "Onest", "Segoe UI"],
        "Onest": ["Onest", "Segoe UI"],
        "system": ["Segoe UI", "Onest"],
    }[family]


def font_stack(value):
    family = normalize_font_family(value)
    return {
        PROJECT_FONT: "'Fuzzy Bubbles', 'Pangolin', 'Onest', 'Segoe UI'",
        "Onest": "'Onest', 'Segoe UI'",
        "system": "'Segoe UI', 'Onest'",
    }[family]
