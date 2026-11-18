"""Build ``.venv/Scripts/Jarvis.exe`` so Windows shows "Jarvis" with its icon.

Task Manager names a process after its executable's description and shows
that executable's icon. Jarvis ran inside ``pythonw.exe`` ("Python", no
icon). Jarvis.exe is a copy of the same Python interpreter with:

* description and product name "Jarvis" (same length as "Python", so the
  version resource keeps its exact layout);
* the Jarvis icon.

It sits in the venv's Scripts folder, so Python finds ``pyvenv.cfg`` one level
up and uses the same packages. The DLLs the interpreter needs are copied next
to it. Every build is test-started; if anything fails, nothing changes and
run_windows.bat keeps using pythonw.exe. Run: ``python -m luxai.jarvis_exe``.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

BUILD = "2"
ROOT = Path(__file__).resolve().parents[1]
ICON_SVG = ROOT / "luxai" / "assets" / "icons" / "jarvis.svg"
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
RUNTIME_DLLS = ("python3.dll", "python3*.dll", "vcruntime140.dll", "vcruntime140_1.dll")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def base_python(venv: Path) -> Path | None:
    config = venv / "pyvenv.cfg"
    if not config.is_file():
        return None
    for line in config.read_text(encoding="utf-8", errors="replace").splitlines():
        key, _, value = line.partition("=")
        if key.strip().casefold() == "home" and value.strip():
            return Path(value.strip())
    return None


def rename_version(blob: bytes, old: str = "Python", new: str = "Jarvis") -> bytes:
    """Swap the FileDescription / ProductName values (same length → same layout)."""
    assert len(old) == len(new)
    data = bytearray(blob)
    for key in ("FileDescription", "ProductName"):
        marker = key.encode("utf-16-le")
        at = data.find(marker)
        if at < 0:
            continue
        value = old.encode("utf-16-le") + b"\0\0"
        found = data.find(value, at + len(marker), at + len(marker) + 48)
        if found >= 0:
            data[found:found + len(old) * 2] = new.encode("utf-16-le")
    return bytes(data)


def icon_images(svg: Path = ICON_SVG) -> list[tuple[int, bytes]]:
    """(size, PNG bytes) of the Jarvis icon, rendered locally with Qt."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841 - needed for painting
    renderer = QSvgRenderer(str(svg))
    images = []
    for size in ICON_SIZES:
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter)
        painter.end()
        array = QByteArray()
        buffer = QBuffer(array)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        images.append((size, bytes(array)))
    return images


def group_icon(images: list[tuple[int, bytes]], first_id: int = 1) -> bytes:
    """RT_GROUP_ICON directory pointing at RT_ICON ids first_id…"""
    header = struct.pack("<HHH", 0, 1, len(images))
    entries = b""
    for index, (size, png) in enumerate(images):
        side = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHIH", side, side, 0, 0, 1, 32, len(png), first_id + index)
    return header + entries


def patch_resources(exe: Path, source: Path, images) -> None:
    import win32api
    import win32con
    module = win32api.LoadLibraryEx(str(source), 0, win32con.LOAD_LIBRARY_AS_DATAFILE)
    try:
        old = {}
        for kind in (win32con.RT_GROUP_ICON, win32con.RT_ICON):
            try:
                names = win32api.EnumResourceNames(module, kind)
            except win32api.error:
                names = []
            old[kind] = [(name, win32api.EnumResourceLanguages(module, kind, name)) for name in names]
        version = win32api.LoadResource(module, win32con.RT_VERSION, 1)
        version_lang = win32api.EnumResourceLanguages(module, win32con.RT_VERSION, 1)[0]
    finally:
        win32api.FreeLibrary(module)
    handle = win32api.BeginUpdateResource(str(exe), False)
    try:
        for kind, entries in old.items():
            for name, languages in entries:
                for language in languages:
                    win32api.UpdateResource(handle, kind, name, None, language)
        for index, (_size, png) in enumerate(images):
            win32api.UpdateResource(handle, win32con.RT_ICON, index + 1, png, 1033)
        win32api.UpdateResource(handle, win32con.RT_GROUP_ICON, 1, group_icon(images), 1033)
        win32api.UpdateResource(handle, win32con.RT_VERSION, 1, rename_version(version), version_lang)
    except Exception:
        win32api.EndUpdateResource(handle, True)  # discard
        raise
    win32api.EndUpdateResource(handle, False)


def works(exe: Path, venv: Path) -> bool:
    """Start the new exe once: it must run Python with this venv's packages."""
    out = Path(tempfile.mkdtemp()) / "check.txt"
    code = ("import sys, PySide6; open(sys.argv[1], 'w', encoding='utf-8').write(sys.prefix)")
    try:
        subprocess.run([str(exe), "-c", code, str(out)], timeout=60, check=False,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        prefix = out.read_text(encoding="utf-8") if out.is_file() else ""
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        shutil.rmtree(out.parent, ignore_errors=True)
    return bool(prefix) and Path(prefix).resolve() == venv.resolve()


def ensure_jarvis_exe(root: Path = ROOT, *, log=print) -> Path | None:
    if sys.platform != "win32":
        return None
    venv = root / ".venv"
    scripts = venv / "Scripts"
    home = base_python(venv)
    source = home / "pythonw.exe" if home else None
    if source is None or not source.is_file() or not scripts.is_dir():
        log("Jarvis.exe: base Python not found; keeping pythonw.exe")
        return None
    target = scripts / "Jarvis.exe"
    stamp = scripts / "Jarvis.exe.stamp"
    key = f"{BUILD}|{_digest(source)}|{_digest(ICON_SVG)}"
    if target.is_file() and stamp.is_file() and stamp.read_text(encoding="utf-8").strip() == key:
        return target
    for pattern in RUNTIME_DLLS:
        for dll in home.glob(pattern):
            copy = scripts / dll.name
            if not copy.is_file() or copy.stat().st_size != dll.stat().st_size:
                shutil.copy2(dll, copy)
    temp = scripts / "Jarvis.new.exe"
    try:
        shutil.copy2(source, temp)
        patch_resources(temp, source, icon_images())
        if not works(temp, venv):
            log("Jarvis.exe: test start failed; keeping pythonw.exe")
            temp.unlink(missing_ok=True)
            return target if target.is_file() and stamp.is_file() else None
        try:
            os.replace(temp, target)
        except PermissionError:
            log("Jarvis.exe is running; the new one will be used next time")
            return target
        stamp.write_text(key, encoding="utf-8")
        log("Jarvis.exe ready")
        return target
    except Exception as error:
        temp.unlink(missing_ok=True)
        log(f"Jarvis.exe: {type(error).__name__}: {error}; keeping pythonw.exe")
        return target if target.is_file() and stamp.is_file() else None


if __name__ == "__main__":
    sys.exit(0 if ensure_jarvis_exe() else 1)
