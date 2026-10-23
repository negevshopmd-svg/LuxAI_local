"""Consent-gated visual click on the actual Discord microphone control.

This narrowly scoped local workflow is deliberately independent of generic
cloud-generated macro plans, which may omit steps or misidentify the window.
"""
from __future__ import annotations


def click_discord_microphone_by_screenshot(planner, *, cancelled=None) -> str:
    """Save a Discord window screenshot and click only its verified mic button.

    The caller must first get explicit approval for sending the screenshot
    to the user's selected vision AI and for toggling the microphone state.
    A click only means an attempted toggle, not that the mic was muted.
    """
    from luxai.discord_screen_review import (
        _ensure_discord_visible, _save_capture, focus_discord,
    )
    from luxai.visual_click import (
        capture_window, find_visual_target, click_visual_target,
    )

    def check_cancel():
        if cancelled is not None and cancelled():
            raise RuntimeError("Команда отменена до нажатия кнопки.")

    check_cancel()
    hwnd = _ensure_discord_visible(cancelled=cancelled)
    check_cancel()
    focus_discord(hwnd)
    check_cancel()

    # The capture is strictly for the verified Discord process/window,
    # not the currently active Jarvis UI or an arbitrary browser.
    capture = capture_window(hwnd)
    saved = _save_capture(capture, "microphone")
    check_cancel()
    point = find_visual_target(
        planner,
        "Find the UNIQUE Discord desktop microphone MUTE/UNMUTE button "
        "within the bottom-left user controls of the app window. "
        "It usually has a microphone glyph and may be muted or unmuted. "
        "Never select microphone icons inside messages, pictures, videos, "
        "calls, browser content, other apps, or security dialogs. "
        "Return found:false if the actual Discord mic toggle cannot be "
        "identified unambiguously.",
        capture,
    )
    check_cancel()
    # Validate original window, focus, pid/title and bounds before clicking.
    click_visual_target(capture, point, 1)
    return (
        "Снимок окна Discord сохранён: " + str(saved) + ". "
        "Нажал на визуально подтверждённую кнопку микрофона Discord. "
        "Это переключатель: состояние микрофона не подтверждено. "
        "Проверьте значок микрофона в Discord."
    )
