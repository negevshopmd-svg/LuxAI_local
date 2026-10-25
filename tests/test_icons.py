"""Exercise actual bundled SVG rendering and live-theme preservation."""
import unittest
from pathlib import Path
import shutil
import tempfile

from PySide6.QtCore import QSize, Qt, qInstallMessageHandler
from PySide6.QtGui import QIcon
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication, QComboBox, QLabel, QLineEdit, QPushButton,
    QSpinBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from luxai.icons import (
    ASSET_DIR, ICON_NAME_ROLE, icon, refresh_icons, set_button_icon,
    set_item_icon, set_label_icon,
)
from luxai.styles import build_styles


def pixels(value):
    image = value.toImage()
    return bytes(image.constBits())


def alpha_sum(value):
    image = value.toImage()
    return sum(image.pixelColor(x, y).alpha()
               for x in range(image.width()) for y in range(image.height()))


class IconRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_bundled_assets_render_without_fonts_or_downloads_at_both_scales(self):
        for path in ASSET_DIR.rglob("*.svg"):
            with self.subTest(icon=path.stem):
                self.assertTrue(QSvgRenderer(path.read_bytes()).isValid())
                for ratio in (1.0, 2.0):
                    value = QIcon(str(path)) if path.parent.name == "ui" else icon(path.stem)
                    pixmap = value.pixmap(QSize(20, 20), ratio)
                    self.assertEqual(pixmap.size(), QSize(round(20 * ratio), round(20 * ratio)))
                    self.assertEqual(pixmap.devicePixelRatioF(), ratio)
                    self.assertGreater(alpha_sum(pixmap), 0)

    def test_live_theme_refresh_preserves_selected_data_and_badge_geometry(self):
        root = QWidget()
        self.addCleanup(root.close)
        self.addCleanup(refresh_icons, root, "dark")
        layout = QVBoxLayout(root)
        button = QPushButton("Settings")
        set_button_icon(button, "settings")
        layout.addWidget(button)
        badge = QLabel()
        badge.setProperty("jarvisIconBoxSize", 35)
        set_label_icon(badge, "plus", size=20)
        layout.addWidget(badge)
        combo = QComboBox()
        combo.addItem("Device A", "endpoint-A")
        combo.addItem("Wireless headset", "endpoint-B")
        combo.setItemData(1, "mic", ICON_NAME_ROLE)
        combo.setCurrentIndex(1)
        layout.addWidget(combo)
        tree = QTreeWidget()
        tree.setColumnCount(1)
        item = QTreeWidgetItem(["Saved command"])
        item.setData(0, Qt.ItemDataRole.UserRole, "saved-command-id")
        set_item_icon(item, "play", widget=tree, column=0)
        tree.addTopLevelItem(item)
        tree.setCurrentItem(item)
        layout.addWidget(tree)
        search = QLineEdit("unchanged draft")
        action = search.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        action.setProperty("jarvisIcon", "search")
        layout.addWidget(search)

        refresh_icons(root, "dark")
        dark = [pixels(value.pixmap(20, 20)) for value in (button.icon(), combo.itemIcon(1), item.icon(0), action.icon())]
        refresh_icons(root, "light")
        light = [pixels(value.pixmap(20, 20)) for value in (button.icon(), combo.itemIcon(1), item.icon(0), action.icon())]
        for before, after in zip(dark, light):
            self.assertNotEqual(before, after)
        self.assertEqual(combo.currentData(), "endpoint-B")
        self.assertIs(tree.currentItem(), item)
        self.assertEqual(item.data(0, Qt.ItemDataRole.UserRole), "saved-command-id")
        self.assertEqual(search.text(), "unchanged draft")
        self.assertEqual(badge.size(), QSize(35, 35))
        self.assertEqual(badge.pixmap().deviceIndependentSize().toSize(), QSize(20, 20))

    def test_disabled_icons_remain_visible_with_reduced_emphasis(self):
        value = icon("mic", color="#ffffff")
        normal = value.pixmap(QSize(24, 24), QIcon.Mode.Normal)
        disabled = value.pixmap(QSize(24, 24), QIcon.Mode.Disabled)
        self.assertGreater(alpha_sum(disabled), 0)
        self.assertLess(alpha_sum(disabled), alpha_sum(normal))

    def test_native_control_chevrons_load_from_paths_with_spaces_and_unicode(self):
        root = QWidget()
        self.addCleanup(root.close)
        layout = QVBoxLayout(root)
        combo = QComboBox()
        combo.addItem("First", "device-1")
        combo.addItem("Second", "device-2")
        combo.setCurrentIndex(1)
        layout.addWidget(combo)
        spin = QSpinBox()
        spin.setValue(2)
        layout.addWidget(spin)
        tree = QTreeWidget()
        for expanded in (False, True):
            item = QTreeWidgetItem(["Group"])
            item.addChild(QTreeWidgetItem(["Command"]))
            tree.addTopLevelItem(item)
            item.setExpanded(expanded)
        layout.addWidget(tree)
        messages = []
        previous = qInstallMessageHandler(lambda kind, context, message: messages.append(message))
        try:
            with tempfile.TemporaryDirectory(prefix="Jarvis pictograme ") as directory:
                destination = Path(directory) / "săgeți noi"
                shutil.copytree(ASSET_DIR / "ui", destination)
                source_path = (ASSET_DIR / "ui").as_posix()
                for theme in ("dark", "light"):
                    css = build_styles(theme).replace(source_path, destination.as_posix())
                    root.setStyleSheet(css)
                    root.show()
                    self.app.processEvents()
                    self.assertFalse(root.grab().isNull())
                    self.assertEqual(combo.currentData(), "device-2")
                    self.assertTrue(tree.topLevelItem(1).isExpanded())
                spin.stepUp()
                self.assertEqual(spin.value(), 3)
        finally:
            qInstallMessageHandler(previous)
        failures = [message for message in messages
                    if "Cannot open file" in message or "Could not create pixmap" in message]
        self.assertEqual(failures, [])
