"""Real Windows smoke test for the fully integrated Tesseract OCR.

Invoked on a Windows GitHub Actions runner, not during fast Linux unit tests.
Requires Pillow, pytesseract and mss installed in the runner.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Running as "python tests/smoke_windows_ocr.py" sets sys.path[0] to
# tests/, not the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw, ImageFont

from luxai.ocr_setup import (
    DATA_DIR, WINDOWS_EXECUTABLE,
    ensure_tesseract, language_data_ready, verify_tesseract,
)
from luxai.screen import read_screen_text


def main():
    if sys.platform != "win32":
        raise RuntimeError("Windows-only integration smoke test")

    binary, models = ensure_tesseract(allow_download=False)
    print("Tesseract EXE:", binary)
    print("Tesseract traineddata:", models)
    assert binary.is_file()
    assert models == DATA_DIR
    assert language_data_ready()
    ready, status = verify_tesseract(binary)
    print("OCR CLI verification:", status.encode("ascii", "backslashreplace").decode("ascii"))
    assert ready

    # Under the normal portable-copy path, the OCR binary and its native
    # DLL dependencies are next to LuxAI's local language models.
    assert WINDOWS_EXECUTABLE.exists(), (
        f"Vendor installed only into Program Files; bundled OCR copy missing: {binary}"
    )

    font_path = Path("C:/Windows/Fonts/arial.ttf")
    if not font_path.is_file():
        font_path = Path("C:/Windows/Fonts/segoeui.ttf")
    font = ImageFont.truetype(str(font_path), 56)
    image = Image.new("RGB", (780, 175), "white")
    ImageDraw.Draw(image).text((30, 32), "HELLO OCR 123", font=font, fill="black")
    path = Path("ocr_smoke_sample.png")
    image.save(path)

    output = read_screen_text(str(path))
    print("Real OCR sample:", repr(output))
    assert "OCR" in output.upper(), "OCR engine failed to recognize known sample"
    print("WINDOWS OCR SUCCESS")


if __name__ == "__main__":
    main()
