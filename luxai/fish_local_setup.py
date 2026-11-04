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
    """Accept only official download CDNs for the original provider.

    Hugging Face serves Xet/LFS files from region-specific CDN hosts. Keep an
    explicit list instead of permitting arbitrary redirect domains or HTTP.
    Do not mix the Hugging Face and GitHub release redirect chains.
    """
    HF_HOSTS = frozenset((
        "huggingface.co", "hf.co",
        "cas-bridge.xethub.hf.co", "cas-bridge.xethub-eu.hf.co",
        "cas-server.xethub.hf.co", "cas-server.xethub-eu.hf.co",
        "transfer.xethub.hf.co", "transfer.xethub-eu.hf.co",
        "us.aws.cdn.hf.co", "us.gcp.cdn.hf.co",
        "cdn-lfs.hf.co", "cdn-lfs-us-1.hf.co", "cdn-lfs-eu-1.hf.co",
    ))
    GITHUB_HOSTS = frozenset((
        "github.com", "release-assets.githubusercontent.com",
        "objects.githubusercontent.com",
    ))

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        from urllib.parse import urlsplit

        origin = urlsplit(req.full_url)
        target = urlsplit(newurl)
        origin_host = (origin.hostname or "").lower()
        target_host = (target.hostname or "").lower()
        permitted = (self.HF_HOSTS if origin_host in self.HF_HOSTS else
                     self.GITHUB_HOSTS if origin_host in self.GITHUB_HOSTS else
                     frozenset())
        if (target.scheme.lower() != "https" or target_host not in permitted or
                target.port not in (None, 443) or
                target.username is not None or target.password is not None):
            # Only expose the hostname; presigned URLs contain private tokens.
            raise InstallError("Unexpected download redirect host: " +
                               (target_host or "(missing)"))
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


def existing_model_ready():
    """Recognize a user-provided GGUF without reading its multi-GB payload."""
    model = FISH_DIR / MODEL_NAME
    if not model.is_file() or not 3_000_000_000 <= model.stat().st_size <= MODEL_LIMIT:
        return False
    with model.open("rb") as stream:
        return stream.read(4) == b"GGUF"


def install_model():
    FISH_DIR.mkdir(parents=True, exist_ok=True)
    # Repair the small tokenizer first. Existing 3.6 GB GGUF files are reused:
    # download() returns without opening the network for an in-range file.
    tok = download(MODEL_BASE + "tokenizer.json", FISH_DIR / "tokenizer.json",
                   TOKENIZER_LIMIT, minimum=1_000_000)
    try:
        with tok.open("rb") as f:
            if not isinstance(json.load(f), dict):
                raise ValueError()
    except (OSError, ValueError, json.JSONDecodeError):
        tok.unlink(missing_ok=True)
        raise InstallError("Tokenizer is invalid") from None
    if existing_model_ready():
        print("Existing Fish GGUF detected; reusing model without downloading it", flush=True)
    else:
        model = download(MODEL_BASE + MODEL_NAME, FISH_DIR / MODEL_NAME,
                         MODEL_LIMIT, minimum=3_000_000_000)
        with model.open("rb") as f:
            if f.read(4) != b"GGUF":
                model.unlink(missing_ok=True)
                raise InstallError("Downloaded model does not have GGUF header")
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
        # If a GGUF is already present, repair the tokenizer first so a
        # missing runtime download cannot also block recovery of that asset.
        # Otherwise verify the small runtime before fetching 3.6 GB weights.
        if not args.runtime_only and existing_model_ready():
            install_model()
            if not args.model_only:
                install_runtime()
        else:
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
