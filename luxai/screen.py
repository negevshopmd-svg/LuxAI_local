"""LuxAI local screenshots and automatically provisioned Tesseract OCR.

The bundled engine and Russian/English models live inside .luxai_data/ocr.
The app runs Tesseract directly with a safe argv list: unlike the Python
pytesseract config-string wrapper, this is reliable on Windows even when
LuxAI is installed in a path containing spaces. Images remain local.
"""
from __future__ import annotations

from pathlib import Path
from datetime import datetime
import subprocess

import mss
from PIL import Image

from luxai.ocr_setup import ensure_tesseract, find_tesseract


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
    """Find the integrated OCR executable; do not download during lookup."""
    binary = find_tesseract(path)
    if binary is None:
        raise FileNotFoundError(
            "Встроенный Tesseract OCR отсутствует. "
            "Запустите Update.bat или дождитесь автоматической установки."
        )
    return str(binary)


def _run_ocr(binary: Path, data: Path, image: Path, languages: str) -> str:
    # No shell, no global process environment mutation and no manual
    # quoting: subprocess passes paths with spaces correctly on Windows.
    command = [
        str(binary), str(image), "stdout",
        "--tessdata-dir", str(data),
        "-l", languages,
    ]
    result = subprocess.run(
        command,
        check=False, timeout=45,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8", errors="replace",
        shell=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip()[:500]
        raise RuntimeError(
            f"Tesseract OCR завершился с кодом {result.returncode}: {detail}"
        )
    return result.stdout


def read_screen_text(image_path, tesseract_path=""):
    """Run local rus+eng Tesseract on a screenshot.

    First use may download and install the pinned OCR engine if the
    application updater has not prepared it. Called from a worker thread.
    """
    image = Path(image_path)
    if not image.is_file():
        raise FileNotFoundError(f"Изображение экрана не найдено: {image}")

    binary, models = ensure_tesseract(tesseract_path)
    try:
        return _run_ocr(binary, models, image, "rus+eng")
    except RuntimeError as exc:
        if "rus.traineddata" not in str(exc):
            raise
        english = _run_ocr(binary, models, image, "eng")
        return english + "\n[Не удалось запустить русскую OCR-модель.]"
