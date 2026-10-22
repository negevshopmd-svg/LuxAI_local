"""Install and locate Tesseract OCR bundled with LuxAI on Windows.

Installs only in .luxai_data/ocr/Tesseract-OCR (a dedicated local directory),
never into the application root or Program Files. The Windows EXE comes from
UB-Mannheim's versioned GitHub release, with SHA-256 pinned to Microsoft's
winget-pkgs manifest for that specific release. English/Russian models come
only from the official Tesseract tessdata_fast repository over HTTPS.

The user's saved model/configuration files remain untouched. No admin shell,
PowerShell, PATH or system environment modifications are needed.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OCR_ROOT = ROOT / ".luxai_data" / "ocr"
INSTALL_DIR = OCR_ROOT / "Tesseract-OCR"
DATA_DIR = OCR_ROOT / "tessdata"
WINDOWS_EXECUTABLE = INSTALL_DIR / "tesseract.exe"

RELEASE = "5.4.0.20240606"
INSTALLER_NAME = f"tesseract-ocr-w64-setup-{RELEASE}.exe"
INSTALLER_URL = (
    "https://github.com/UB-Mannheim/tesseract/releases/download/"
    f"v{RELEASE}/{INSTALLER_NAME}"
)
# microsoft/winget-pkgs, manifests/u/UB-Mannheim/TesseractOCR/
# 5.4.0.20240606/UB-Mannheim.TesseractOCR.installer.yaml
INSTALLER_SHA256 = "c885fff6998e0608ba4bb8ab51436e1c6775c2bafc2559a19b423e18678b60c9"

MODELS = {
    "rus": "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/rus.traineddata",
    "eng": "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/eng.traineddata",
}
_DOWNLOAD_CAP_BYTES = 75 * 1024 * 1024
_LANG_CAP_BYTES = 20 * 1024 * 1024
_LOCK = threading.Lock()


class OCRInstallError(RuntimeError):
    """OCR download/install/verification failed; app remains usable."""


def _valid_binary(path: Path) -> bool:
    return path.is_file() and path.stat().st_size >= 100_000


def find_tesseract(configured_path: str = "") -> Path | None:
    """Prefer bundled OCR, then a valid user-provided or system installation.

    An old, invalid path from config.json should NOT override a now-bundled
    working executable, and no internet is used during lookup.
    """
    candidates: list[Path] = [WINDOWS_EXECUTABLE]
    if configured_path:
        candidates.append(
            Path(os.path.expandvars(configured_path)).expanduser()
        )
    existing = shutil.which("tesseract.exe") or shutil.which("tesseract")
    if existing:
        candidates.append(Path(existing))
    if sys.platform == "win32":
        for directory in (
            os.getenv("PROGRAMFILES"),
            os.getenv("PROGRAMFILES(X86)"),
            str(Path.home() / "AppData" / "Local" / "Programs"),
        ):
            if directory:
                candidates.append(
                    Path(directory) / "Tesseract-OCR" / "tesseract.exe"
                )
    for path in candidates:
        try:
            if _valid_binary(path):
                return path
        except (OSError, ValueError):
            continue
    return None


def language_data_ready() -> bool:
    return all(
        (DATA_DIR / (lang + ".traineddata")).is_file()
        and (DATA_DIR / (lang + ".traineddata")).stat().st_size >= 100_000
        for lang in MODELS
    )


def _download_bounded(url: str, destination: Path, *, limit: int) -> str:
    """Download over HTTPS to an isolated temporary file with size limits."""
    if not url.startswith((
        "https://github.com/UB-Mannheim/tesseract/releases/download/",
        "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/",
    )):
        raise OCRInstallError("Источник OCR не разрешён.")
    request = urllib.request.Request(
        url, headers={"User-Agent": "LuxAI-OCR-Setup/1.0"},
    )
    digest = hashlib.sha256()
    bytes_read = 0
    with urllib.request.urlopen(request, timeout=45) as response, destination.open("wb") as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            bytes_read += len(chunk)
            if bytes_read > limit:
                raise OCRInstallError("Загружаемый OCR-файл слишком большой.")
            digest.update(chunk)
            output.write(chunk)
    if bytes_read < 100_000:
        raise OCRInstallError("Загрузка OCR неполная или пустая.")
    return digest.hexdigest()


def _install_binary() -> Path:
    """Install a pinned 64-bit Windows build into an isolated private folder."""
    if sys.platform != "win32" or struct.calcsize("P") != 8:
        raise OCRInstallError("Встроенный OCR требует 64-битную Windows.")
    if _valid_binary(WINDOWS_EXECUTABLE):
        return WINDOWS_EXECUTABLE

    OCR_ROOT.mkdir(parents=True, exist_ok=True)
    # Important: the install directory must be a DEDICATED empty subfolder.
    # The vendor's uninstaller removes that whole directory; never install
    # to LuxAI_Local root or a directory containing user files.
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ocr_download_", dir=str(OCR_ROOT)) as directory:
        installer = Path(directory) / INSTALLER_NAME
        obtained = _download_bounded(
            INSTALLER_URL, installer, limit=_DOWNLOAD_CAP_BYTES,
        )
        if obtained.lower() != INSTALLER_SHA256:
            raise OCRInstallError(
                "Подпись SHA-256 установщика Tesseract не совпала. "
                "Файл не будет запускаться."
            )
        with installer.open("rb") as check:
            if check.read(2) != b"MZ":
                raise OCRInstallError("Загруженный файл не является Windows EXE.")
        try:
            result = subprocess.run(
                [
                    str(installer),
                    "/S",
                    "/D=" + str(INSTALL_DIR),
                ],
                check=False,
                timeout=180,
                cwd=str(OCR_ROOT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OCRInstallError(
                f"Не удалось установить встроенный Tesseract: {exc}"
            ) from exc
        if result.returncode != 0:
            raise OCRInstallError(
                f"Установщик Tesseract завершился с кодом {result.returncode}. "
                "Возможно, Windows запросил права администратора."
            )
    if not _valid_binary(WINDOWS_EXECUTABLE):
        raise OCRInstallError(
            "Установщик завершился, но встроенный tesseract.exe "
            "не появился. Проверьте защиту Windows или разрешения."
        )
    return WINDOWS_EXECUTABLE


def _install_languages() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for language, url in MODELS.items():
        path = DATA_DIR / f"{language}.traineddata"
        if path.is_file() and path.stat().st_size >= 100_000:
            continue
        # Download to a temp file and atomically move only after it
        # succeeds; failed requests cannot corrupt an existing model.
        with tempfile.NamedTemporaryFile(
            prefix=language + "_", suffix=".partial",
            dir=str(DATA_DIR), delete=False,
        ) as file:
            temporary = Path(file.name)
        try:
            _download_bounded(url, temporary, limit=_LANG_CAP_BYTES)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def verify_tesseract(binary: Path) -> tuple[bool, str]:
    if not binary.is_file():
        return False, "Не найден tesseract.exe."
    if not language_data_ready():
        return False, "Отсутствуют языковые модели rus/eng."
    try:
        # Never invoke a shell or trust unvalidated model paths.
        run = subprocess.run(
            [
                str(binary), "--list-langs",
                "--tessdata-dir", str(DATA_DIR),
            ],
            timeout=20, capture_output=True, text=True,
            errors="replace", check=False,
        )
        langs = set(run.stdout.casefold().split()) | set(run.stderr.casefold().split())
        if run.returncode or not {"rus", "eng"}.issubset(langs):
            return False, (
                "Tesseract не видит языки rus/eng: "
                + ((run.stderr or run.stdout).strip()[:250])
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"Tesseract не запускается: {exc}"
    return True, f"Tesseract готов: {binary} (rus+eng)"


def ensure_tesseract(configured_path: str = "", *, allow_download=True) -> tuple[Path, Path]:
    """Return (executable, tessdata dir); install on first call if missing.

    Called by Update.bat/install_windows.bat as well as the OCR worker
    on first use. Installation is process-locked and repeat-safe.
    """
    with _LOCK:
        binary = find_tesseract(configured_path)
        if binary and language_data_ready():
            ok, _ = verify_tesseract(binary)
            if ok:
                return binary, DATA_DIR
        if not allow_download:
            raise OCRInstallError(
                "Tesseract OCR ещё не установлен или языки rus/eng отсутствуют."
            )
        if sys.platform != "win32":
            raise OCRInstallError(
                "Автоустановка Tesseract поддерживается только на Windows."
            )
        if binary is None:
            binary = _install_binary()
        try:
            _install_languages()
        except (OSError, urllib.error.URLError) as exc:
            raise OCRInstallError(
                f"Не удалось скачать языки rus/eng для OCR: {exc}"
            ) from exc
        valid, reason = verify_tesseract(binary)
        if not valid:
            raise OCRInstallError(reason)
        return binary, DATA_DIR


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Install LuxAI bundled Tesseract OCR")
    parser.add_argument("--check", action="store_true", help="Check without network")
    opts = parser.parse_args()
    try:
        binary, models = ensure_tesseract(allow_download=not opts.check)
    except (OCRInstallError, OSError, urllib.error.URLError) as exc:
        print("OCR: instalarea nu a reusit: " + str(exc))
        return 1
    print(f"OCR: pregatit automat ({binary}); limbi: rus + eng ({models})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
