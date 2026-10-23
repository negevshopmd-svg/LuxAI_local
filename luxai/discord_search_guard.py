"""Screenshot-gated Discord Quick Switcher: never type into an unverified field."""
from __future__ import annotations

import time


def verified_discord_search(planner, hwnd: int, query: str, *, replace=False,
                            cancelled=None):
    """Focus only the visible Ctrl+K *overlay* textbox before typing.

    A failed Ctrl+K used to type '@someone' in the active DM composer.
    Only operate after a fresh screenshot identifies the modal search field
    in the main (not bottom composer) region. No Enter and no messages.
    """
    from luxai.discord_research import focus_discord
    from luxai.visual_click import capture_window, find_visual_target, click_visual_target
    from luxai.desktop_actions import _type_unicode_windows
    import pyautogui

    def check():
        if cancelled is not None and cancelled():
            raise RuntimeError("Discord search cancelled")
    if not query or len(query) > 64 or any(ord(x) < 32 for x in query):
        raise ValueError("Invalid Discord search term")
    check()
    focus_discord(hwnd)
    if not replace:
        pyautogui.hotkey("ctrl", "k", interval=0.07)
        time.sleep(0.35)
    check()
    shot = capture_window(hwnd)
    point = find_visual_target(
        planner,
        "STRICT PRECONDITION: the Discord Ctrl+K QUICK SWITCHER MODAL "
        "must be OPEN OVER THE main chat, with its floating input and "
        "the quick switcher search/results panel visibly present. "
        "Locate ONLY the center of the floating search INPUT inside that "
        "Quick Switcher overlay. Never return the bottom chat message "
        "COMPOSER, Discord left sidebar search, or any chat textbox. "
        "If the popup is absent, hidden or uncertain return found:false. "
        "Do not infer from what was previously clicked.",
        shot,
    )
    # Even a misleading model-produced coordinate must not be able to
    # select the bottom DM editor. An overlay search must be above it.
    if point[1] > shot.top + int(shot.height * 0.72):
        raise ValueError("Discord search overlay not verified; no text typed")
    if point[0] < shot.left + int(shot.width * 0.16):
        raise ValueError("Discord search result location is not an overlay input")
    check()
    click_visual_target(shot, point, 1)
    check()
    if replace:
        pyautogui.hotkey("ctrl", "a", interval=0.05)
    _type_unicode_windows(query)
    check()
    time.sleep(0.60)
    return capture_window(hwnd)
