#!/usr/bin/env python3
"""Safe additive updater for Lux AI Local from the public GitHub main branch."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

OWNER = "negevshopmd-svg"
REPO = "LuxAI_local"
BRANCH = "main"
API = f"https://api.github.com/repos/{OWNER}/{REPO}"
ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / ".luxai_update_state.json"
BACKUP_ROOT = ROOT / "backups"
MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024

# These are local/user data. They are never copied over by an update.
PRESERVE_NAMES = {
    "models", "model", ".venv", "venv", ".git", "__pycache__",
    "backups", "downloads", "logs", "config.json", "settings.json",
    ".env", "updater_config.json", ".luxai_secrets", ".luxai_data", "online_agent.log", "voice_error.log",
}
SKIP_SUFFIXES = {".pyc", ".pyo"}


def request_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "LuxAI-Updater",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def download(url: str, target: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "LuxAI-Updater"})
    total = 0
    with urllib.request.urlopen(req, timeout=60) as response, target.open("wb") as out:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_DOWNLOAD_BYTES:
                raise RuntimeError("Arhiva depășește limita de siguranță de 500 MB.")
            out.write(chunk)


def is_preserved(rel: Path) -> bool:
    return any(part in PRESERVE_NAMES for part in rel.parts) or rel.suffix.lower() in SKIP_SUFFIXES


def safe_extract(zip_path: Path, destination: Path) -> None:
    base = destination.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f"Arhivă ZIP deteriorată: {bad}")
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            p = PurePosixPath(name)
            if p.is_absolute() or ".." in p.parts:
                raise RuntimeError(f"Cale nesigură în arhivă: {name}")
            target = (destination / Path(*p.parts)).resolve()
            if target != base and base not in target.parents:
                raise RuntimeError(f"Cale în afara directorului temporar: {name}")
        zf.extractall(destination)


def validate_staged_requirements(source: Path) -> None:
    """Reject malformed dependencies before touching installed project files.

    Use the existing virtual environment's pip parser, fully offline. This
    prevents a malformed requirements.txt from overwriting the working file
    and only then causing pip install to fail.
    """
    requirements = source / "requirements.txt"
    if not requirements.is_file():
        raise RuntimeError("Arhiva nu conține requirements.txt.")
    win_python = ROOT / ".venv" / "Scripts" / "python.exe"
    unix_python = ROOT / ".venv" / "bin" / "python"
    python = (
        win_python if win_python.is_file() else
        unix_python if unix_python.is_file() else
        Path(sys.executable)
    )
    checker = (
        "from pathlib import Path\n"
        "from pip._vendor.packaging.requirements import Requirement\n"
        "import sys\n"
        "rows = Path(sys.argv[1]).read_text(encoding='utf-8').splitlines()\n"
        "for n, row in enumerate(rows, 1):\n"
        "    row = row.split('#', 1)[0].strip()\n"
        "    if row:\n"
        "        try: Requirement(row)\n"
        "        except Exception as exc:\n"
        "            raise ValueError(f'Linia {n}: {row}: {exc}') from exc\n"
    )
    check = subprocess.run(
        [str(python), "-c", checker, str(requirements)],
        cwd=str(source), timeout=20, capture_output=True, text=True,
        errors="replace", check=False,
    )
    if check.returncode:
        details = (check.stderr or check.stdout).strip()
        raise RuntimeError(
            "requirements.txt din actualizare conține dependențe invalide. "
            "Niciun fișier nu a fost suprascris. "
            + details[-900:]
        )



def ensure_local_ai_backend() -> bool:
    """Update the optional GGUF backend even when the code is already up-to-date."""
    if sys.platform != "win32":
        return True
    python = ROOT / ".venv" / "Scripts" / "python.exe"
    helper = ROOT / "luxai" / "local_ai_setup.py"
    if not python.is_file() or not helper.is_file():
        print("GGUF: missing Python environment or installer; run install_windows.bat.")
        return False
    print("Verific motorul local GGUF (llama-cpp-python)...")
    try:
        result = subprocess.run(
            [str(python), "-m", "luxai.local_ai_setup"],
            cwd=str(ROOT), timeout=480, check=False,
        )
        if result.returncode == 0:
            print("Motorul GGUF este instalat si verificat.")
            return True
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"GGUF: instalarea nu a reusit: {type(exc).__name__}.")
    print("GGUF: nu este disponibil; verifica logs/local_ai_install.log.")
    print("Jarvis si comenzile fara GGUF continua sa functioneze.")
    return False


def main() -> int:
    print("=== Lux AI | Actualizare automată din GitHub ===")
    print(f"Repository: https://github.com/{OWNER}/{REPO}")
    try:
        commit = request_json(f"{API}/commits/{BRANCH}")
        latest_sha = commit.get("sha", "")
        if not latest_sha:
            raise RuntimeError("GitHub nu a returnat hash-ul commitului.")
        state = {}
        if STATE_FILE.exists():
            try:
                state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                state = {}
        current_sha = state.get("commit", "")
        print(f"Commit instalat: {current_sha[:12] if current_sha else 'necunoscut'}")
        print(f"Commit GitHub:   {latest_sha[:12]}")
        if current_sha == latest_sha:
            print("Lux AI este deja la zi. Verific si motorul GGUF optional...")
            ensure_local_ai_backend()
            return 0
    except Exception as e:
        print(f"Nu pot verifica GitHub: {e}")
        return 1

    # Update proceeds automatically without an interactive confirmation.
    print("Actualizarea pornește automat. Fișierele suprascrise vor avea backup.")

    with tempfile.TemporaryDirectory(prefix="luxai_update_") as temp:
        tempdir = Path(temp)
        archive = tempdir / "source.zip"
        extracted = tempdir / "extracted"
        extracted.mkdir()
        try:
            # GitHub's archive endpoint works without publishing a Release.
            download(f"{API}/zipball/{latest_sha}", archive)
            safe_extract(archive, extracted)

            roots = [p for p in extracted.iterdir() if p.is_dir()]
            if len(roots) != 1:
                raise RuntimeError("Structura arhivei GitHub nu este cea așteptată.")
            source = roots[0]
            if not (source / "main.py").is_file():
                raise RuntimeError("Arhiva nu conține main.py; nu modific nimic.")
            # Validate requirements from the downloaded copy, BEFORE backup
            # and BEFORE replacing anything in the user's installation.
            validate_staged_requirements(source)

            files = []
            for src in source.rglob("*"):
                rel = src.relative_to(source)
                if is_preserved(rel):
                    continue
                if src.is_file():
                    files.append((src, rel))
            if not files:
                raise RuntimeError("Nu am găsit fișiere de proiect pentru actualizare.")

            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = BACKUP_ROOT / f"{stamp}-{(current_sha[:12] if current_sha else 'initial')}"
            # Create a backup only for files that will actually be overwritten.
            for src, rel in files:
                dest = ROOT / rel
                if dest.is_file():
                    backup_file = backup / rel
                    backup_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dest, backup_file)

            print(f"Aplic {len(files)} fișiere...")
            for src, rel in files:
                dest = ROOT / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)

            # Update the existing virtual environment after refreshing
            # requirements. Without this, adding new Windows action libraries
            # such as pycaw leaves controls visible but nonfunctional.
            win_python = ROOT / ".venv" / "Scripts" / "python.exe"
            unix_python = ROOT / ".venv" / "bin" / "python"
            venv_python = win_python if win_python.is_file() else unix_python
            requirements = ROOT / "requirements.txt"
            if venv_python.is_file() and requirements.is_file():
                print("Verific și instalez dependențele noi în .venv...")
                process = subprocess.run(
                    [
                        str(venv_python), "-m", "pip", "install",
                        "--disable-pip-version-check",
                        "-r", str(requirements),
                    ],
                    cwd=str(ROOT), timeout=300, check=False,
                )
                if process.returncode != 0:
                    raise RuntimeError(
                        "Fișierele au fost actualizate, dar pip nu a instalat "
                        "toate dependențele. Rulează install_windows.bat "
                        "sau încearcă din nou Update.bat."
                    )
            else:
                print(
                    "AVERTISMENT: .venv nu există; rulează "
                    "install_windows.bat înainte să pornești aplicația."
                )

            # Refresh the optional llama.cpp backend automatically as well.
            # Failure does not invalidate the core application update.
            ensure_local_ai_backend()

            # Prepare Tesseract OCR on the user's PC as part of the
            # normal updater. The verified Windows installer and both
            # language models live in .luxai_data/ocr, a preserved local
            # folder. Failure does not corrupt the already-updated app.
            ocr_ready = True
            if sys.platform == "win32" and venv_python.is_file():
                print("Pregatesc OCR integrat: Tesseract + rusa/engleza...")
                try:
                    ocr_result = subprocess.run(
                        [str(venv_python), "-m", "luxai.ocr_setup"],
                        cwd=str(ROOT), check=False, timeout=330,
                    )
                    ocr_ready = ocr_result.returncode == 0
                except (subprocess.TimeoutExpired, OSError) as exc:
                    ocr_ready = False
                    print(f"OCR: eroare la instalare: {exc}")
                if not ocr_ready:
                    print(
                        "AVERTISMENT: Codul Jarvis este actualizat, dar "
                        "Tesseract nu s-a instalat. Verifica internetul "
                        "sau permisiunile Windows. Instalarea OCR se "
                        "reincearca si automat din aplicatie."
                    )

            STATE_FILE.write_text(
                json.dumps({"commit": latest_sha, "branch": BRANCH}, indent=2),
                encoding="utf-8",
            )
            print("Actualizare instalată cu succes.")
            if backup.exists():
                print(f"Backup pentru fișierele suprascrise: {backup}")
            else:
                print("Nu au existat fișiere existente care să necesite backup.")
            print("Nu am șters niciun fișier local.")
            print("Folderul models și config.json au fost păstrate.")
            print("Pornește Lux AI cu run_windows.bat.")
            return 0
        except Exception as e:
            print(f"Actualizarea a eșuat: {e}")
            print("Nu au fost șterse fișiere. Verifică folderul backups dacă s-au copiat deja fișiere.")
            return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nActualizare anulată.")
        raise SystemExit(130)
