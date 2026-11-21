"""0.4.3q: no extension error in sandboxed frames.

Reported (Chrome's extension errors page, on chatgpt.com): «Failed to execute 'postMessage' on 'DOMWindow': The target
origin provided ('https://cdn.platform.openai.com') does not match the recipient window's origin ('null')». A
sandboxed iframe has the real origin "null"; the extension posted to the frame's address instead.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("node"), "Node.js runs the extension's content script")
class SandboxFrameTests(unittest.TestCase):
    def test_a_sandboxed_frame_raises_no_error_and_posts_nothing(self):
        result = subprocess.run(["node", str(ROOT / "tests" / "js" / "sandbox_frame_harness.js")],
                                capture_output=True, text=True, timeout=30, check=True)
        outcome = json.loads(result.stdout)
        self.assertEqual(outcome["errors"], [])
        self.assertEqual(outcome["posted"], 0)


class ContractTests(unittest.TestCase):
    def test_messages_use_the_real_origin(self):
        content = (ROOT / "browser_extension" / "content.js").read_text(encoding="utf-8")
        page = (ROOT / "browser_extension" / "youtube_audio.js").read_text(encoding="utf-8")
        for source in (content, page):
            self.assertNotIn("location.origin", source)
        self.assertIn("const PAGE_ORIGIN = self.origin;", content)
        self.assertIn('if (!PAGE_ORIGIN || PAGE_ORIGIN === "null") return;', content)
        self.assertEqual(content.count("window.postMessage("), 1)  # only through toPage()
        self.assertIn('if (self.origin === "null") return;', page)


if __name__ == "__main__":
    unittest.main()
