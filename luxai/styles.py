"""Centralized Qt stylesheet for Jarvis's Luxify-inspired interface."""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QUrl


DARK = {
    "bg": "#0b0d11",
    "side": "#11161e",
    "surface": "#1b1d20",
    "control": "#24272b",
    "field": "#24272b",
    "hover": "#282e36",
    "border": "#30343a",
    "text": "#f0f2f6",
    "muted": "#a6acb8",
    "navtext": "#c6ccd7",
    "scroll": "#272c34",
    "selection": "#242a34",
    "black": "#0b0d11",
}

LIGHT = {
    "bg": "#f5f7fb",
    "side": "#e8edf6",
    "surface": "#ffffff",
    "control": "#edf1f7",
    "field": "#f7f9fc",
    "hover": "#dce7f7",
    "border": "#cdd6e4",
    "text": "#1c2738",
    "muted": "#667184",
    "navtext": "#334155",
    "scroll": "#cbd5e1",
    "selection": "#dce9ff",
    "black": "#f5f7fb",
}


def build_styles(theme="dark", accent="#3978f6"):
    p = LIGHT if theme == "light" else DARK
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(accent)):
        accent = "#3978f6"

    css = """
QWidget {
    background: $bg;
    color: $text;
    font-family: 'Segoe UI', 'Arial';
    font-size: 13px;
}
QMainWindow, QWidget#MainContent {
    background: $bg;
}
QDialog {
    background: $bg;
}
QListWidget, QTreeWidget {
    background: $surface;
    color: $text;
    border: 1px solid $border;
    border-radius: 10px;
    outline: 0;
}
QListWidget::item, QTreeWidget::item {
    padding: 7px 8px;
    border: none;
}
QListWidget::item:hover, QTreeWidget::item:hover {
    background: $hover;
}
QListWidget::item:selected, QTreeWidget::item:selected {
    background: $selection;
    color: $text;
}
QLabel {
    background: transparent;
}
QFrame#Sidebar {
    background: $side;
    border-right: 1px solid $border;
}
QLabel#SidebarBrand {
    color: $text;
}
QLabel#SidebarVersion {
    color: $muted;
    font-size: 10px;
    font-weight: 400;
    padding: 0;
}
QPushButton#Nav {
    background: transparent;
    border: none;
    border-radius: 10px;
    text-align: left;
    padding: 10px 9px;
    color: $navtext;
    font-weight: 500;
}
QPushButton#Nav:hover {
    background: $hover;
    color: $text;
}
QPushButton#Nav[active="true"] {
    background: $selection;
    border-left: 3px solid $accent;
    color: $text;
    padding-left: 6px;
    font-weight: 600;
}
QPushButton#Nav[collapsed="true"], QPushButton#Nav[active="true"][collapsed="true"] {
    text-align: center;
    padding: 10px 0;
    border-left: none;
}
QFrame#HomeCard {
    background: $surface;
    border: 1px solid $border;
    border-radius: 17px;
}
QLabel#HomeCardTitle {
    font-size: 17px;
    font-weight: 700;
    color: $text;
}
QLabel#HomeRowLabel {
    color: $muted;
    font-size: 13px;
}
QLabel#HomeVolumeValue {
    font-size: 13px;
    color: $text;
}
QWidget#HomePage, QWidget#HomeLeft, QWidget#HeroOrb {
    background: transparent;
}
QTextEdit#HomeHistory {
    background: transparent;
    border: none;
    padding: 0px;
    color: $text;
    font-size: 13px;
}
QFrame#Card, QFrame#SettingsCard, QFrame#SettingsSidebar {
    background: $surface;
    border: 1px solid $border;
    border-radius: 15px;
}
QLabel#PageTitle {
    font-size: 23px;
    font-weight: 700;
    color: $text;
}
QLabel#Muted {
    color: $muted;
}
QLabel#PickerSubtitle, QLabel#ActionHint, QLabel#PickerGroup, QLabel#TileDescription {
    color: $muted;
    background: transparent;
}
QLabel#TileIcon {
    background: $selection;
    border-radius: 10px;
}
QFrame#ActionTile {
    background: $surface;
    border: 1px solid $border;
    border-radius: 12px;
}
QFrame#ActionTile:hover {
    background: $hover;
    border-color: $accent;
}
QFrame#ActionTile[chosen="true"] {
    background: $selection;
    border-color: $accent;
}
QListWidget#ActionCategories {
    background: transparent;
    border: none;
}
QListWidget#ActionCategories::item:selected {
    background: $selection;
    color: $text;
}
QPushButton#PickerClose:hover {
    background: $hover;
    color: $text;
}
QPushButton {
    background: $control;
    border: 1px solid $border;
    border-radius: 9px;
    color: $text;
    padding: 8px 12px;
}
QPushButton:hover {
    background: $hover;
    border-color: $accent;
}
QPushButton#Primary {
    background: $accent;
    color: white;
    border: none;
    font-weight: 600;
}
QPushButton#Primary:hover {
    background: $accent;
}
QPushButton#SettingsNav {
    border: none;
    border-radius: 9px;
    padding: 9px 11px;
    text-align: left;
    background: transparent;
    color: $navtext;
}
QPushButton#SettingsNav:hover {
    background: $hover;
}
QPushButton#SettingsNav[selected="true"] {
    background: $selection;
    border-left: 3px solid $accent;
    color: $text;
}
QLineEdit, QTextEdit, QComboBox, QSpinBox {
    background: $field;
    color: $text;
    border: 1px solid $border;
    border-radius: 9px;
    padding: 8px;
    selection-background-color: $accent;
}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
    border-color: $accent;
}
QComboBox {
    padding-right: 29px;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 27px;
    border: none;
    background: transparent;
}
QComboBox::down-arrow {
    image: url("$chevron_down");
    width: 14px;
    height: 14px;
}
QSpinBox, QDoubleSpinBox {
    padding-right: 25px;
}
QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 23px;
    border: none;
    background: transparent;
}
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 23px;
    border: none;
    background: transparent;
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: url("$chevron_up");
    width: 12px;
    height: 12px;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: url("$chevron_down");
    width: 12px;
    height: 12px;
}
QTreeView::branch:closed:has-children {
    image: url("$chevron_right");
}
QTreeView::branch:open:has-children {
    image: url("$chevron_down");
}
QCheckBox {
    color: $text;
    background: transparent;
    spacing: 10px;
}
QCheckBox::indicator {
    width: 17px;
    height: 17px;
}
QCheckBox::indicator:unchecked {
    background: $control;
    border: 1px solid $border;
    border-radius: 8px;
}
QCheckBox::indicator:checked {
    background: $accent;
    border: 1px solid $accent;
    border-radius: 8px;
}
QSlider::groove:horizontal {
    height: 5px;
    background: $scroll;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: $accent;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 16px;
    margin: -6px 0;
    background: #ffffff;
    border-radius: 8px;
}
QScrollBar:vertical {
    background: $bg;
    width: 9px;
}
QScrollBar::handle:vertical {
    background: $scroll;
    border-radius: 4px;
    min-height: 22px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QPushButton#HeaderMic {
    border: 1px solid $border;
    background: $surface;
    border-radius: 11px;
    padding: 2px;
    font-size: 20px;
    color: $text;
}
QPushButton#HeaderMic:checked {
    border-color: $accent;
    color: $accent;
}
"""
    for key, value in p.items():
        css = css.replace("$" + key, value)
    css = css.replace("$accent", accent)
    # Qt URLs preserve spaces and Unicode paths on Windows installations.
    arrow_theme = "light" if theme == "light" else "dark"
    icon_root = Path(__file__).resolve().parent / "assets" / "icons" / "ui"
    for direction in ("down", "up", "right"):
        # QSS image loaders expect a quoted local filename. Passing file://
        # makes Qt SVG treat it as a relative "file:/..." path on Linux.
        url = QUrl.fromLocalFile(str(icon_root / f"chevron-{direction}-{arrow_theme}.svg")).toLocalFile().replace("\\", "/")
        css = css.replace("$chevron_" + direction, url)
    return css
