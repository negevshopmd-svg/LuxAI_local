"""Register bundled UI fonts locally and normalize saved font preferences."""
from pathlib import Path

from PySide6.QtGui import QFontDatabase, QGuiApplication


ROOT = Path(__file__).resolve().parents[1]
PROJECT_FONT = "Fuzzy Bubbles"


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
                 ("FuzzyBubbles-Regular.ttf", "FuzzyBubbles-Bold.ttf"))
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


def font_stack(value):
    family = normalize_font_family(value)
    return {
        PROJECT_FONT: "'Fuzzy Bubbles', 'Onest', 'Segoe UI'",
        "Onest": "'Onest', 'Segoe UI'",
        "system": "'Segoe UI', 'Onest'",
    }[family]
