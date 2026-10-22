"""Local screenshots and OCR; screenshots are NEVER automatically uploaded."""
from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime

import mss
from PIL import Image
import pytesseract


def capture_screen():
    out = Path.home() / "Pictures" / "LuxAI"
    out.mkdir(parents=True, exist_ok=True)
    destination = out / (
        "screen_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".png"
    )
    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[1])
        Image.frombytes("RGB", shot.size, shot.rgb).save(destination)
    return str(destination)


def locate_tesseract(path="") -> str:
    """Find tesseract.exe in settings, PATH, or standard Windows directories."""
    if path:
        selected = Path(os.path.expandvars(str(path))).expanduser()
        if not selected.is_file():
            raise FileNotFoundError(
                f"Tesseract не найден по указанному пути: {selected}"
            )
        return str(selected)

    from shutil import which
    discovered = which("tesseract.exe") or which("tesseract")
    if discovered:
        return discovered
    for base in (
        os.getenv("PROGRAMFILES", ""),
        os.getenv("PROGRAMFILES(X86)", ""),
        str(Path.home() / "AppData" / "Local" / "Programs"),
    ):
        if base:
            candidate = Path(base) / "Tesseract-OCR" / "tesseract.exe"
            if candidate.is_file():
                return str(candidate)
    raise FileNotFoundError(
        "Tesseract OCR не установлен. "
        "Установите Tesseract-OCR (английский и русский языки) "
        "и выберите tesseract.exe в Настройки → Система."
    )


def read_screen_text(image_path, tesseract_path=""):
    pytesseract.pytesseract.tesseract_cmd = locate_tesseract(tesseract_path)
    picture = Image.open(image_path)
    try:
        return pytesseract.image_to_string(picture, lang="rus+eng")
    except pytesseract.TesseractError as exc:
        # English text still matters if the Windows installation lacks the
        # optional Russian traineddata package. Report this in the output.
        if "rus.traineddata" not in str(exc):
            raise
        text = pytesseract.image_to_string(picture, lang="eng")
        return text + "\n[Русский пакет OCR rus.traineddata не установлен.]"
