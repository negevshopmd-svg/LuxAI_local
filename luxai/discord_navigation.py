"""A verified Discord user-open action, with retries after Ctrl+K overlays.

Every click follows a NEW capture and an exact header check. Search matches
are not authority to open or message someone else.
"""
from __future__ import annotations

import re
import time

from luxai.fast_intents import command_text
from luxai.discord_screen_review import (
    _ensure_discord_visible, validate_discord_review_user,
)
from luxai.discord_contact_vision import (
    locate_visible_contact, same_discord_name, search_alias,
)
from luxai.discord_research import focus_discord


def detect_discord_open_dm(text: str) -> str | None:
    phrase = command_text(text).strip().rstrip(" .!?")
    lower = phrase.casefold()
    platform = r"(?:discord|дискорд\w*|дискор\w*)"
    if not re.search(r"(?<!\w)" + platform + r"(?!\w)", lower):
        return None
    if re.search(
        r"(?:скрин|снимок|микрофон|отправ\w*|напиши|сообщени|"
        r"пересказ|содержани|информаци\w*\s+(?:про|об)|потом|затем|"
        r"\b(?:screenshot|microphone|microfon\w*|send|write|message|scrie(?:-i)?|trimite\w*|"
        r"call|ring|phone|sun[ăa](?:-l)?|apeleaz[ăa]|then|apoi)\b)",
        lower,
    ):
        return None
    if re.search(r"\b(?:не\s+(?:наж\w*|откр\w*|найд\w*|выб\w*)|"
                 r"(?:do\s+not|don['’]?t|never)\s+|nu\s+|how\s+|как\s+|cum\s+)", lower):
        return None
    phrase = re.sub(r"^(?:в|на|in|on|în|pe)\s+" + platform + r"\s*[,;:]?\s+", "", phrase, flags=re.I)
    action = re.match(
        r"^(?:нажм\w*|нажми|жми|жать|откр[оы]\w*|найд\w*|найти|выбер\w*|выбрать|перейд\w*|"
        r"open|find|select|click|go\s+to|"
        r"deschide|deschizi|găsește|gaseste|caută|cauta|apasă|apasa|apeși|apesi|"
        r"selectează|selecteaza|intră|intra)\s+", phrase, re.I,
    )
    if action is None:
        return None
    rest = phrase[action.end():].strip()
    rest = re.sub(r"^(?:(?:в|на|in|on|în|pe)\s+)?" + platform + r"\s+", "", rest, flags=re.I)
    rest = re.sub(r"^(?:(?:на|по|pe|on|the)\s+)+", "", rest, flags=re.I)
    # Opening a person, rather than an arbitrary Discord setting, needs an
    # explicit contact/chat noun. The actual identity remains fully literal.
    descriptor = re.match(
        r"^(?:(?:личн\w*\s+)?(?:чат|переписку)|"
        r"(?:the\s+)?(?:direct\s+messages?|dm|chat|conversation)|"
        r"(?:conversația|conversatia|conversație|conversatie|chatul|dm-ul))"
        r"(?:\s+(?:с|со|cu|with|of))?\s+", rest, re.I,
    )
    if descriptor:
        rest = rest[descriptor.end():]
    role = re.match(
        r"^(?:(?:пользовател[ьюя]|юзер[ау]?|контакт[ау]?|друг[ау]?|"
        r"(?:my\s+)?(?:user|friend|contact)|utilizator(?:ul|ului)?|"
        r"prieten(?:ul|ului)?(?:\s+meu)?|contact(?:ul|ului)?|lui|pe)\s+)+", rest, re.I,
    )
    if role:
        rest = rest[role.end():]
    if descriptor is None and role is None:
        return None
    candidate = re.sub(
        r"\s+(?:в|на|in|on|în|pe)\s+" + platform + r"$",
        "", rest.strip(" .,!?;"), flags=re.I,
    )
    if re.search(r"\s+(?:and|și|si|и)\s+", candidate, re.I):
        return None
    try:
        return validate_discord_review_user(candidate)
    except ValueError:
        return None


def _chat_header_ok(planner, hwnd: int, displayed: str):
    """Check the CURRENT open DM, not a username in the side bar."""
    from luxai.visual_click import capture_window, find_visual_target
    capture = capture_window(hwnd)
    point = find_visual_target(
        planner,
        "Only return found:true for the HEADER of the currently OPEN individual "
        f"Discord DIRECT MESSAGE chat if it unmistakably identifies {displayed!r}. "
        "The header is at the TOP of the active main chat pane. Names in the "
        "left sidebar, Quick Switcher menu, messages or right profiles do "
        "NOT prove an open chat. Return found:false otherwise.",
        capture,
    )
    # Model text matching in a sidebar or search popup is NOT evidence
    # that we entered a chat. A valid active-chat header must be in the
    # actual top strip of the center conversation pane.
    if (point[1] > capture.top + max(58, int(capture.height * 0.20))
            or point[0] < capture.left + int(capture.width * 0.18)):
        raise ValueError("Discord: header of intended active chat not verified")
    return capture


def open_discord_contact(planner, spoken: str, *,
                         confirm_candidate=None, cancelled=None,
                         verified_identity=None) -> str:
    """Locate, open and recheck an individual DM without composing or sending."""
    from luxai.visual_click import capture_window, click_visual_target
    from luxai.discord_search_guard import verified_discord_search

    username = validate_discord_review_user(spoken)

    def check():
        if cancelled is not None and cancelled():
            raise RuntimeError("Discord command cancelled")

    check()
    hwnd = _ensure_discord_visible(cancelled=cancelled)
    focus_discord(hwnd)
    check()
    capture = capture_window(hwnd)
    candidate = locate_visible_contact(planner, capture, username)
    if candidate is None:
        capture = verified_discord_search(
            planner, hwnd, "@" + username, cancelled=cancelled,
        )
        candidate = locate_visible_contact(
            planner, capture, username, quick_switcher=True,
        )
        if candidate is None:
            alias = search_alias(username)
            if alias:
                capture = verified_discord_search(
                    planner, hwnd, "@" + alias, replace=True,
                    cancelled=cancelled,
                )
                candidate = locate_visible_contact(
                    planner, capture, username, quick_switcher=True,
                )
    if candidate is None:
        raise ValueError("Discord: пользователь не найден в списке или в поиске.")
    displayed = candidate.display_name
    if not same_discord_name(username, displayed):
        if confirm_candidate is None or not confirm_candidate(username, displayed):
            raise ValueError("Discord: другой никнейм не подтверждён, чат не открыт.")
    check()
    focus_discord(hwnd)
    click_visual_target(capture, candidate.point, 1)
    time.sleep(0.35)

    for attempt in range(2):
        check()
        try:
            _chat_header_ok(planner, hwnd, displayed)
            if verified_identity is not None:
                # Only pass back the actual visible name AFTER the
                # opened conversation header confirms this identity.
                verified_identity(displayed)
            return f"Discord: открыт и проверен личный чат «{displayed}»."
        except (ValueError, RuntimeError) as exc:
            if attempt:
                raise ValueError(
                    "Discord: после клика заголовок нужного чата не появился. "
                    "Остановился без ввода и отправки сообщений."
                ) from exc
            # A Quick Switcher result can dismiss the overlay without
            # activating the conversation. Take a fresh screenshot and
            # click a *newly located* account in the visible DM sidebar.
            focus_discord(hwnd)
            fresh = capture_window(hwnd)
            second = locate_visible_contact(planner, fresh, displayed)
            if second is None or not same_discord_name(second.display_name, displayed):
                raise ValueError(
                    "Discord: поиск закрылся, но пользователь не найден "
                    "повторно на новом снимке."
                )
            check()
            click_visual_target(fresh, second.point, 1)
            time.sleep(0.35)
    raise RuntimeError("Discord user was not verified")
