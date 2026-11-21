#!/usr/bin/env python3
"""Safe additive updater for Lux AI Local from the public GitHub main branch."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
import zlib
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
    "backups", "downloads", "logs", "recordings", "screenshots", "config.json", "settings.json",
    ".env", "config.local.json", "updater_config.json", ".luxai_secrets", ".luxai_data",
    ".luxai_update_state.json", "online_agent.log", "voice_error.log",
}
SKIP_SUFFIXES = {".pyc", ".pyo", ".onnx", ".gguf"}
CLEANUP_MANIFEST = "runtime_cleanup_manifest.json"


# ---- Setup window (0.4.2l) -------------------------------------------------
# scripts/setup_ui.ps1 shows the progress; this file only appends JSON lines.
UI_EVENTS: Path | None = None
_CONSOLE_HIDDEN = False


def ui_emit(**event) -> None:
    if UI_EVENTS is None:
        return
    try:
        with UI_EVENTS.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass


def ui_step(step: str, state: str) -> None:
    ui_emit(t="step", id=step, state=state)


def ui_detail(ro: str, ru: str = "", en: str = "") -> None:
    ui_emit(t="detail", text=ro, ru=ru or ro, en=en or ro)


def _console(show: bool) -> None:
    global _CONSOLE_HIDDEN
    if sys.platform != "win32":
        return
    try:
        import ctypes
        window = ctypes.windll.kernel32.GetConsoleWindow()
        if window:
            ctypes.windll.user32.ShowWindow(window, 5 if show else 0)
            _CONSOLE_HIDDEN = not show
    except Exception:
        pass


def _setup_ui_script() -> Path | None:
    """The window script: the CURRENT one from GitHub first, the installed copy only as a fallback.

    An older installed window loaded the fonts straight from luxai/assets/fonts and kept them open,
    so the update could not replace Onest.ttf (WinError 5). It must never run from the folder the
    update rewrites.
    """
    try:
        target = Path(tempfile.gettempdir()) / f"luxai_setup_ui_{os.getpid()}.ps1"
        download(f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}/scripts/setup_ui.ps1", target)
        if target.stat().st_size > 1000 and target.read_bytes().startswith(b"\xef\xbb\xbf"):
            return target
    except Exception:
        pass
    local = ROOT / "scripts" / "setup_ui.ps1"
    if local.is_file():
        copy = Path(tempfile.gettempdir()) / f"luxai_setup_ui_{os.getpid()}.ps1"
        try:
            shutil.copy2(local, copy)
            return copy
        except OSError:
            return local
    return None


def start_ui(mode: str = "update") -> bool:
    """Open the setup window and hide this console; False = stay in the console."""
    global UI_EVENTS
    if sys.platform != "win32" or os.environ.get("LUXAI_NO_UI") or os.environ.get("LUXAI_NO_DOWNLOADS"):
        return False
    script = _setup_ui_script()
    if script is None:
        return False
    import time
    temp = Path(tempfile.gettempdir())
    events = temp / f"luxai_{mode}_{os.getpid()}.jsonl"
    ready = events.with_suffix(".ready")
    try:
        events.write_text("", encoding="utf-8")
        ready.unlink(missing_ok=True)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-STA", "-WindowStyle", "Hidden",
             "-File", str(script), "-Events", str(events), "-Mode", mode, "-Root", str(ROOT),
             "-ProducerPid", str(os.getpid()), "-Ready", str(ready)],
            cwd=str(ROOT), creationflags=flags, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    except OSError:
        return False
    UI_EVENTS = events
    os.environ["LUXAI_UI_EVENTS"] = str(events)  # helpers (translator download) report bytes too
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        if ready.exists():
            _console(False)
            try:
                (ROOT / ".luxai_update_ui").write_text("1", encoding="ascii")  # Update.bat: no «pause»
            except OSError:
                pass
            return True
        time.sleep(0.1)
    return True  # the window may still come; keep the console visible meanwhile


def ui_finish(ok: bool, ro: str, ru: str, en: str) -> None:
    ui_emit(t="done", ok=ok, message=ro, ru=ru, en=en)
    if not ok and _CONSOLE_HIDDEN and not os.environ.get("LUXAI_BAT_UI"):
        _console(True)  # an older Update.bat waits with «pause» in its console


def report(message: str, ru: str = "", en: str = "") -> None:
    """Console line + a line in the window's «Details» (in the app's language when given)."""
    ui_emit(t="log", text=message, ru=ru or message, en=en or message)
    _report_console(message)


def _report_console(message: str) -> None:
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


_SHOW_BYTES = False  # the next download shows its bytes in the setup window


def download(url: str, target: Path) -> None:
    import time
    progress = _SHOW_BYTES
    req = urllib.request.Request(url, headers={"User-Agent": "LuxAI-Updater"})
    total = 0
    shown = 0.0
    with urllib.request.urlopen(req, timeout=60) as response, target.open("wb") as out:
        size = int(response.headers.get("Content-Length") or 0)
        while True:
            chunk = response.read(256 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_DOWNLOAD_BYTES:
                raise RuntimeError("Arhiva depășește limita de siguranță de 500 MB.")
            out.write(chunk)
            if progress and time.monotonic() - shown > 0.25:
                shown = time.monotonic()
                ui_emit(t="bytes", done=total, total=size)
    if progress:
        ui_emit(t="bytes", done=total, total=size or total)


# ---- signed releases (0.4.2u, audit #8) -----------------------------------------
# A copy of the verifier in scripts/release_signature.py (tests check both agree): the archive is checked
# with the key built into THIS file, never with code taken from the archive being checked.
RELEASE_PUBLIC_KEY = "3e8a92f065399c640b507a1bf5488a91230c9582ed3595f226210c91b62237fb"
RELEASE_MANIFEST = "release_manifest.json"
RELEASE_SIGNATURE = "release_manifest.sig"
_CRLF_SUFFIXES = (".bat", ".cmd")

_P = 2 ** 255 - 19
_Q = 2 ** 252 + 27742317777372353535851937790883648493


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


_D = -121665 * _inv(121666) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _add(a, b):
    A = (a[1] - a[0]) * (b[1] - b[0]) % _P
    B = (a[1] + a[0]) * (b[1] + b[0]) % _P
    C = 2 * a[3] * b[3] * _D % _P
    D = 2 * a[2] * b[2] % _P
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F % _P, G * H % _P, F * G % _P, E * H % _P)


def _mul(s: int, point):
    result = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            result = _add(result, point)
        point = _add(point, point)
        s >>= 1
    return result


def _equal(a, b) -> bool:
    return (a[0] * b[2] - b[0] * a[2]) % _P == 0 and (a[1] * b[2] - b[1] * a[2]) % _P == 0


def _recover_x(y: int, sign: int):
    if y >= _P:
        return None
    x2 = (y * y - 1) * _inv(_D * y * y + 1) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


_GY = 4 * _inv(5) % _P
_GX = _recover_x(_GY, 0)
_G = (_GX, _GY, 1, _GX * _GY % _P)


def _compress(point) -> bytes:
    z = _inv(point[2])
    x, y = point[0] * z % _P, point[1] * z % _P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _decompress(data: bytes):
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % _P)


def _hash_int(data: bytes) -> int:
    return int.from_bytes(hashlib.sha512(data).digest(), "little") % _Q


def _expand(secret: bytes):
    digest = hashlib.sha512(secret).digest()
    a = int.from_bytes(digest[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, digest[32:]


def _sig_public_key(secret: bytes) -> bytes:
    a, _prefix = _expand(secret)
    return _compress(_mul(a, _G))


def _sig_sign(secret: bytes, message: bytes) -> bytes:
    a, prefix = _expand(secret)
    public = _compress(_mul(a, _G))
    r = _hash_int(prefix + message)
    encoded_r = _compress(_mul(r, _G))
    s = (r + _hash_int(encoded_r + public + message) * a) % _Q
    return encoded_r + s.to_bytes(32, "little")


def _sig_verify(public: bytes, message: bytes, signature: bytes) -> bool:
    if len(public) != 32 or len(signature) != 64:
        return False
    point_a = _decompress(public)
    point_r = _decompress(signature[:32])
    if point_a is None or point_r is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _Q:
        return False
    h = _hash_int(signature[:32] + public + message)
    return _equal(_mul(s, _G), _add(point_r, _mul(h, point_a)))


def _sig_file_digest(name: str, data: bytes) -> str:
    """SHA-256 as GitHub's archive has the file; batch files are compared with LF line ends."""
    if name.lower().endswith(_CRLF_SUFFIXES):
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()



VERIFIED_DIGESTS: dict[str, str] = {}  # rel path → signed SHA-256 of the archive just verified


def verify_release(source: Path) -> str:
    """Every file of the downloaded archive must be exactly the signed one; returns the signed version."""
    try:
        manifest = (source / RELEASE_MANIFEST).read_bytes()
        signature = bytes.fromhex((source / RELEASE_SIGNATURE).read_text(encoding="ascii").strip())
    except (OSError, ValueError) as exc:
        raise RuntimeError("Actualizarea nu este semnată de LuxAI. Nu instalez nimic.") from exc
    if not _sig_verify(bytes.fromhex(RELEASE_PUBLIC_KEY), manifest, signature):
        raise RuntimeError("Semnătura actualizării nu corespunde cheii LuxAI. Nu instalez nimic.")
    data = json.loads(manifest.decode("utf-8"))
    expected = data.get("files") if isinstance(data, dict) else None
    if not isinstance(expected, dict):
        raise RuntimeError("Manifestul actualizării are o formă neașteptată.")
    actual = {}
    for path in source.rglob("*"):
        if path.is_file():
            rel = path.relative_to(source).as_posix()
            if rel not in (RELEASE_MANIFEST, RELEASE_SIGNATURE):
                actual[rel] = _sig_file_digest(rel, path.read_bytes())
    changed = sorted(name for name in set(actual) | set(expected) if actual.get(name) != expected.get(name))
    if changed:
        raise RuntimeError("Fișiere care nu corespund semnăturii: " + ", ".join(changed[:5])
                           + (" …" if len(changed) > 5 else ""))
    VERIFIED_DIGESTS.clear()
    VERIFIED_DIGESTS.update(actual)  # reused for the installation state (audit 2 #33)
    return str(data.get("version", ""))


def is_preserved(rel: Path) -> bool:
    # Windows paths are case insensitive. A differently-cased ZIP entry must
    # never overwrite the user's settings, environment or model files.
    return (
        any(part.casefold() in PRESERVE_NAMES or part.casefold().startswith((".venv.old-", ".env."))
            for part in rel.parts)
        or rel.suffix.lower() in SKIP_SUFFIXES
        or rel.name.casefold().endswith(".onnx.json")
    )


def is_development_file(rel: Path) -> bool:
    """GitHub-only source and Markdown; text help and license notices remain."""
    parts = tuple(part.casefold() for part in rel.parts)
    return bool(parts) and (
        rel.suffix.casefold() == ".md"
        # Git settings and an old example: needed on GitHub, not on the user's PC (0.4.2o).
        or (len(parts) == 1 and parts[0] in {".gitattributes", ".gitignore", "manifest.example.json", ".txt"})
        or parts[0] in {"tests", ".github"}
        or (len(parts) == 2 and parts[0] == "scripts"
            and parts[1].startswith("test_") and parts[1].endswith(".py"))
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
        # One decompression (audit 2 #33): extracting checks every file's CRC itself, testzip() first
        # decompressed the whole archive a second time.
        try:
            zf.extractall(destination)
        except (zipfile.BadZipFile, zlib.error, EOFError) as exc:
            raise RuntimeError(f"Arhivă ZIP deteriorată: {exc}") from exc


def validate_staged_source(source: Path) -> None:
    """Catch incomplete archives and Python syntax errors before replacing code."""
    for name in ("main.py", "launch_windows.py", "requirements.txt", "luxai/voice.py", "run_windows.bat"):
        if not (source / name).is_file():
            raise RuntimeError(f"Arhiva este incompletă: lipsește {name}.")
    for path in source.rglob("*.py"):
        rel = path.relative_to(source)
        if not is_preserved(rel) and not is_development_file(rel):
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
        if destination.suffix.lower() in (".bat", ".cmd"):
            # cmd.exe misreads LF-only batch files (GitHub archives keep LF): «echo» became «ho».
            data = source.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            temporary.write_bytes(data)
            shutil.copystat(source, temporary)
        else:
            shutil.copy2(source, temporary)
        _replace_with_retry(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _replace_with_retry(temporary: Path, destination: Path, attempts: int = 12) -> None:
    """A file held open for a moment (antivirus scan, a closing program, a font in use) is retried
    for about 6 s before the update gives up and restores the previous files."""
    import time
    for attempt in range(attempts):
        try:
            os.replace(temporary, destination)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.5)


def _is_link(path: Path) -> bool:
    """Include Windows junctions/reparse points on Python 3.11 as well."""
    return path.is_symlink() or bool(
        getattr(path.lstat(), "st_file_attributes", 0) & 0x400
    )


def _tree_has_links(directory: Path) -> bool:
    if _is_link(directory):
        return True
    for parent, directories, files in os.walk(directory, followlinks=False):
        if any(_is_link(Path(parent) / name) for name in directories + files):
            return True
    return False


def _cleanup_catalog() -> dict[str, set[str]]:
    """Read a bounded, validated catalog of exact published source hashes.

    A path alone never authorizes deletion. Unknown, edited or user-added
    content is retained, including files inside a source-only directory.
    """
    catalog = ROOT / CLEANUP_MANIFEST
    if not catalog.is_file() or _is_link(catalog) or catalog.stat().st_size > 4 * 1024 * 1024:
        return {}
    data = json.loads(catalog.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("format") != 1
            or not isinstance(data.get("files"), dict)
            or len(data["files"]) > MAX_ARCHIVE_FILES):
        raise ValueError("Invalid cleanup catalog")
    result = {}
    reserved = {"con", "prn", "aux", "nul"} | {
        f"{prefix}{n}" for prefix in ("com", "lpt") for n in range(1, 10)
    }
    for name, hashes in data["files"].items():
        if not isinstance(name, str) or "\\" in name or any(ord(char) < 32 for char in name):
            raise ValueError("Invalid cleanup path")
        rel = PurePosixPath(name)
        if (not rel.parts or rel.is_absolute() or ".." in rel.parts
                or name != rel.as_posix()
                or any(":" in part or part.endswith((".", " "))
                       or part.split(".")[0].casefold() in reserved for part in rel.parts)
                or not is_development_file(Path(name)) or is_preserved(Path(name))
                or not isinstance(hashes, list) or not hashes or len(hashes) > 2000
                or any(not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None
                       for value in hashes)):
            raise ValueError("Invalid cleanup catalog entry")
        result[name] = set(hashes)
    return result


def cleanup_development_files() -> None:
    """Remove unchanged bundled development files from an installation only."""
    # A Git checkout is a development copy, including worktrees whose .git
    # entry is a file. Never trim the maintainer's checked-out source.
    if (ROOT / ".git").exists() or (ROOT / ".git").is_symlink():
        return
    removed = 0
    try:
        if _is_link(ROOT):
            return
        catalog = _cleanup_catalog()  # Validate every entry before any deletion.
        for name, hashes in catalog.items():
            path = ROOT / name
            try:
                if any(_is_link(parent) for parent in (path, *path.parents)
                       if parent != ROOT and parent.exists()):
                    continue
                if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
                    continue
                if hashlib.sha256(path.read_bytes()).hexdigest() not in hashes:
                    continue
                path.unlink()
                removed += 1
                parent = path.parent
                while parent != ROOT:
                    try:
                        parent.rmdir()  # Only empty directories; retain personal additions.
                    except OSError:
                        break
                    parent = parent.parent
            except OSError:
                continue  # Locked files can be retried by the next update/install.
    except (OSError, ValueError, TypeError) as exc:
        report(f"Curățarea fișierelor de dezvoltare a fost omisă: {type(exc).__name__}.")
    if removed:
        report(f"Fișiere de dezvoltare nemodificate eliminate: {removed}.")


_LEGACY_BACKUP_NAME = re.compile(
    r"\d{8}-\d{6}(?:-\d{6})?-(?:[a-f0-9]{12}|initial)\Z"
)


def _legacy_manifest(path: Path) -> set[str] | None:
    if not path.is_file() or _is_link(path) or path.stat().st_size > 4 * 1024 * 1024:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) != {"overwritten", "new"}:
            return None
        for entries in (data["overwritten"], data["new"]):
            if not isinstance(entries, list) or len(entries) > MAX_ARCHIVE_FILES:
                return None
            for value in entries:
                if not isinstance(value, str):
                    return None
                relative = PurePosixPath(value.replace("\\", "/"))
                if (not relative.parts or relative.is_absolute() or ".." in relative.parts
                        or any(":" in part for part in relative.parts)):
                    return None
        return {PurePosixPath(value.replace("\\", "/")).as_posix()
                for value in data["overwritten"]}
    except (OSError, ValueError, TypeError):
        return None


def cleanup_legacy_backups() -> None:
    """Remove only backups made by earlier LuxAI updaters, never user folders.

    A recognized name plus its valid transaction manifest identifies modern
    backups. Pre-0.2 backups lacked manifests; require their old timestamp
    format and application code, and reject any preserved personal files.
    Never traverse a symlink, junction, or other Windows reparse point.
    """
    removed = 0
    try:
        if BACKUP_ROOT.is_dir() and not _is_link(BACKUP_ROOT):
            for saved in list(BACKUP_ROOT.iterdir()):
                if not _LEGACY_BACKUP_NAME.fullmatch(saved.name):
                    continue
                if not saved.is_dir() or _tree_has_links(saved):
                    continue
                manifest = saved.with_name(saved.name + ".manifest.json")
                expected = _legacy_manifest(manifest)
                actual = {path.relative_to(saved).as_posix()
                          for path in saved.rglob("*") if path.is_file()}
                if any(is_preserved(Path(value)) for value in actual):
                    continue
                if expected is None:
                    if manifest.exists() or re.fullmatch(
                        r"\d{8}-\d{6}-(?:[a-f0-9]{12}|initial)", saved.name
                    ) is None:
                        continue
                    if not (saved / "main.py").is_file() or any(
                        is_preserved(Path(value)) for value in actual
                    ):
                        continue
                elif not actual.issubset(expected):
                    # An extra user file was placed inside this backup.
                    continue
                shutil.rmtree(saved)
                if expected is not None:
                    manifest.unlink()
                removed += 1
            # A previous interrupted cleanup may leave only the manifest.
            for manifest in BACKUP_ROOT.glob("*.manifest.json"):
                name = manifest.name.removesuffix(".manifest.json")
                if (_LEGACY_BACKUP_NAME.fullmatch(name)
                        and not (BACKUP_ROOT / name).exists()
                        and _legacy_manifest(manifest) is not None):
                    manifest.unlink()
            try:
                BACKUP_ROOT.rmdir()
            except OSError:
                pass  # Unknown/user files in this directory are retained.
        data = ROOT / ".luxai_data"
        bootstrap = data / "updater-bootstrap"
        if (data.is_dir() and not _is_link(data)
                and bootstrap.is_dir() and not _is_link(bootstrap)):
            previous = bootstrap / "Update.py.previous"
            if previous.is_file() and not _is_link(previous):
                previous.unlink()
            try:
                bootstrap.rmdir()
            except OSError:
                pass
    except OSError as exc:
        report(f"Nu am putut elimina toate copiile vechi ale updaterului: {type(exc).__name__}.")
    if removed:
        report(f"Copii vechi ale updaterului eliminate: {removed}.")


@contextmanager
def file_transaction(files: list[tuple[Path, Path]], backup: Path | None = None, remove=()):
    """Restore replaced code and remove new code if any update step fails.

    ``remove``: files the new version dropped (audit 2 #2). They are deleted INSIDE the transaction,
    after a backup copy, and come back with everything else when a later step (including writing
    the installation state) fails.

    Package installation is a separate operation: pip cannot roll back all
    package changes. On dependency failure we restore the previous code and
    explicitly direct the user to the installer to repair the environment.
    """
    destinations = [(src, rel, _destination(rel)) for src, rel in files]
    removals = [(Path(rel), ROOT / Path(rel)) for rel in remove]
    managed = backup is None
    backup = Path(tempfile.mkdtemp(prefix="luxai_rollback_")) if managed else backup
    retain = False
    try:
        originals = set()
        for _, rel, dest in destinations + [(None, rel, dest) for rel, dest in removals]:
            if dest.is_file():
                saved = backup / rel
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, saved)
                originals.add(rel)
        backup.mkdir(parents=True, exist_ok=True)
        applied = []
        try:
            # 0.4.2u (audit #29): stage every new file next to the installation, write a durable
            # journal, then MOVE the staged files into place (each move is atomic and instant). If the PC
            # stops in between, resume_interrupted_update() finishes the moves at the next start.
            staging = _stage_files([(src, rel) for src, rel, _dest in destinations])
            for _src, rel, dest in destinations:
                dest.parent.mkdir(parents=True, exist_ok=True)  # a new folder in this version
                _replace_with_retry(staging / rel, dest)
                applied.append((rel, dest))
            dropped = 0
            for rel, dest in removals:
                if rel in originals:
                    dest.unlink(missing_ok=True)
                    applied.append((rel, dest))  # restored from the backup on failure
                    dropped += 1
            if dropped:
                report(f"Fișiere vechi eliminate: {dropped}.", f"Удалено старых файлов: {dropped}.",
                       f"Old files removed: {dropped}.")
            yield
            _finish_journal()
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
                retain = True
                if managed:
                    # Preserve recovery data only for the exceptional case
                    # where Windows prevented restoring the old installation.
                    recovery = ROOT / ".luxai_data" / "update-recovery"
                    try:
                        data = recovery.parent
                        if (data.exists() and _is_link(data)) or (recovery.exists() and _is_link(recovery)):
                            raise OSError("Recovery directory is a local link")
                        recovery.mkdir(parents=True, exist_ok=True)
                        target = recovery / backup.name
                        shutil.move(str(backup), str(target))
                        backup = target
                    except OSError:
                        # Keep the original temp directory if moving recovery
                        # files also failed; never discard the only originals.
                        pass
                report(f"Restaurarea automată nu este completă. Recuperare: {backup}")
                report("; ".join(errors))
                raise RuntimeError(f"Restaurare incompletă; fișierele originale sunt în {backup}") from failure
            report("Fișierele programului au fost restaurate la versiunea anterioară.")
            _finish_journal()
            raise
    finally:
        if not retain:
            try:
                shutil.rmtree(backup)
            except OSError:
                report("Nu am putut elimina toate fișierele temporare ale actualizării.")


PENDING_FILE = ROOT / ".luxai_update_pending.json"


def _journal_file() -> Path:
    return ROOT / ".luxai_update_journal.json"


def _staging_root() -> Path:
    return ROOT / ".luxai_data" / "update-staging"  # same disk as the installation: moves are atomic


def _fsync_write(path: Path, data: bytes) -> None:
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with open(temporary, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _stage_files(files) -> Path:
    """Copy the new files into one staging folder on the same disk, then record the journal."""
    import uuid
    staging = _staging_root() / uuid.uuid4().hex[:12]
    hashes = {}
    for src, rel in files:
        target = staging / rel
        _atomic_copy(src, target)  # also turns .bat/.cmd into CRLF
        # The digest of the STAGED bytes: after a crash, a file already moved is recognised by it (audit 3 #1).
        hashes[Path(rel).as_posix()] = hashlib.sha256(target.read_bytes()).hexdigest()
    _fsync_write(_journal_file(), json.dumps({"staging": staging.name, "files": list(hashes),
                                           "sha256": hashes}).encode("utf-8"))
    return staging


def _finish_journal() -> None:
    try:
        journal = json.loads(_journal_file().read_text(encoding="utf-8"))
        name = str(journal.get("staging", ""))
    except (OSError, ValueError, AttributeError):
        name = ""
    _journal_file().unlink(missing_ok=True)
    if name and "/" not in name and "\\" not in name and name not in (".", ".."):
        shutil.rmtree(_staging_root() / name, ignore_errors=True)


def resume_interrupted_update() -> int:
    """Finish the file moves of an update the PC did not finish (power cut, forced close).

    Returns the number of files moved, or -1 when the state cannot be confirmed (audit 3 #1): an unreadable
    journal, or a file that is neither waiting in staging nor already in place with its recorded digest.
    Then the journal STAYS, the launcher keeps Jarvis closed and Update.bat installs everything again —
    success is never declared for a state nobody can check.
    """
    if not _journal_file().exists():
        return 0
    try:
        journal = json.loads(_journal_file().read_text(encoding="utf-8"))
        name = str(journal["staging"])
        files = [str(item) for item in journal["files"]]
        digests = journal["sha256"]
        # The shape is checked first (audit 4 #1): a non-empty list, and a 64-hex digest for EVERY file.
        if (not isinstance(journal["files"], list) or not files or not isinstance(digests, dict)
                or any(not re.fullmatch(r"[0-9a-f]{64}", str(digests.get(rel, ""))) for rel in files)):
            raise ValueError("journal shape")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        report("Jurnalul actualizării întrerupte nu poate fi citit — rulează Update.bat.",
               "Журнал прерванного обновления не читается — запустите Update.bat.",
               "The interrupted update's journal cannot be read — run Update.bat.")
        return -1
    if "/" in name or "\\" in name or name in ("", ".", ".."):
        return -1
    staging = _staging_root() / name

    def digest(path: Path) -> str:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""
        except OSError:
            return ""

    # Every file is checked BEFORE anything moves (audit 4 #1): a staged file must still be exactly the
    # staged bytes, and a file no longer in staging must already be in place with that digest.
    to_move = []
    unconfirmed = []
    for rel in files:
        path = PurePosixPath(rel)
        if path.is_absolute() or ".." in path.parts:
            unconfirmed.append(rel)
            continue
        staged = staging.joinpath(*path.parts)
        target = ROOT.joinpath(*path.parts)
        if staged.is_file():
            if digest(staged) == digests[rel]:
                to_move.append((staged, target))
            else:
                unconfirmed.append(rel)  # damaged in staging: never installed
        elif digest(target) != digests[rel]:
            unconfirmed.append(rel)
    moved = 0
    if not unconfirmed:
        for staged, target in to_move:
            target.parent.mkdir(parents=True, exist_ok=True)
            _replace_with_retry(staged, target)
            moved += 1
    if unconfirmed:
        report(f"Actualizarea întreruptă nu poate fi confirmată ({len(unconfirmed)} fișiere) — rulează Update.bat.",
               f"Прерванное обновление не подтверждено (файлов: {len(unconfirmed)}) — запустите Update.bat.",
               f"The interrupted update cannot be confirmed ({len(unconfirmed)} files) — run Update.bat.")
        return -1
    _finish_journal()
    if moved:
        report(f"Am terminat o actualizare întreruptă ({moved} fișiere).",
               f"Завершил прерванное обновление (файлов: {moved}).", f"Finished an interrupted update ({moved} files).")
    return moved


def write_pending(latest_sha: str) -> None:
    try:
        PENDING_FILE.write_text(json.dumps({"commit": latest_sha, "started": int(__import__("time").time())}),
                                encoding="utf-8")
    except OSError:
        pass


def clear_pending() -> None:
    try:
        PENDING_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _installed_hashes(files) -> dict[str, str]:
    """SHA-256 of each installed file. The signed digest of the verified archive is reused when the
    installed bytes are the same bytes (everything except .bat/.cmd, which get CRLF) — audit 2 #33."""
    hashes = {}
    for _src, rel in files or []:
        name = rel.as_posix()
        known = VERIFIED_DIGESTS.get(name)
        if known and not name.lower().endswith(_CRLF_SUFFIXES):
            hashes[name] = known
            continue
        destination = _destination(rel)
        try:
            hashes[rel.as_posix()] = hashlib.sha256(destination.read_bytes()).hexdigest()
        except OSError:
            continue
    return hashes


def write_update_state(latest_sha: str, files=None) -> None:
    fd, name = tempfile.mkstemp(prefix=".luxai-state-", dir=ROOT)
    os.close(fd)
    temporary = Path(name)
    state = {"commit": latest_sha, "branch": BRANCH, "requirements": requirements_fingerprint()}
    if files is not None:
        state["files"] = _installed_hashes(files)
    try:
        temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(temporary, STATE_FILE)
    finally:
        temporary.unlink(missing_ok=True)


def _previous_file_hashes() -> dict:
    try:
        old = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    files = old.get("files", {}) if isinstance(old, dict) else {}
    return files if isinstance(files, dict) else {}


def dropped_files(previous: dict, current) -> list[str]:
    """Files the previous update installed that the new version no longer has, still UNCHANGED (audit #29).

    Only computed here; they are removed inside file_transaction, so a failure brings them back (audit 2 #2).
    """
    current = {Path(rel).as_posix() for rel in current}
    dropped = []
    for rel, digest in previous.items():
        if rel in current or not isinstance(rel, str) or not isinstance(digest, str):
            continue
        path = PurePosixPath(rel)
        if path.is_absolute() or ".." in path.parts or is_preserved(Path(*path.parts)):
            continue
        target = ROOT.joinpath(*path.parts)
        try:
            if target.is_file() and not _is_link(target) and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
                dropped.append(path.as_posix())
        except OSError:
            continue
    return dropped


def remove_dropped_files(previous: dict, current: dict) -> int:
    """Delete the dropped files directly (kept for callers outside an update transaction)."""
    removed = 0
    for rel in dropped_files(previous, current):
        try:
            ROOT.joinpath(*PurePosixPath(rel).parts).unlink()
            removed += 1
        except OSError:
            continue
    if removed:
        report(f"Fișiere vechi eliminate: {removed}.", f"Удалено старых файлов: {removed}.", f"Old files removed: {removed}.")
    return removed


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



def _freeze() -> str | None:
    """«pip freeze --all» of the installation's .venv, or None when it cannot be read."""
    python = ROOT / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        return None
    try:
        result = subprocess.run([str(python), "-m", "pip", "freeze", "--all", "--disable-pip-version-check"],
                                capture_output=True, text=True, timeout=120, check=False,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def _package_lines(freeze: str) -> dict[str, str]:
    """Normalized package name → its exact freeze line (== pins AND «name @ url» lines; audit 2 #4)."""
    lines = {}
    for line in (freeze or "").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        name = re.split(r"\s*(?:==|@)\s*", line, maxsplit=1)[0]
        if name and name != line:
            lines[re.sub(r"[-_.]+", "-", name).lower()] = line
    return lines


def snapshot_packages() -> str:
    """The exact installed package versions (pip freeze), to put back if the update fails (audit #7)."""
    freeze = _freeze()
    lines = list(_package_lines(freeze or "").values())
    return "\n".join(lines) + "\n" if lines else ""


def restore_packages(snapshot: str) -> bool:
    """Put the libraries back EXACTLY as they were before this update (audit 2 #4).

    Packages added since the snapshot are removed, changed ones go back to their old version, and
    the result is checked against the snapshot again — success is never taken from pip's exit
    code alone. Nothing to do when the environment did not change.
    """
    python = ROOT / ".venv" / "Scripts" / "python.exe"
    if not snapshot or not python.is_file():
        return False
    wanted = _package_lines(snapshot)
    current = _freeze()
    if current is not None and _package_lines(current) == wanted:
        return True
    report("Revin la versiunile anterioare ale bibliotecilor...",
           "Возвращаю прежние версии библиотек…", "Restoring the previous library versions…")
    added = sorted(set(_package_lines(current or "")) - set(wanted) - {"pip", "setuptools", "wheel"})
    fd, name = tempfile.mkstemp(prefix="luxai_packages_", suffix=".txt")
    os.close(fd)
    try:
        if added:
            run_streamed([str(python), "-m", "pip", "uninstall", "-y", "--disable-pip-version-check", *added],
                         timeout=600)
        Path(name).write_text(snapshot, encoding="utf-8")
        run_streamed([str(python), "-m", "pip", "install", "--disable-pip-version-check", "--no-deps",
                      "--prefer-binary", "-r", name], timeout=900)
    except (OSError, subprocess.TimeoutExpired):
        return False
    finally:
        Path(name).unlink(missing_ok=True)
    after = _freeze()
    restored = after is not None and _package_lines(after) == wanted
    if not restored:
        report("Bibliotecile NU au revenit complet la versiunile anterioare.",
               "Библиотеки НЕ вернулись полностью к прежним версиям.",
               "The libraries did NOT fully return to their previous versions.")
    return restored


def requirements_fingerprint() -> str:
    """SHA-256 of requirements.txt as installed by the last successful library step."""
    try:
        data = (ROOT / "requirements.txt").read_bytes().replace(b"\r\n", b"\n")
    except OSError:
        return ""
    return hashlib.sha256(data).hexdigest()


def record_requirements() -> None:
    """Remember which requirements.txt the environment now satisfies (the up-to-date path)."""
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            return
        state["requirements"] = requirements_fingerprint()
        _fsync_write(STATE_FILE, json.dumps(state, indent=2).encode("utf-8"))
    except (OSError, ValueError):
        pass


def _installed_requirements() -> str:
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    value = state.get("requirements", "") if isinstance(state, dict) else ""
    return value if isinstance(value, str) else ""


def upgrade_dependencies() -> bool:
    """Controlled libraries (audit #7): the environment changes only when the PROJECT's requirements change.

    Same requirements as last time → nothing is installed or upgraded (no drift between updates), only
    checked. Changed requirements → only what is missing or no longer satisfied is installed, never
    «everything to the newest». Either way the result must pass pip check and import Jarvis; the
    caller restores the exact previous versions (pip freeze) when it does not.
    Never touches globally installed Python packages.
    """
    windows_python = ROOT / ".venv" / "Scripts" / "python.exe"
    unix_python = ROOT / ".venv" / "bin" / "python"
    python = windows_python if windows_python.is_file() else unix_python
    requirements = ROOT / "requirements.txt"
    if not python.is_file() or not requirements.is_file():
        report("Dependențe: mediul .venv lipsește. Rulează install_windows.bat.")
        return False
    unchanged = bool(_installed_requirements()) and _installed_requirements() == requirements_fingerprint()
    check = [
        [str(python), "-m", "pip", "check"],
        [str(python), "-c", "import main; from luxai.voice import VoiceListener; print('LuxAI imports OK')"],
    ]
    if unchanged:
        report("Cerințele bibliotecilor nu s-au schimbat — verific doar mediul.",
               "Требования к библиотекам не изменились — только проверяю окружение.",
               "Library requirements did not change — only checking the environment.")
        commands = check
    else:
        report("Cerințele bibliotecilor s-au schimbat — instalez doar ce lipsește.",
               "Требования к библиотекам изменились — ставлю только недостающее.",
               "Library requirements changed — installing only what is missing.")
        commands = [
            [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--prefer-binary",
             "--retries", "2", "--timeout", "30", "-r", str(requirements)],
        ] + check
    for command in commands:
        try:
            result = run_streamed(command, timeout=480)
            if result.returncode != 0:
                report("Dependențe: instalarea/verificarea a eșuat.",
                       "Библиотеки: установка/проверка не удалась.", "Libraries: install/check failed.")
                return False
        except (OSError, subprocess.TimeoutExpired) as exc:
            report(f"Dependențe: verificarea a eșuat ({type(exc).__name__}).")
            return False
    report("Bibliotecile LuxAI sunt verificate.", "Библиотеки LuxAI проверены.", "LuxAI libraries are checked.")
    return True


_PIP_LINE = [
    (re.compile(r"^Collecting (\S+)"), ("Verific {0}", "Проверяю {0}", "Checking {0}")),
    (re.compile(r"^Requirement already satisfied: (\S+)"), ("Verific {0}", "Проверяю {0}", "Checking {0}")),
    (re.compile(r"^\s*Downloading (\S+?)-\d\S* \(([^)]+)\)"), ("Descarc {0} ({1})", "Скачиваю {0} ({1})", "Downloading {0} ({1})")),
    (re.compile(r"^Installing collected packages: (.+)"), ("Instalez {0}", "Устанавливаю {0}", "Installing {0}")),
    (re.compile(r"^Successfully installed (.+)"), ("Instalat: {0}", "Установлено: {0}", "Installed: {0}")),
]


def run_streamed(command: list[str], timeout: float, cwd: Path | None = None):
    """subprocess.run with every output line also shown in the setup window.

    The output is read on a helper thread and the time limit is kept by the caller, so a child
    process that holds the pipe open cannot stretch the wait; on time-out the whole process tree is
    ended and TimeoutExpired is raised — never a misleading exit code (audit #42).
    """
    import threading
    process = subprocess.Popen(command, cwd=str(cwd or ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace")

    def pump():
        try:
            for raw in process.stdout:
                line = raw.rstrip()
                if not line:
                    continue
                _report_console(line)
                ui_emit(t="log", text=line)
                for pattern, (ro, ru, en) in _PIP_LINE:
                    match = pattern.search(line)
                    if match:
                        parts = [part[:60] for part in match.groups()]
                        ui_detail(ro.format(*parts), ru.format(*parts), en.format(*parts))
                        break
        except (OSError, ValueError):
            pass

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    try:
        process.wait(timeout)
    except subprocess.TimeoutExpired:
        # Clean-up has its own limits (audit 2 #34): taskkill at most 20 s, then a plain kill, then
        # at most 10 s for the process; the reader thread is a daemon and is never waited on here.
        if sys.platform == "win32":
            try:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True, timeout=20,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
            except (OSError, subprocess.TimeoutExpired):
                pass
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait(10)
        except subprocess.TimeoutExpired:
            pass
        raise
    reader.join(2)  # a grandchild may keep the pipe open; its output is not needed any more
    return process


def ensure_offline_translator() -> bool:
    """The offline translator (captions, read aloud, notifications, chat), installed once.

    A pinned, hash-checked model in models/, which the updater preserves.
    Failure is not fatal — the app retries in the background on first use.
    """
    python = ROOT / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        return False
    if not (ROOT / "models" / "nllb-200-600M-ct2-int8" / "model.bin").is_file():
        ui_detail("Descarc traducătorul (~640 MB, o singură dată)",
                  "Скачиваю переводчик (~640 МБ, один раз)", "Downloading the translator (~640 MB, once)")
    else:
        ui_detail("Traducătorul e deja instalat", "Переводчик уже установлен", "The translator is already installed")
    try:
        result = run_streamed([str(python), "-m", "luxai.offline_translate"], timeout=1800)
        if result.returncode != 0:
            report("AVERTISMENT: traducatorul offline nu s-a descarcat acum; Jarvis il descarca singur la prima traducere.",
                   "ВНИМАНИЕ: офлайн-переводчик сейчас не скачался; Jarvis скачает его сам при первом переводе.",
                   "WARNING: the offline translator did not download now; Jarvis downloads it on first use.")
            return False
        return True
    except (subprocess.TimeoutExpired, OSError) as exc:
        report(f"Traducator offline: eroare la descarcare: {exc}")
        return False


def ensure_ocr() -> bool:
    """Tesseract OCR in .luxai_data/ocr (preserved); failure does not break the update."""
    venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
    if sys.platform != "win32" or not venv_python.is_file():
        return True
    report("Pregatesc OCR integrat: Tesseract + rusa/engleza...",
           "Готовлю встроенный OCR: Tesseract + русский/английский…", "Preparing built-in OCR: Tesseract + Russian/English…")
    try:
        ok = run_streamed([str(venv_python), "-m", "luxai.ocr_setup"], timeout=330).returncode == 0
    except (subprocess.TimeoutExpired, OSError) as exc:
        ok = False
        report(f"OCR: eroare la instalare: {exc}")
    if not ok:
        report("AVERTISMENT: Codul Jarvis este actualizat, dar Tesseract nu s-a instalat. Verifica internetul "
               "sau permisiunile Windows. Instalarea OCR se reincearca si automat din aplicatie.",
               "ВНИМАНИЕ: Jarvis обновлён, но Tesseract не установился. Проверьте интернет или права Windows — "
               "приложение попробует ещё раз само.",
               "WARNING: Jarvis is updated, but Tesseract did not install. Check the internet or Windows permissions; "
               "the app retries by itself.")
    return ok


def run_step(step: str, action) -> bool:
    """One row of the window: active → done / warn."""
    ui_step(step, "active")
    try:
        ok = action()
    except Exception:
        ui_step(step, "warn")
        raise
    ui_step(step, "done" if ok is not False else "warn")
    return ok is not False


FIND_JARVIS_PS = r"""
$root = [IO.Path]::GetFullPath($env:LUXAI_ROOT).TrimEnd('\') + '\'
$skip = @([int]$env:LUXAI_SELF, [int]$env:LUXAI_PARENT)
Get-CimInstance Win32_Process -Filter "Name='Jarvis.exe' OR Name='pythonw.exe' OR Name='python.exe'" | Where-Object {
    $_.ProcessId -notin $skip -and $_.ExecutablePath -and
    ([IO.Path]::GetFullPath($_.ExecutablePath)).StartsWith($root, [StringComparison]::OrdinalIgnoreCase) -and
    ($_.Name -eq 'Jarvis.exe' -or $_.CommandLine -match '(main|launch_windows)\.py')
} | ForEach-Object { if ($env:LUXAI_KILL -eq '1') { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; $_.ProcessId }
"""
TASK_NAME = "LuxAI Jarvis (admin)"  # the old shared name; each folder now has its own (audit 2 #5)


def _admin_task_names() -> list[str]:
    """This folder's own task name (written by the settings switch), then the old shared name."""
    names = []
    try:
        own = (ROOT / ".luxai_data" / "admin_task.txt").read_text(encoding="ascii").strip()
        if own.startswith(TASK_NAME + " ") and len(own) <= 64 and '"' not in own:
            names.append(own)
    except (OSError, UnicodeError):
        pass
    names.append(TASK_NAME)
    return names


def our_admin_task() -> str | None:
    """The name of the admin task that starts THIS folder, or None."""
    for name in _admin_task_names():
        if _task_is_ours(name):
            return name
    return None


def admin_task_is_ours() -> bool:
    return our_admin_task() is not None


def _task_is_ours(name: str) -> bool:
    """The task belongs to THIS folder (another installation's task is never touched)."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(["schtasks", "/Query", "/TN", name, "/XML"], capture_output=True,
                                timeout=20, creationflags=flags, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    raw = result.stdout
    text = raw.decode("utf-16", "ignore") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", "ignore")
    match = re.search(r"<WorkingDirectory>(.*?)</WorkingDirectory>", text, re.I | re.S)
    if not match:
        return False
    import html
    folder = html.unescape(match.group(1)).strip().rstrip("\\/")
    return os.path.normcase(os.path.abspath(folder)) == os.path.normcase(os.path.abspath(str(ROOT)))


def _jarvis_pids(kill: bool) -> list[int]:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    env = dict(os.environ, LUXAI_ROOT=str(ROOT), LUXAI_SELF=str(os.getpid()), LUXAI_PARENT=str(os.getppid()),
               LUXAI_KILL="1" if kill else "0")
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", FIND_JARVIS_PS],
                                capture_output=True, text=True, timeout=40, env=env, creationflags=flags, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [int(line) for line in (result.stdout or "").split() if line.strip().isdigit()]


def _task_running(name: str = TASK_NAME) -> bool:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(["schtasks", "/Query", "/TN", name, "/FO", "CSV", "/NH"], capture_output=True,
                                timeout=20, creationflags=flags, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    # The status column is localized; «Running» / «Выполняется» / «În execuție» all differ from Ready/Disabled.
    line = result.stdout.decode("utf-8", "ignore") + result.stdout.decode("cp866", "ignore")
    return any(word in line for word in ("Running", "Выполняется", "execu", "Wird ausgef"))


def close_jarvis() -> int:
    """Close a running Jarvis of THIS folder before files and libraries are replaced (audit #5, #6).

    The elevated one is ended through the admin task, but only when the task belongs to this
    folder; others by path, also when started as pythonw launch_windows.py. Then wait until they
    really exited; a Jarvis that keeps running stops the update before anything is replaced.
    """
    if sys.platform != "win32" or os.environ.get("LUXAI_NO_DOWNLOADS") or not (ROOT / ".venv").exists():
        return 0  # tests and folders without an installed Jarvis
    import time
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    ours = our_admin_task()
    if ours:
        try:
            subprocess.run(["schtasks", "/End", "/TN", ours], capture_output=True, timeout=15,
                           creationflags=flags, check=False)
        except (OSError, subprocess.TimeoutExpired):
            pass
    closed = _jarvis_pids(kill=True)
    deadline = time.monotonic() + 15
    remaining = _jarvis_pids(kill=False)
    while (remaining or (ours and _task_running(ours))) and time.monotonic() < deadline:
        time.sleep(0.7)
        remaining = _jarvis_pids(kill=False)
    if remaining or (ours and _task_running(ours)):
        raise RuntimeError("Jarvis nu s-a închis (PID " + ", ".join(map(str, remaining)) + "). "
                           "Închide-l din bara de sistem și pornește din nou Update.bat.")
    if closed:
        report(f"Am închis Jarvis ({len(closed)} proces/e) pentru actualizare.",
               f"Закрыл Jarvis (процессов: {len(closed)}) для обновления.",
               f"Closed Jarvis ({len(closed)} process(es)) for the update.")
        time.sleep(1.0)  # let Windows release the files
    return len(closed)


def _remote_version(sha: str) -> str:
    try:
        req = urllib.request.Request(f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{sha}/version.txt",
                                     headers={"User-Agent": "LuxAI-Updater"})
        with urllib.request.urlopen(req, timeout=10) as response:
            value = response.read(64).decode("utf-8", "replace").strip()
        return value if re.fullmatch(r"[0-9][0-9A-Za-z.\-]{0,30}", value) else ""
    except Exception:
        return ""


def _older_version(candidate: str, installed: str) -> bool:
    def key(value):
        match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:\.?([a-z]+))?", str(value).strip(), re.I)
        if not match:
            return None
        suffix = (match.group(4) or "").lower()
        return int(match.group(1)), int(match.group(2)), int(match.group(3)), (len(suffix), suffix)
    new, old = key(candidate), key(installed)
    return bool(new and old and new < old)


def _local_version() -> str:
    try:
        return (ROOT / "version.txt").read_text(encoding="utf-8").strip()[:32]
    except OSError:
        return ""


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
        result = run_streamed([str(python), "-m", "luxai.local_ai_setup"], timeout=480)
        if result.returncode == 0:
            report("Motorul GGUF este instalat si verificat.")
            return True
    except (OSError, subprocess.TimeoutExpired) as exc:
        report(f"GGUF: instalarea nu a reusit: {type(exc).__name__}.")
    report("GGUF: nu este disponibil; verifica logs/local_ai_install.log.")
    report("Jarvis si comenzile fara GGUF continua sa functioneze.")
    return False



def cleanup_retired_fish_local() -> bool:
    """Remove only the discontinued Fish S2 local installation.

    Cloud Fish Audio (luxai/fish_tts.py), Piper models, other GGUF models,
    credentials and personal recordings outside models/fishaudio are retained.
    Never follow user-controlled symlinks or Windows junctions.
    """
    if (ROOT / ".git").exists() or (ROOT / ".git").is_symlink():
        report("Fish S2 cleanup skipped in a Git working tree.")
        return True
    if _is_link(ROOT):
        report("Fish S2 cleanup blocked: installation path is a link.")
        return False

    success = True
    models = ROOT / "models"
    fish_dir = models / "fishaudio"
    try:
        if models.exists() and _is_link(models):
            report("Fish S2 cleanup blocked: models is a link.")
            success = False
        elif fish_dir.is_symlink() or (fish_dir.exists() and _is_link(fish_dir)):
            report("Fish S2 cleanup blocked: fishaudio is a link.")
            success = False
        elif fish_dir.exists():
            if not fish_dir.is_dir() or _tree_has_links(fish_dir):
                report("Fish S2 cleanup blocked: untrusted link inside fishaudio.")
                success = False
            else:
                shutil.rmtree(fish_dir)
                report("Removed models/fishaudio (local GGUF, tokenizer and CPU runtime).")
    except OSError as exc:
        report(f"Fish S2 cleanup could not remove the model folder: {type(exc).__name__}.")
        success = False

    # The incremental updater deliberately does not delete obsolete application
    # files on its own. Remove exactly the retired Fish S2 entry points.
    retired = (
        "install_fish_audio.bat",
        "luxai/fish_local.py",
        "luxai/fish_local_setup.py",
        "luxai/fish_local_worker.py",
        "luxai/fish_local_reference.py",
        "scripts/build_fish_runtime.py",
    )
    for name in retired:
        target = ROOT / name
        try:
            if any(_is_link(parent) for parent in target.parents if parent != ROOT and parent.exists()):
                report(f"Fish S2 cleanup blocked: linked parent of {name}.")
                success = False
            elif target.is_symlink() or (target.exists() and _is_link(target)):
                report(f"Fish S2 cleanup blocked: linked file {name}.")
                success = False
            elif target.is_file():
                target.unlink()
        except OSError as exc:
            report(f"Could not remove retired Fish S2 file {name}: {type(exc).__name__}.")
            success = False

    cache = ROOT / "luxai" / "__pycache__"
    try:
        if cache.is_dir() and not _is_link(cache) and not _is_link(cache.parent):
            for path in cache.glob("fish_local*.pyc"):
                if path.is_symlink() or _is_link(path):
                    success = False
                else:
                    path.unlink()
    except OSError:
        success = False

    # A retained config may still select the removed engine. Switch only that
    # engine back to Fish cloud, preserving its independently stored API key.
    config_file = ROOT / "config.json"
    if config_file.exists():
        try:
            if _is_link(config_file):
                report("Fish S2 cleanup blocked: config.json is a link.")
                return False
            config = json.loads(config_file.read_text(encoding="utf-8"))
            if isinstance(config, dict):
                changed = False
                if config.get("voice_engine") == "fish_local":
                    config["voice_engine"] = "fish"
                    changed = True
                for key in ("fish_local_reference", "fish_local_reference_text",
                            "fish_local_threads"):
                    if key in config:
                        config.pop(key)
                        changed = True
                if changed:
                    fd, temporary_name = tempfile.mkstemp(
                        prefix=".luxai-fish-migrate-", suffix=".json", dir=ROOT)
                    os.close(fd)
                    temporary = Path(temporary_name)
                    try:
                        temporary.write_text(
                            json.dumps(config, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
                        os.replace(temporary, config_file)
                    finally:
                        temporary.unlink(missing_ok=True)
                    report("Voice settings migrated from local Fish S2 to Fish Audio cloud.")
        except (OSError, ValueError, TypeError) as exc:
            report(f"Could not migrate Fish voice settings: {type(exc).__name__}.")
            success = False
    return success


def perform_update() -> int:
    try:
        resumed = resume_interrupted_update()  # a half-applied update is finished first (audit #29)
    except OSError as exc:
        resumed = -1
        report(f"Nu am putut termina actualizarea întreruptă: {exc}")
    translator_weight = 5 if (ROOT / "models" / "nllb-200-600M-ct2-int8" / "model.bin").is_file() else 70
    plan = [("check", 2), ("download", 8), ("apply", 3), ("libs", 25), ("gguf", 8), ("ocr", 4),
            ("translator", translator_weight), ("cleanup", 2)]
    ui_emit(t="plan", mode="update", version=_local_version(), steps=[{"id": i, "w": w} for i, w in plan])
    report("=== Lux AI | Actualizare automată din GitHub ===",
           "=== Lux AI | Автоматическое обновление с GitHub ===", "=== Lux AI | Automatic update from GitHub ===")
    report(f"Repository: https://github.com/{OWNER}/{REPO}")
    ui_step("check", "active")
    ui_detail("Închid Jarvis, dacă e deschis", "Закрываю Jarvis, если он открыт", "Closing Jarvis if it is open")
    close_jarvis()
    ui_detail("Întreb GitHub de ultima versiune", "Спрашиваю у GitHub последнюю версию", "Asking GitHub for the latest version")
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
        if PENDING_FILE.exists() or resumed < 0 or _journal_file().exists():
            # The last update was interrupted between files (or its journal cannot be confirmed, audit 3 #1):
            # install everything again; the new transaction replaces the old journal.
            current_sha = ""
            report("Actualizarea anterioară a fost întreruptă — reinstalez toate fișierele.",
                   "Прошлое обновление было прервано — устанавливаю все файлы заново.",
                   "The previous update was interrupted — installing all files again.")
        if not isinstance(current_sha, str) or len(current_sha) != 40 or any(c not in "0123456789abcdef" for c in current_sha):
            current_sha = ""
        report(f"Commit instalat: {current_sha[:12] if current_sha else 'necunoscut'}",
               f"Установленный коммит: {current_sha[:12] if current_sha else 'неизвестен'}",
               f"Installed commit: {current_sha[:12] if current_sha else 'unknown'}")
        report(f"Commit GitHub:   {latest_sha[:12]}", f"Коммит на GitHub: {latest_sha[:12]}", f"GitHub commit: {latest_sha[:12]}")
        remote = _remote_version(latest_sha)
        if remote:
            ui_emit(t="plan", version=remote, steps=[])
        ui_step("check", "done")
        if current_sha == latest_sha:
            report("Lux AI este deja la zi. Verific si bibliotecile instalate...",
                   "Lux AI уже последней версии. Проверяю установленные библиотеки…",
                   "Lux AI is up to date. Checking the installed libraries…")
            ui_step("download", "skip")
            ui_step("apply", "skip")
            packages = snapshot_packages()
            if run_step("libs", upgrade_dependencies):
                record_requirements()
            else:
                restore_packages(packages)  # the environment goes back exactly as it was (audit #7)
                ui_finish(False, "Bibliotecile nu s-au putut verifica. Rulează install_windows.bat.",
                          "Не удалось проверить библиотеки. Запустите install_windows.bat.",
                          "The libraries could not be checked. Run install_windows.bat.")
                return 1
            run_step("gguf", ensure_local_ai_backend)
            run_step("ocr", ensure_ocr)
            run_step("translator", ensure_offline_translator)
            run_step("cleanup", lambda: (cleanup_development_files(), cleanup_legacy_backups(),
                                         cleanup_retired_fish_local()) and True)
            ui_finish(True, "Jarvis e deja la ultima versiune — am verificat bibliotecile și modelele.",
                      "Jarvis уже последней версии — проверил библиотеки и модели.",
                      "Jarvis is already the latest version — libraries and models checked.")
            return 0
    except Exception as e:
        ui_step("check", "fail")
        report(f"Nu pot verifica GitHub: {e}", f"Не могу проверить GitHub: {e}", f"Cannot reach GitHub: {e}")
        ui_finish(False, f"Nu pot verifica GitHub: {e}. Verifică internetul.",
                  f"Не могу связаться с GitHub: {e}. Проверьте интернет.", f"Cannot reach GitHub: {e}. Check the internet.")
        return 1

    # Update proceeds automatically without an interactive confirmation.
    report("Actualizarea pornește automat. Recuperarea în caz de eroare folosește doar fișiere temporare.")

    with tempfile.TemporaryDirectory(prefix="luxai_update_") as temp:
        tempdir = Path(temp)
        archive = tempdir / "source.zip"
        extracted = tempdir / "extracted"
        extracted.mkdir()
        try:
            # GitHub's archive endpoint works without publishing a Release.
            ui_step("download", "active")
            ui_detail("Arhiva programului de pe GitHub", "Архив программы с GitHub", "The program archive from GitHub")
            global _SHOW_BYTES
            _SHOW_BYTES = True
            try:
                download(f"{API}/zipball/{latest_sha}", archive)
            finally:
                _SHOW_BYTES = False
            ui_step("download", "done")
            ui_step("apply", "active")
            ui_detail("Despachetez și verific fișierele", "Распаковываю и проверяю файлы", "Unpacking and checking the files")
            safe_extract(archive, extracted)

            roots = [p for p in extracted.iterdir() if p.is_dir()]
            if len(roots) != 1:
                raise RuntimeError("Structura arhivei GitHub nu este cea așteptată.")
            source = roots[0]
            signed_version = verify_release(source)  # nothing is applied from an unsigned or changed archive
            if _older_version(signed_version, _local_version()):
                raise RuntimeError(f"Refuz o versiune mai veche ({signed_version}) decât cea instalată.")
            validate_staged_source(source)
            # Validate requirements from the downloaded copy, BEFORE backup
            # and BEFORE replacing anything in the user's installation.
            validate_staged_requirements(source)

            files = []
            for src in source.rglob("*"):
                rel = src.relative_to(source)
                if is_preserved(rel) or is_development_file(rel):
                    continue
                if src.is_file():
                    files.append((src, rel))
            if not files:
                raise RuntimeError("Nu am găsit fișiere de proiect pentru actualizare.")

            report(f"Aplic {len(files)} fișiere...", f"Применяю файлов: {len(files)}…", f"Applying {len(files)} files…")
            ui_detail(f"Aplic {len(files)} fișiere", f"Применяю файлов: {len(files)}", f"Applying {len(files)} files")
            packages = snapshot_packages()
            dropped = dropped_files(_previous_file_hashes(), [rel for _src, rel in files])
            # A durable mark: if the PC loses power between two files, the next start says so and the
            # next update re-applies everything instead of trusting the old state (audit #29).
            write_pending(latest_sha)
            libraries_touched = False
            try:
                with file_transaction(files, remove=dropped):
                    ui_step("apply", "done")
                    libraries_touched = True
                    if not run_step("libs", upgrade_dependencies):
                        ui_step("libs", "fail")
                        raise RuntimeError("Actualizarea bibliotecilor a eșuat. Codul anterior se restaurează.")

                    # Optional parts: failures warn but never undo the code update.
                    run_step("gguf", ensure_local_ai_backend)
                    run_step("ocr", ensure_ocr)
                    run_step("translator", ensure_offline_translator)

                    write_update_state(latest_sha, files)
            except Exception as failure:
                # Any failure after the library step (state file included) brings the old code back,
                # so the old libraries must come back with it (audit 2 #4).
                if libraries_touched and packages:
                    restored = restore_packages(packages)
                    raise RuntimeError(
                        f"{failure} "
                        + ("Bibliotecile au revenit la versiunile anterioare." if restored else
                           "Bibliotecile nu au putut reveni singure — rulează install_windows.bat.")
                    ) from failure
                raise
            clear_pending()
            report("Actualizare instalată cu succes.", "Обновление установлено.", "Update installed.")
            run_step("cleanup", lambda: (cleanup_development_files(), cleanup_legacy_backups(),
                                         cleanup_retired_fish_local()) and True)
            report("Nu păstrez backupuri permanente ale fișierelor programului.",
                   "Постоянные резервные копии файлов программы не хранятся.", "No permanent backups of program files are kept.")
            report("Modelele personale si config.json au fost pastrate, cu exceptia Fish S2 local.",
                   "Личные модели и config.json сохранены (кроме локального Fish S2).",
                   "Personal models and config.json were kept (except local Fish S2).")
            report("Pornește Lux AI cu run_windows.bat.", "Запустите Lux AI через run_windows.bat.", "Start Lux AI with run_windows.bat.")
            version = _local_version()
            ui_finish(True, f"Jarvis {version} e instalat. Setările și modelele tale au rămas neschimbate.",
                      f"Jarvis {version} установлен. Ваши настройки и модели не тронуты.",
                      f"Jarvis {version} is installed. Your settings and models were kept.")
            return 0
        except Exception as e:
            report(f"Actualizarea a eșuat: {e}", f"Обновление не удалось: {e}", f"The update failed: {e}")
            report("Datele personale au fost păstrate. Verifică mesajele de restaurare de mai sus.",
                   "Личные данные сохранены. Смотрите сообщения о восстановлении выше.",
                   "Personal data was kept. See the restore messages above.")
            if "Restaurare incompletă" in str(e):
                # Say what is true: the old files are NOT all back (audit #30).
                ui_finish(False, f"{e}\nRestaurarea NU este completă. Nu porni Jarvis; rulează din nou Update.bat.",
                          f"{e}\nВосстановление НЕ завершено. Не запускайте Jarvis; запустите Update.bat ещё раз.",
                          f"{e}\nThe restore is NOT complete. Do not start Jarvis; run Update.bat again.")
            else:
                clear_pending()
                ui_finish(False, f"{e}\nFișierele anterioare au fost restaurate, datele tale sunt neatinse.",
                          f"{e}\nПрежние файлы восстановлены, ваши данные не тронуты.",
                          f"{e}\nThe previous files were restored; your data is untouched.")
            return 1


def main() -> int:
    start_ui("update")
    try:
        with updater_lock():
            return perform_update()
    except (OSError, RuntimeError) as exc:
        report(f"Actualizarea nu poate porni: {exc}", f"Обновление не может начаться: {exc}", f"The update cannot start: {exc}")
        ui_finish(False, f"Actualizarea nu poate porni: {exc}", f"Обновление не может начаться: {exc}",
                  f"The update cannot start: {exc}")
        return 1


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["--clean-installation"]:
            cleanup_development_files()
            raise SystemExit(0)
        if sys.argv[1:] == ["--resume"]:
            # Same OS lock as the updater (audit 2 #1): never moves files while an update runs.
            # 0 = done/nothing to do, 2 = an update is running right now, 1 = could not finish.
            try:
                with updater_lock():
                    done = resume_interrupted_update()
                    raise SystemExit(1 if done < 0 or _journal_file().exists() else 0)
            except RuntimeError:
                raise SystemExit(2)
            except OSError:
                raise SystemExit(1)
        if sys.argv[1:] == ["--remove-fish-local"]:
            raise SystemExit(0 if cleanup_retired_fish_local() else 1)
        raise SystemExit(main())
    except KeyboardInterrupt:
        report("\nActualizare anulată.")
        raise SystemExit(130)
