"""0.4.1f Layout-independent shortcuts: Ctrl+C works with a Russian layout."""
import sys
import unittest
from unittest import mock

from luxai import keys


class KeysTests(unittest.TestCase):
    def test_virtual_key_codes(self):
        self.assertEqual(keys.vk_code("ctrl"), 0x11)
        self.assertEqual(keys.vk_code("c"), 0x43)
        self.assertEqual(keys.vk_code("F8"), 0x77)
        self.assertEqual(keys.vk_code("end"), 0x23)
        with self.assertRaises(ValueError):
            keys.vk_code("ё")

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_press_uses_virtual_keys_not_the_layout(self):
        events = []
        with mock.patch("ctypes.windll.user32.keybd_event", side_effect=lambda vk, scan, flags, extra: events.append((vk, flags))):
            keys.press("ctrl", "c", interval=0)
        self.assertEqual(events, [(0x11, 0), (0x43, 0), (0x43, keys.KEYUP), (0x11, keys.KEYUP)])

    def test_selection_copy_defaults_to_layout_independent_keys(self):
        import inspect
        from luxai import selection
        source = inspect.getsource(selection.copy_selected_text)
        self.assertIn("luxai.keys", source)
        self.assertNotIn("pyautogui.hotkey", source)

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_patched_pyautogui_routes_letters_through_virtual_keys(self):
        import pyautogui
        original = pyautogui.hotkey, pyautogui.press
        self.addCleanup(lambda: (setattr(pyautogui, "hotkey", original[0]), setattr(pyautogui, "press", original[1]),
                                 setattr(keys, "_PATCHED", False)))
        keys._PATCHED = False
        with mock.patch.object(keys, "press") as press:
            keys.patch_pyautogui()
            pyautogui.hotkey("ctrl", "s", interval=0.05)
            press.assert_called_once_with("ctrl", "s", interval=0.05)


if __name__ == "__main__":
    unittest.main()
