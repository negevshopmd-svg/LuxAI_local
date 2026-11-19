"""Release tool (maintainer only, never installed): sign the files of the next commit.

    python tests/sign_release.py --init    # once: create the key (private part stays on this PC)
    python tests/sign_release.py           # every release, after «git add -A»: writes and stages
                                           # release_manifest.json + release_manifest.sig

The private key is encrypted with Windows DPAPI for this Windows user in
%USERPROFILE%\\.luxai_release\\signing_key.bin. Keep a backup of that folder:
without it no further update can be signed for existing installations.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
import release_signature as rs  # noqa: E402

KEY_DIR = Path(os.environ.get("LUXAI_RELEASE_KEY_DIR") or Path.home() / ".luxai_release")
KEY_FILE = KEY_DIR / "signing_key.bin"


def _crypt(data: bytes, encrypt: bool) -> bytes:
    from luxai.secure_keys import _win_crypt
    return _win_crypt(data, encrypt)


def load_secret() -> bytes:
    secret = _crypt(KEY_FILE.read_bytes(), False)
    if len(secret) != 32:
        raise SystemExit("The release key file is damaged.")
    return secret


def init_key() -> None:
    if KEY_FILE.exists():
        raise SystemExit(f"A release key already exists: {KEY_FILE}")
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_bytes(32)
    KEY_FILE.write_bytes(_crypt(secret, True))
    print("public key:", rs.public_key(secret).hex())


def git(*args: str, data: bytes | None = None) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT, input=data)


def staged_files() -> dict[str, str]:
    """{path: sha256} of the files as they will be in the next commit (the git index)."""
    entries = []
    for entry in git("ls-files", "-s", "-z").split(b"\0"):
        if not entry:
            continue
        meta, raw_name = entry.split(b"\t", 1)
        mode, blob, _stage = meta.split()
        name = raw_name.decode("utf-8")
        if name in (rs.MANIFEST, rs.SIGNATURE) or mode == b"160000":
            continue
        entries.append((name, blob))
    batch = git("cat-file", "--batch", data=b"\n".join(blob for _name, blob in entries) + b"\n")
    files, offset = {}, 0
    for name, _blob in entries:
        end = batch.index(b"\n", offset)
        length = int(batch[offset:end].split()[-1])
        offset = end + 1
        files[name] = rs.file_digest(name, batch[offset:offset + length])
        offset += length + 1
    return files


def main() -> int:
    if "--init" in sys.argv:
        init_key()
        return 0
    secret = load_secret()
    public = rs.public_key(secret).hex()
    if public != rs.PUBLIC_KEY_HEX:
        raise SystemExit("This key does not match the public key built into the updater.")
    version = (ROOT / "version.txt").read_text(encoding="utf-8").strip()
    manifest = json.dumps({"format": 1, "version": version, "files": dict(sorted(staged_files().items()))},
                          indent=1, ensure_ascii=False).encode("utf-8") + b"\n"
    signature = rs.sign(secret, manifest)
    if not rs.verify(bytes.fromhex(public), manifest, signature):
        raise SystemExit("Self-check of the signature failed.")
    (ROOT / rs.MANIFEST).write_bytes(manifest)
    (ROOT / rs.SIGNATURE).write_text(signature.hex() + "\n", encoding="ascii")
    git("add", rs.MANIFEST, rs.SIGNATURE)
    print(f"signed {len(json.loads(manifest)['files'])} files of {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
