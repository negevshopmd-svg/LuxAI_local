#!/usr/bin/env python3
"""Safe additive updater for Lux AI Local from the public GitHub main branch."""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

OWNER = "negevshopmd-svg"
REPO = "LuxAI_local"
BRANCH = "main"
API = f"https://api.github.com/repos/{OWNER}/{REPO}"
ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / ".luxai_update_state.json"
BACKUP_ROOT = ROOT / "backups"
MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024
MAX_EXTRACTED_BYTES = 1024 * 1024 * 1024
MAX_ARCHIVE_FILES = 20000

# These are local/user data. They are never copied over by an update.
PRESERVE_NAMES = {
    "models", "model", ".venv", "venv", ".git", "__pycache__",
    "backups", "downloads", "logs", "config.json", "settings.json",
    ".env", "config.local.json", "updater_config.json", ".luxai_secrets", ".luxai_data",
    ".luxai_update_state.json", "online_agent.log", "voice_error.log",
}
SKIP_SUFFIXES = {".pyc", ".pyo", ".onnx", ".gguf"}


def report(message: str) -> None:
    """Keep console/redirect encoding failures outside update transactions.

    Windows redirected stdout can still use a strict legacy code page even
    after chcp 65001. Preserve Unicode when the stream supports it; otherwise
    escape only unsupported characters. A closed pipe must not hide the real
    update error or prevent restoration of the previous files.
    """
    text = message + "\n"
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        try:
            stream.write(text)
            stream.flush()
            return
        except UnicodeEncodeError:
            try:
                encoding = getattr(stream, "encoding", None) or "ascii"
                escaped = text.encode(encoding, errors="backslashreplace").decode(encoding)
                stream.write(escaped)
                stream.flush()
                return
            except Exception:
                # Reporting is best-effort; output errors must never replace
                # the exception that triggered rollback or mark success false.
                continue
        except Exception:
            continue


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
    # Windows paths are case insensitive. A differently-cased ZIP entry must
    # never overwrite the user's settings, environment or model files.
    return (
        any(part.casefold() in PRESERVE_NAMES or part.casefold().startswith((".venv.old-", ".env."))
            for part in rel.parts)
        or rel.suffix.lower() in SKIP_SUFFIXES
        or rel.name.casefold().endswith(".onnx.json")
    )


def safe_extract(zip_path: Path, destination: Path) -> None:
    base = destination.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        entries = zf.infolist()
        # Check declared sizes BEFORE testzip decompresses the archive.
        if len(entries) > MAX_ARCHIVE_FILES or sum(info.file_size for info in entries) > MAX_EXTRACTED_BYTES:
            raise RuntimeError("Arhiva depășește limita de fișiere sau de date extrase.")
        seen = set()
        for info in entries:
            name = info.filename.replace("\\", "/")
            p = PurePosixPath(name)
            key = str(p).casefold()
            reserved = {"con", "prn", "aux", "nul"} | {f"{prefix}{n}" for prefix in ("com", "lpt") for n in range(1, 10)}
            if (
                p.is_absolute() or ".." in p.parts or not p.parts
                or any(":" in part or part.endswith((".", " ")) or part.split(".")[0].casefold() in reserved for part in p.parts)
                or stat.S_ISLNK(info.external_attr >> 16)
                or key in seen
            ):
                raise RuntimeError(f"Cale nesigură în arhivă: {name}")
            seen.add(key)
            target = (destination / Path(*p.parts)).resolve()
            if target != base and base not in target.parents:
                raise RuntimeError(f"Cale în afara directorului temporar: {name}")
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f"Arhivă ZIP deteriorată: {bad}")
        zf.extractall(destination)


def validate_staged_source(source: Path) -> None:
    """Catch incomplete archives and Python syntax errors before replacing code."""
    for name in ("main.py", "launch_windows.py", "requirements.txt", "luxai/voice.py", "run_windows.bat"):
        if not (source / name).is_file():
            raise RuntimeError(f"Arhiva este incompletă: lipsește {name}.")
    for path in source.rglob("*.py"):
        if not is_preserved(path.relative_to(source)):
            compile(path.read_bytes(), str(path), "exec")


def _destination(rel: Path) -> Path:
    """Never follow a local junction/symlink when overwriting application code."""
    root = ROOT.resolve()
    dest = ROOT / rel
    resolved = dest.resolve()
    if resolved == root or root not in resolved.parents:
        raise RuntimeError(f"Destinație în afara proiectului: {rel}")
    for path in (dest, *dest.parents):
        if path == ROOT:
            break
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise RuntimeError(f"Nu suprascriu o legătură locală: {rel}")
    if dest.exists() and not dest.is_file():
        raise RuntimeError(f"Destinația nu este un fișier: {rel}")
    return dest


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".luxai-update-", dir=destination.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def file_transaction(files: list[tuple[Path, Path]], backup: Path):
    """Restore replaced code and remove new code if any update step fails.

    Package installation is a separate operation: pip cannot roll back all
    package changes. On dependency failure we restore the previous code and
    explicitly direct the user to the installer to repair the environment.
    """
    destinations = [(src, rel, _destination(rel)) for src, rel in files]
    originals = set()
    for _, rel, dest in destinations:
        if dest.is_file():
            saved = backup / rel
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dest, saved)
            originals.add(rel)
    backup.mkdir(parents=True, exist_ok=True)
    (backup.parent / (backup.name + ".manifest.json")).write_text(json.dumps({
        "overwritten": [str(rel) for rel in sorted(originals)],
        "new": [str(rel) for _, rel, _ in destinations if rel not in originals],
    }, indent=2), encoding="utf-8")
    applied = []
    try:
        for src, rel, dest in destinations:
            _atomic_copy(src, dest)
            applied.append((rel, dest))
        yield
    except BaseException as failure:
        errors = []
        for rel, dest in reversed(applied):
            try:
                if rel in originals:
                    _atomic_copy(backup / rel, dest)
                else:
                    dest.unlink(missing_ok=True)
            except OSError as exc:
                errors.append(f"{rel}: {type(exc).__name__}")
        if errors:
            report(f"Restaurarea automată nu este completă. Backup: {backup}")
            report("; ".join(errors))
            raise RuntimeError(f"Restaurare incompletă; fișierele originale sunt în {backup}") from failure
        else:
            report("Fișierele programului au fost restaurate la versiunea anterioară.")
        raise


def write_update_state(latest_sha: str) -> None:
    fd, name = tempfile.mkstemp(prefix=".luxai-state-", dir=ROOT)
    os.close(fd)
    temporary = Path(name)
    try:
        temporary.write_text(json.dumps({"commit": latest_sha, "branch": BRANCH}, indent=2), encoding="utf-8")
        os.replace(temporary, STATE_FILE)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def updater_lock():
    """An OS lock is released even after a crash; stale PID files cannot block updates."""
    lock_path = ROOT / ".luxai_data" / "updater.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        if sys.platform == "win32":
            import msvcrt
            if not lock_path.stat().st_size:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("O altă actualizare LuxAI rulează deja. Așteaptă să termine.") from exc
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError("O altă actualizare LuxAI rulează deja. Așteaptă să termine.") from exc
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


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



def upgrade_dependencies() -> bool:
    """Upgrade direct requirements in the existing venv to the latest compatible releases.

    Do not touch globally installed Python packages. If a network update fails,
    the operator gets an actionable message rather than a false success.
    """
    windows_python = ROOT / ".venv" / "Scripts" / "python.exe"
    unix_python = ROOT / ".venv" / "bin" / "python"
    python = windows_python if windows_python.is_file() else unix_python
    requirements = ROOT / "requirements.txt"
    if not python.is_file() or not requirements.is_file():
        report("Dependențe: mediul .venv lipsește. Rulează install_windows.bat.")
        return False
    report("Verific ultimele versiuni compatibile ale bibliotecilor LuxAI...")
    commands = [
        [str(python), "-m", "pip", "install", "--disable-pip-version-check",
         "--upgrade", "pip"],
        [str(python), "-m", "pip", "install", "--disable-pip-version-check",
         "--upgrade", "--upgrade-strategy", "only-if-needed", "--prefer-binary",
         "--retries", "2", "--timeout", "30", "-r", str(requirements)],
        [str(python), "-m", "pip", "check"],
        [str(python), "-c", "import main; from luxai.voice import VoiceListener; print('LuxAI imports OK')"],
    ]
    for command in commands:
        try:
            result = subprocess.run(command, cwd=str(ROOT), timeout=480, check=False)
            if result.returncode != 0:
                report("Dependențe: actualizarea/verificarea a eșuat. Rulează install_windows.bat.")
                return False
        except (OSError, subprocess.TimeoutExpired) as exc:
            report(f"Dependențe: verificarea a eșuat ({type(exc).__name__}).")
            return False
    report("Bibliotecile LuxAI sunt actualizate la ultimele versiuni compatibile.")
    return True


def ensure_local_ai_backend() -> bool:
    """Update the optional GGUF backend even when the code is already up-to-date."""
    if sys.platform != "win32":
        return True
    python = ROOT / ".venv" / "Scripts" / "python.exe"
    helper = ROOT / "luxai" / "local_ai_setup.py"
    if not python.is_file() or not helper.is_file():
        report("GGUF: missing Python environment or installer; run install_windows.bat.")
        return False
    report("Verific motorul local GGUF (llama-cpp-python)...")
    try:
        result = subprocess.run(
            [str(python), "-m", "luxai.local_ai_setup"],
            cwd=str(ROOT), timeout=480, check=False,
        )
        if result.returncode == 0:
            report("Motorul GGUF este instalat si verificat.")
            return True
    except (OSError, subprocess.TimeoutExpired) as exc:
        report(f"GGUF: instalarea nu a reusit: {type(exc).__name__}.")
    report("GGUF: nu este disponibil; verifica logs/local_ai_install.log.")
    report("Jarvis si comenzile fara GGUF continua sa functioneze.")
    return False


def perform_update() -> int:
    report("=== Lux AI | Actualizare automată din GitHub ===")
    report(f"Repository: https://github.com/{OWNER}/{REPO}")
    try:
        commit = request_json(f"{API}/commits/{BRANCH}")
        latest_sha = commit.get("sha", "")
        if not isinstance(latest_sha, str) or len(latest_sha) != 40 or any(c not in "0123456789abcdef" for c in latest_sha):
            raise RuntimeError("GitHub nu a returnat un hash valid al commitului.")
        state = {}
        if STATE_FILE.exists():
            try:
                state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                state = {}
        current_sha = state.get("commit", "") if isinstance(state, dict) else ""
        if not isinstance(current_sha, str) or len(current_sha) != 40 or any(c not in "0123456789abcdef" for c in current_sha):
            current_sha = ""
        report(f"Commit instalat: {current_sha[:12] if current_sha else 'necunoscut'}")
        report(f"Commit GitHub:   {latest_sha[:12]}")
        if current_sha == latest_sha:
            report("Lux AI este deja la zi. Verific si bibliotecile instalate...")
            if not upgrade_dependencies():
                return 1
            ensure_local_ai_backend()
            return 0
    except Exception as e:
        report(f"Nu pot verifica GitHub: {e}")
        return 1

    # Update proceeds automatically without an interactive confirmation.
    report("Actualizarea pornește automat. Fișierele suprascrise vor avea backup.")

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
            validate_staged_source(source)
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

            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            backup = BACKUP_ROOT / f"{stamp}-{(current_sha[:12] if current_sha else 'initial')}"
            report(f"Aplic {len(files)} fișiere...")
            with file_transaction(files, backup):
                # Direct dependencies are rechecked against the index, even when
                # already installed. Stay within requirements and Python markers.
                if not upgrade_dependencies():
                    raise RuntimeError(
                        "Actualizarea bibliotecilor a eșuat. Se încearcă restaurarea codului anterior; "
                        "pip poate să fi modificat parțial mediul .venv. "
                        "Rulează install_windows.bat pentru repararea bibliotecilor."
                    )

                # Refresh the optional llama.cpp backend automatically as well.
                # Failure does not invalidate the core application update.
                ensure_local_ai_backend()

                # Prepare Tesseract OCR on the user's PC as part of the
                # normal updater. The verified Windows installer and both
                # language models live in .luxai_data/ocr, a preserved local
                # folder. Failure does not corrupt the already-updated app.
                ocr_ready = True
                if sys.platform == "win32" and (ROOT / ".venv" / "Scripts" / "python.exe").is_file():
                    report("Pregatesc OCR integrat: Tesseract + rusa/engleza...")
                    venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
                    try:
                        ocr_result = subprocess.run(
                            [str(venv_python), "-m", "luxai.ocr_setup"],
                            cwd=str(ROOT), check=False, timeout=330,
                        )
                        ocr_ready = ocr_result.returncode == 0
                    except (subprocess.TimeoutExpired, OSError) as exc:
                        ocr_ready = False
                        report(f"OCR: eroare la instalare: {exc}")
                    if not ocr_ready:
                        report(
                            "AVERTISMENT: Codul Jarvis este actualizat, dar "
                            "Tesseract nu s-a instalat. Verifica internetul "
                            "sau permisiunile Windows. Instalarea OCR se "
                            "reincearca si automat din aplicatie."
                        )

                write_update_state(latest_sha)
            report("Actualizare instalată cu succes.")
            if backup.exists():
                report(f"Backup pentru fișierele suprascrise: {backup}")
            else:
                report("Nu au existat fișiere existente care să necesite backup.")
            report("Nu am șters niciun fișier local.")
            report("Folderul models și config.json au fost păstrate.")
            report("Pornește Lux AI cu run_windows.bat.")
            return 0
        except Exception as e:
            report(f"Actualizarea a eșuat: {e}")
            report("Datele personale au fost păstrate. Verifică mesajele de restaurare și folderul backups.")
            return 1


def main() -> int:
    try:
        with updater_lock():
            return perform_update()
    except (OSError, RuntimeError) as exc:
        report(f"Actualizarea nu poate porni: {exc}")
        return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        report("\nActualizare anulată.")
        raise SystemExit(130)
