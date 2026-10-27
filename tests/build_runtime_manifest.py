"""Refresh known source-only file hashes before publishing an update.

Run from a maintainer checkout with ``python tests/build_runtime_manifest.py``.
Catalog the published main ancestry and the exact current working source, so
new installations and older ZIP installations can trim only unchanged files.
"""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import Update as updater


def git(*arguments, data=None):
    return subprocess.check_output(["git", *arguments], cwd=ROOT, input=data)


def main():
    blobs = defaultdict(set)
    for commit in git("rev-list", "origin/main").decode("ascii").splitlines():
        for entry in git("ls-tree", "-rz", "--full-tree", commit).split(b"\0"):
            if not entry:
                continue
            metadata, raw_name = entry.split(b"\t", 1)
            name = raw_name.decode("utf-8")
            path = Path(name)
            if updater.is_development_file(path) and not updater.is_preserved(path):
                mode, kind, blob = metadata.split()
                if kind == b"blob" and mode in {b"100644", b"100755"}:
                    blobs[name].add(blob)

    contents = {}
    object_ids = sorted({blob for versions in blobs.values() for blob in versions})
    batch = git("cat-file", "--batch", data=b"\n".join(object_ids) + b"\n")
    offset = 0
    for blob in object_ids:
        end = batch.index(b"\n", offset)
        length = int(batch[offset:end].split()[-1])
        offset = end + 1
        contents[blob] = batch[offset:offset + length]
        offset += length + 1

    hashes = defaultdict(set)

    def record(name, content):
        hashes[name].add(hashlib.sha256(content).hexdigest())
        if b"\0" not in content:
            # ZIPs use repository bytes. Also recognize untouched source copied
            # with Windows text line endings; any other edit remains different.
            windows = content.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            hashes[name].add(hashlib.sha256(windows).hexdigest())

    for name, versions in blobs.items():
        for blob in versions:
            record(name, contents[blob])
    for raw_name in git("ls-files", "--cached", "--others", "--exclude-standard", "-z").split(b"\0"):
        if not raw_name:
            continue
        name = raw_name.decode("utf-8")
        path = ROOT / name
        if (updater.is_development_file(Path(name)) and not updater.is_preserved(Path(name))
                and path.is_file() and not path.is_symlink()):
            record(name, path.read_bytes())
    manifest = {"format": 1, "files": {name: sorted(values) for name, values in sorted(hashes.items())}}
    target = ROOT / updater.CLEANUP_MANIFEST
    target.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Recorded {len(hashes)} source-only paths in {target.name}.")


if __name__ == "__main__":
    main()
