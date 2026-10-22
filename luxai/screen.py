"""LuxAI local screenshots and automatically provisioned Tesseract OCR.

The engine and Russian/English models live inside the private LuxAI data
folder; no manual system-wide Tesseract installation, PATH change, or cloud
upload is required. The first OCR request can install the engine if
install_windows.bat / Update.bat has not already prepared it.
"""
from __future__ import annotations

from pathlib import Path
from datetime import datetime

import mss
from PIL import Image
import pytesseract

from luxai.ocr_setup import (
    ensure_tesseract, find_tesseract, language_data_ready,
    OCRInstallError,
)


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
    """Look for the integrated OCR engine before any system installation.

    Does not download; code that wants OCR should use ensure_tesseract.
    """
    binary = find_tesseract(path)
    if binary is None:
        raise FileNotFoundError(
            "Встроенный Tesseract OCR отсутствует. "
            "Запустите Update.bat или дождитесь автоматической установки."
        )
    return str(binary)


def read_screen_text(image_path, tesseract_path=""):
    """Read screen text offline using bundled OCR and language data.

    First use may download the pinned executable and traineddata. Caller
    should invoke this in a worker thread to avoid freezing the GUI.
    """
    binary, models = ensure_tesseract(tesseract_path)
    pytesseract.pytesseract.tesseract_cmd = str(binary)
    # Restrict models to the bundled private tessdata directory. This works
    # even if a previously system-installed Tesseract has no Russian model.
    config = f'--tessdata-dir "{models}"'
    with Image.open(image_path) as picture:
        try:
            return pytesseract.image_to_string(
                picture, lang="rus+eng", config=config
            )
        except pytesseract.TesseractError as exc:
            if "rus.traineddata" not in str(exc):
                raise
            english = pytesseract.image_to_string(
                picture, lang="eng", config=config
            )
            return english + "\n[Русский пакет OCR не загрузился.]"
