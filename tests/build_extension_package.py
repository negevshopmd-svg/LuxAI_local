"""Build the Chrome Web Store package of the Jarvis browser extension (developer tool, stays on GitHub).

    python tests/build_extension_package.py      -> dist/jarvis-film-captions-<version>.zip

Upload that ZIP at https://chrome.google.com/webstore/devconsole (a Google developer account is needed:
a one-time fee). Listing texts and the privacy answers are in PROJECT_HANDOFF.md («Publishing the browser
extension»). After it is published, put its Web Store ID in luxai/ui_browser_extension.py (STORE_ID) and
Jarvis opens the store page instead of the developer-mode steps.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "browser_extension"
FILES = ("manifest.json", "background.js", "content.js", "icon128.png")


def main() -> int:
    manifest = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))
    out = ROOT / "dist" / f"jarvis-film-captions-{manifest['version']}.zip"
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as package:
        for name in FILES:
            package.write(SOURCE / name, name)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
