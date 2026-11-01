"""One-time, opt-in Fish S2 local asset installation (no API key required).

Files live in models/fishaudio and are retained on updates. The native CPU DLL
comes from a pinned GitHub Release built by this repository's Windows CI.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

from luxai.fish_local import FISH_DIR, MODEL_NAME, RUNTIME_DIR

MODEL_BASE = "https://huggingface.co/rodrigomt/s2-pro-gguf/resolve/main/"
RUNTIME_NAME = "fish-s2-cpu-win-x64-2c332619-v1.zip"
RUNTIME_URL = ("https://github.com/negevshopmd-svg/LuxAI_local/releases/download/"
               "fish-s2-runtime-v1/" + RUNTIME_NAME)
MODEL_LIMIT = 5_000_000_000
TOKENIZER_LIMIT = 35_000_000
RUNTIME_LIMIT = 140_000_000


class InstallError(RuntimeError):
    pass


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        from urllib.parse import urlsplit
        host = (urlsplit(newurl).hostname or "").lower()
        allowed = ("huggingface.co", "hf.co", "github.com", "release-assets.githubusercontent.com",
                   "objects.githubusercontent.com", "cas-bridge.xethub.hf.co",
                   "cas-server.xethub.hf.co", "cdn-lfs.hf.co", "cdn-lfs-us-1.hf.co")
        if not (newurl.startswith("https://") and (host in allowed or
                host.endswith(".xethub.hf.co") or host.endswith(".huggingface.co"))):
            raise InstallError("Unexpected download redirect host")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url: str, dest: Path, limit: int, minimum: int = 1):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and minimum <= dest.stat().st_size <= limit:
        return dest
    part = dest.with_name(dest.name + ".partial")
    size = part.stat().st_size if part.is_file() else 0
    if size > limit:
        part.unlink()
        size = 0
    request = urllib.request.Request(url, headers={
        "User-Agent": "LuxAI-FishS2-Local/1.0",
        **({"Range": f"bytes={size}-"} if size else {}),
    })
    opener = urllib.request.build_opener(SafeRedirect())
    started = time.monotonic()
    try:
        with opener.open(request, timeout=45) as response:
            if size and response.status != 206:
                size = 0  # Host does not support Range; restart rather than append.
            mode = "ab" if size else "wb"
            total = size
            with part.open(mode) as output:
                while True:
                    data = response.read(1024 * 1024)
                    if not data:
                        break
                    total += len(data)
                    if total > limit:
                        raise InstallError("Download exceeds configured size limit")
                    output.write(data)
                    if time.monotonic() - started > 10:
                        print(f"{dest.name}: {total / (1024 ** 2):.0f} MiB", flush=True)
                        started = time.monotonic()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise InstallError("Download interrupted; rerun to resume") from None
    if not minimum <= part.stat().st_size <= limit:
        raise InstallError("Downloaded file size is incomplete")
    part.replace(dest)
    return dest


def install_model():
    FISH_DIR.mkdir(parents=True, exist_ok=True)
    model = download(MODEL_BASE + MODEL_NAME, FISH_DIR / MODEL_NAME,
                     MODEL_LIMIT, minimum=3_000_000_000)
    with model.open("rb") as f:
        if f.read(4) != b"GGUF":
            model.unlink(missing_ok=True)
            raise InstallError("Downloaded model does not have GGUF header")
    tok = download(MODEL_BASE + "tokenizer.json", FISH_DIR / "tokenizer.json",
                   TOKENIZER_LIMIT, minimum=1_000_000)
    try:
        with tok.open("rb") as f:
            if not isinstance(json.load(f), dict):
                raise ValueError()
    except (OSError, ValueError, json.JSONDecodeError):
        tok.unlink(missing_ok=True)
        raise InstallError("Tokenizer is invalid") from None
    print("Fish S2 model and tokenizer installed in models/fishaudio", flush=True)


def install_runtime():
    if sys.platform != "win32":
        raise InstallError("The precompiled runtime is for 64-bit Windows")
    FISH_DIR.mkdir(parents=True, exist_ok=True)
    if (RUNTIME_DIR / "cpu-baseline" / "s2.dll").is_file():
        from luxai.fish_local import choose_runtime, FishLocalError
        try:
            choose_runtime()
            print("Fish native runtime is already present", flush=True)
            return
        except FishLocalError:
            print("Outdated or invalid Fish runtime; replacing it.", flush=True)
    with tempfile.TemporaryDirectory(prefix="fish-s2-package-") as tmp:
        package = download(RUNTIME_URL, Path(tmp) / RUNTIME_NAME,
                           RUNTIME_LIMIT, minimum=100_000)
        with zipfile.ZipFile(package) as archive:
            allowed = {"manifest.json", "cpu-baseline/s2.dll", "cpu-avx2/s2.dll",
                       "LICENSE.txt", "GGML-LICENSE.txt", "NOTICE.txt", "BUILD-PATCHES.txt"}
            if set(archive.namelist()) != allowed:
                raise InstallError("Unexpected native runtime archive contents")
            manifest = json.loads(archive.read("manifest.json"))
            if (manifest.get("engine"), manifest.get("target"), manifest.get("source_commit")) != (
                    "s2.cpp", "windows-x64", "2c33261938da1a41d713768b1b391b4d368d7d2c"):
                raise InstallError("Native runtime provenance mismatch")
            for name in allowed - {"manifest.json"}:
                entry = archive.getinfo(name)
                if entry.file_size > 80_000_000:
                    raise InstallError("Oversized runtime archive entry")
                data = archive.read(name)
                expected = manifest["files"][name]
                if hashlib.sha256(data).hexdigest() != expected["sha256"] or len(data) != expected["size"]:
                    raise InstallError("Runtime checksum mismatch")
            for name in allowed:
                destination = RUNTIME_DIR / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                # All filenames are from a fixed allowlist; no ZIP path traversal.
                destination.write_bytes(archive.read(name))
    print("Fish native CPU runtime installed", flush=True)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-only", action="store_true")
    parser.add_argument("--runtime-only", action="store_true")
    args = parser.parse_args()
    try:
        # Verify the small runtime download first; do not fetch 3.6 GB of
        # weights if a GitHub Release has not yet been published.
        if not args.model_only:
            install_runtime()
        if not args.runtime_only:
            install_model()
        print("Ready. Select Fish S2 Local in Jarvis Settings.", flush=True)
        return 0
    except (InstallError, OSError, zipfile.BadZipFile, KeyError) as exc:
        print(f"Fish local installation failed: {type(exc).__name__}: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
