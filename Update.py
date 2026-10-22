#!/usr/bin/env python3
"""Lux AI updater for public GitHub Releases.

Expected release asset: LuxAI_local-update.zip
The ZIP should contain the updated project files at its root (not an extra wrapper folder).
"""
from __future__ import annotations
import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

OWNER = "negevshopmd-svg"
REPO = "LuxAI_local"
ASSET_NAME = "LuxAI_local-update.zip"
API_URL = f"https://api.github.com/repos/{OWNER}/{REPO}/releases/latest"
ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / ".luxai_update_state.json"
BACKUP_ROOT = ROOT / "backups"
# User data and large local models should not be overwritten by application updates.
PRESERVE_NAMES = {
    "settings.json", ".env", "models", "model", "downloads", "logs",
    "backups", ".git", "__pycache__", ".venv", "venv"
}
MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024  # 500 MB safety limit

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
                raise RuntimeError("Arhiva depășește limita de 500 MB.")
            out.write(chunk)

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"version": "0.0.0"}

def safe_extract(zip_path: Path, destination: Path) -> None:
    base = destination.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            p = Path(name)
            if p.is_absolute() or ".." in p.parts:
                raise RuntimeError(f"Cale nesigură în arhivă: {name}")
            target = (destination / p).resolve()
            if target != base and base not in target.parents:
                raise RuntimeError(f"Cale în afara proiectului: {name}")
        zf.extractall(destination)

def main() -> int:
    print("=== Lux AI | GitHub Updater ===")
    print(f"Repository: {OWNER}/{REPO}")
    try:
        release = request_json(API_URL)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print("Nu există încă un Release publicat. Creează primul Release cu asset-ul " + ASSET_NAME)
        else:
            print(f"Eroare GitHub HTTP: {e.code}")
        return 1
    except Exception as e:
        print(f"Nu pot verifica GitHub: {e}")
        return 1

    if release.get("draft") or release.get("prerelease"):
        print("Ultimul Release este draft/prerelease; nu îl instalez.")
        return 1

    latest = release.get("tag_name", "").strip()
    current = load_state().get("version", "0.0.0")
    print(f"Versiune instalată: {current}")
    print(f"Versiune GitHub:    {latest}")
    if not latest:
        print("GitHub nu a returnat tag_name.")
        return 1
    if latest == current:
        print("Lux AI este deja la zi.")
        return 0

    assets = release.get("assets", [])
    asset = next((a for a in assets if a.get("name") == ASSET_NAME), None)
    if not asset:
        print(f"Release-ul nu conține asset-ul necesar: {ASSET_NAME}")
        print("Deschide:", release.get("html_url", ""))
        return 1

    answer = input(f"Instalez {latest}? Backup-ul va fi salvat în backups. [d/N]: ").strip().lower()
    if answer not in ("d", "da", "y", "yes"):
        print("Anulat.")
        return 0

    with tempfile.TemporaryDirectory(prefix="luxai_update_") as td:
        td_path = Path(td)
        archive = td_path / ASSET_NAME
        extracted = td_path / "extracted"
        extracted.mkdir()
        try:
            print("Descarc actualizarea...")
            download(asset["browser_download_url"], archive)
            print("Verific arhiva...")
            with zipfile.ZipFile(archive) as zf:
                bad = zf.testzip()
                if bad:
                    raise RuntimeError(f"Arhivă ZIP deteriorată: {bad}")
            safe_extract(archive, extracted)

            # Reject archives that are empty and detect the common nested-folder mistake.
            incoming = list(extracted.iterdir())
            if not incoming:
                raise RuntimeError("Arhiva este goală.")
            if len(incoming) == 1 and incoming[0].is_dir() and not any(
                (incoming[0] / n).exists() for n in ("main.py", "app.py", "Update.py")
            ):
                print("Atenție: arhiva pare să conțină un folder în plus. Verifică structura ZIP-ului.")
                source = incoming[0]
            else:
                source = extracted

            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = BACKUP_ROOT / f"{stamp}-{current}"
            backup.mkdir(parents=True, exist_ok=True)
            # Copy files that will be overwritten, then apply incoming files.
            for src in source.rglob("*"):
                rel = src.relative_to(source)
                if any(part in PRESERVE_NAMES for part in rel.parts):
                    continue
                dest = ROOT / rel
                if src.is_file() and dest.exists() and dest.is_file():
                    bdest = backup / rel
                    bdest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dest, bdest)

            for src in source.rglob("*"):
                rel = src.relative_to(source)
                if any(part in PRESERVE_NAMES for part in rel.parts):
                    continue
                dest = ROOT / rel
                if src.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                elif src.is_file():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)

            STATE_FILE.write_text(json.dumps({"version": latest}, indent=2), encoding="utf-8")
            print(f"Actualizare instalată: {latest}")
            print(f"Backup: {backup}")
            print("Pornește Lux AI din nou.")
            return 0
        except Exception as e:
            print(f"Actualizarea a eșuat: {e}")
            print("Fișierele deja existente copiate în backup se află în:", BACKUP_ROOT)
            return 1

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nAnulat de utilizator.")
        raise SystemExit(130)
