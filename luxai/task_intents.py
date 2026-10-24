"""Small, offline intent hints for choosing a desktop tool.

These helpers describe the user's request; they never open an application,
inspect a filesystem, capture a screen, or grant permission to a tool. Compound
requests stay compound, so opening an app cannot silently discard later work.
"""
from __future__ import annotations

import re

from luxai.fast_intents import quick_reply, strip_wake_name
from luxai.windows_apps import ALIASES, normalized_name


_POLITE = re.compile(
    r"^(?:пожалуйста|ну|(?:ты\s+)?можешь(?:\s+ли)?(?:\s+ты)?|"
    r"(?:не\s+)?мог(?:ла)?\s+бы\s+ты|хочу\s+чтобы\s+ты|"
    r"please|(?:can|could|would|will)\s+you(?:\s+please)?|"
    r"te\s+rog(?:\s+frumos)?|(?:poți|poti)(?:\s+(?:să|sa))?|"
    r"ai\s+putea(?:\s+(?:să|sa))?|(?:aș|as)\s+vrea\s+(?:să|sa)|"
    r"vreau\s+(?:să|sa))\b[\s,:;—–-]*", re.I,
)
_OPEN = re.compile(
    r"^(?:открой|открыть|открывай|откроешь|запусти|запустить|"
    r"запускай|включи|включить|зайди(?:\s+в)?|перейди\s+в|"
    r"open|launch|start|run|go\s+(?:to|into)|"
    r"deschide(?:-mi)?|deschizi|pornește|porneste|pornești|pornesti|"
    r"lansează|lanseaza|intră\s+în|intra\s+in)\b\s+", re.I,
)
_ACTION_WORD = (
    r"откро\w*|запуст\w*|включ\w*|выключ\w*|перейд\w*|зайд\w*|"
    r"наж\w*|клик\w*|найд\w*|сдела\w*|созда\w*|прочит\w*|"
    r"подожд\w*|напиш\w*|введ\w*|перемест\w*|скопир\w*|"
    r"закро\w*|удал\w*|отправ\w*|выбер\w*|прокрут\w*|"
    r"измен\w*|покаж\w*|провер\w*|исправ\w*|сверн\w*|разверн\w*|"
    r"очист\w*|перезагруз\w*|перезапуст\w*|заблокир\w*|исслед\w*|"
    r"скача\w*|установ\w*|выполн\w*|"
    r"open|launch|start|run|click|press|find|search|take|create|read|"
    r"wait|write|type|move|copy|close|delete|send|select|scroll|change|resize|"
    r"show|check|fix|minimize|maximize|restart|reboot|lock|research|analyze|analyse|"
    r"deschide|pornește|porneste|apasă|apasa|caută|cauta|fă|fa|"
    r"creează|creeaza|citește|citeste|așteaptă|asteapta|scrie|mută|muta|"
    r"copiază|copiaza|închide|inchide|șterge|sterge|trimite|alege|"
    r"schimbă|schimba|redimensionează|redimensioneaza|verifică|verifica|"
    r"repornește|reporneste|blochează|blocheaza|cercetează|cerceteaza"
)
# Bare "and" can be part of an app name. A conjunction followed by an action
# is a clause boundary; explicit "then"/"потом" are boundaries themselves.
_CLAUSE = re.compile(
    r"(?:\s*[,;]\s*|\s+)(?:потом|затем|после\s+этого|then|apoi|"
    r"după\s+aceea|dupa\s+aceea)\b|"
    r"(?:\s*[,;]\s*(?:(?:и|а|но|and|but|și|si)\s+)?|\s+(?:и|а|но|and|but|și|si)\s+)"
    r"(?=(?:(?:не|don't|do\s+not|nu)\s+)?(?:" + _ACTION_WORD + r")\b)", re.I,
)
_APP_PREFIX = re.compile(
    r"^(?:(?:окно|приложение|программу|программа)(?:\s+приложения)?|"
    r"(?:the\s+)?(?:app|application|program|window)(?:\s+(?:of|for))?|"
    r"(?:aplicația|aplicatia|aplicație|aplicatie|programul|fereastra))\s+", re.I,
)
_NON_APP = re.compile(
    r"^(?:файл\w*|документ\w*|папк\w*|сайт\w*|ссылк\w*|"
    r"вкладк\w*|кнопк\w*|настройк\w*|микрофон\w*|камер\w*|"
    r"громкост\w*|звук\w*|экран\w*|монитор\w*|компьютер\w*|"
    r"ночн\w*|т[её]мн\w*|светл\w*|file|document|folder|website|site|"
    r"link|tab|button|settings|microphone|camera|volume|screen|monitor|"
    r"computer|pc|night|dark|light|fișier\w*|fisier\w*|dosar\w*|"
    r"setări|setari|microfon\w*|ecran\w*|lumina|lumină|tema|temă)\b", re.I,
)
_SHELL = re.compile(
    r"^(?:cmd|powershell|pwsh|terminal|windows\s+terminal|"
    r"командн\w*\s+строк\w*|терминал\w*|linia\s+de\s+comandă|"
    r"linia\s+de\s+comanda)(?:\s|$)", re.I,
)


def _text(text: str) -> str:
    value = " ".join(str(text or "").strip().split())
    for _ in range(4):
        previous = value
        value = strip_wake_name(value).strip()
        value = _POLITE.sub("", value, count=1)
        if value == previous:
            break
    value = re.sub(r"(?:[,\s]+(?:пожалуйста|please|te\s+rog))[.!?]*$", "", value, flags=re.I)
    return value.rstrip(" .!?").strip()


def _app_parts(text: str) -> tuple[str, str] | None:
    value = _text(text)
    launch = _OPEN.match(value)
    if not launch:
        return None
    rest = value[launch.end():].strip()
    boundary = _CLAUSE.search(rest)
    name = rest[:boundary.start()].strip(" ,;") if boundary else rest
    remainder = rest[boundary.start():].strip() if boundary else ""
    name = re.sub(r"^(?:мне|для\s+меня)\s+", "", name, flags=re.I)
    name = re.sub(r"\s+for\s+me$", "", name, flags=re.I)
    name = _APP_PREFIX.sub("", name, count=1).strip()
    if re.match(r"^the\s+.+\s+(?:app|application|window)$", name, re.I):
        name = re.sub(r"^the\s+", "", name, flags=re.I)
    name = re.sub(r"\s+(?:app|application|window)$", "", name, flags=re.I)
    for left, right in (("\"", "\""), ("'", "'"), ("«", "»")):
        if name.startswith(left) and name.endswith(right) and len(name) > 2:
            name = name[1:-1].strip()
            break
    if (not name or _NON_APP.match(name) or _SHELL.match(name)
            or re.search(r"(?:https?://|www\.|\.(?:txt|pdf|docx?|xlsx?|png|jpe?g|gguf))\b", name, re.I)
            or direct_action_request(value) is not None or system_request(value) is not None):
        return None
    # Grammatical forms following "окно"/"window" should still use the same
    # known alias; unrelated multiword application names remain intact.
    folded = name.casefold()
    if folded not in ALIASES and folded[-1:] in {"а", "я", "е"} and folded[:-1] in ALIASES:
        name = folded[:-1]
    try:
        return normalized_name(name), remainder
    except ValueError:
        return None


def direct_app_request(text: str) -> str | None:
    """Return an app name only when opening it is the ENTIRE request."""
    parsed = _app_parts(text)
    return parsed[0] if parsed is not None and not parsed[1] else None


def opening_app(text: str) -> str | None:
    """Return an INITIAL requested app open, never an app named by a click."""
    parsed = _app_parts(text)
    return parsed[0] if parsed is not None else None


def screenshot_request(text: str) -> bool:
    """Recognize a standalone local capture, without dropping later actions."""
    value = _text(text)
    if _CLAUSE.search(value):
        return False
    return bool(re.fullmatch(
        r"(?:(?:сделай|сделать|сними|сохрани)\s+(?:мне\s+)?"
        r"(?:скриншот|скрин|снимок)(?:\s+(?:(?:текущего|активного)\s+)?(?:экрана|окна))?|"
        r"сними\s+экран|"
        r"(?:take|make|save|capture)\s+(?:(?:a|the)\s+)?(?:screenshot|screen\s*shot|screen\s+capture)"
        r"(?:\s+of\s+(?:the\s+)?(?:screen|desktop|current\s+window))?|"
        r"capture\s+(?:the\s+)?screen|"
        r"(?:fă|fa|fă-mi|fa-mi|salvează|salveaza|capturează|captureaza)\s+"
        r"(?:(?:o|un)\s+)?(?:captură\s+de\s+ecran|captura\s+de\s+ecran|screenshot|printscreen))",
        value, re.I,
    ))


def direct_action_request(text: str) -> dict | None:
    """Describe a standalone system-object open, not icon-coordinate guesses."""
    value = _text(text)
    if re.fullmatch(
        r"(?:открой|открыть|покажи|open|show|deschide|arată|arata)\s+"
        r"(?:(?:the|мне)\s+)?(?:корзину(?:\s+Windows)?|(?:Windows\s+)?recycle\s+bin|"
        r"(?:coșul|cosul|coș|cos)(?:\s+de\s+reciclare)?)", value, re.I,
    ):
        return {"action": "open_recycle_bin"}
    return None


def system_request(text: str) -> dict | None:
    """Describe explicit system intent; explanations never become power calls."""
    value = _text(text)
    pc = r"(?:(?:(?:мой|этот)\s+)?(?:компьютер(?:а)?|комп(?:а)?|пк|ноутбук(?:а)?)|windows|(?:(?:the|my|this)\s+)?(?:computer|pc|laptop)|calculator(?:ul)?|laptopul)"
    patterns = (
        ("cancel_shutdown", r"(?:отмени|отменить)\s+(?:выключение|отключение)(?:\s+" + pc + r")?|cancel\s+(?:the\s+)?shutdown|(?:anulează|anuleaza)\s+oprirea(?:\s+calculatorului)?"),
        ("shutdown", r"(?:выключи|выключить|отключи)\s+" + pc + r"|(?:shut\s+down|shutdown|turn\s+off)\s+" + pc + r"|(?:oprește|opreste|închide|inchide)\s+" + pc),
        ("restart", r"(?:перезагрузи|перезагрузить|перезапусти)\s+" + pc + r"|(?:restart|reboot)\s+" + pc + r"|(?:repornește|reporneste|restartează|restarteaza)\s+" + pc),
        ("sleep", r"(?:переведи|отправь)\s+" + pc + r"\s+(?:в\s+)?(?:спящий\s+режим|сон)|(?:включи|активируй)\s+спящий\s+режим|put\s+" + pc + r"\s+to\s+sleep|sleep\s+" + pc + r"|(?:pune|treci)\s+" + pc + r"\s+(?:în|in)\s+(?:repaus|modul\s+(?:de\s+)?repaus)"),
        ("lock", r"(?:заблокируй|заблокировать)\s+(?:экран|сеанс|сессию|" + pc + r")|lock\s+(?:(?:the|my)\s+)?(?:screen|session|computer|pc)|(?:blochează|blocheaza)\s+(?:ecranul|sesiunea|calculatorul)"),
    )
    for action, pattern in patterns:
        if re.fullmatch(pattern, value, re.I):
            return {"action": action}

    if re.fullmatch(
        r"(?:какая(?:\s+сейчас)?\s+тема(?:\s+Windows)?|проверь\s+тему(?:\s+Windows)?|"
        r"(?:what|which)(?:\s+is\s+the)?\s+(?:current\s+)?(?:windows\s+)?theme(?:\s+is\s+(?:active|enabled))?|"
        r"(?:ce|care)\s+(?:este\s+)?tem[ăa](?:\s+(?:actuală|actuala|Windows|este\s+activă|este\s+activa))?|(?:verifică|verifica)\s+tema)",
        value, re.I,
    ):
        return {"action": "get_theme"}

    kind = r"т[её]мн\w*|светл\w*|dark|light|întunecată|intunecata|închisă|inchisa|deschisă|deschisa"
    setting = re.fullmatch(
        r"(?P<verb>включи|отключи|выключи|поставь|установи|переключи|выбери|"
        r"enable|disable|set|use|switch\s+to|turn\s+on|turn\s+off|"
        r"activează|activeaza|dezactivează|dezactiveaza|setează|seteaza)\s+"
        r"(?:(?:на|the|o)\s+)?(?:(?P<kind>" + kind + r")\s+"
        r"(?:тему|тема|режим|theme|mode|temă|tema)|"
        r"(?:тему|тема|режим|theme|mode|temă|tema)\s+(?P<kind_after>" + kind + r"))"
        r"(?:\s+(?:Windows|в\s+Windows))?", value, re.I,
    )
    if setting:
        dark = bool(re.match(r"т[её]мн|dark|întunec|intunec|închis|inchis", setting["kind"] or setting["kind_after"], re.I))
        disabled = bool(re.match(r"отключ|выключ|disable|turn\s+off|dezactiv", setting["verb"], re.I))
        return {"action": "set_dark_theme", "enabled": dark != disabled}
    if re.fullmatch(
        r"(?:(?:включи|выключи|отключи|открой|настрой|enable|disable|open|"
        r"turn\s+on|turn\s+off|activează|activeaza|dezactivează|dezactiveaza|deschide)\s+)?"
        r"(?:ночной\s+свет|night\s+light|(?:lumină|lumina)\s+de\s+noapte)(?:\s+Windows)?", value, re.I,
    ):
        return {"action": "open_night_light_settings"}
    if re.fullmatch(
        r"(?:(?:включи|выключи|отключи|поставь|активируй|enable|disable|set|"
        r"turn\s+on|turn\s+off|activează|activeaza|dezactivează|dezactiveaza|setează|seteaza)\s+)?"
        r"(?:ночной\s+режим|night\s+mode|(?:modul|mod|regim(?:ul)?)\s+de\s+noapte)", value, re.I,
    ):
        return {"action": "clarify_night_mode"}
    return None


def is_task_cancel(text: str) -> bool:
    """Exact task cancellation; bare Stop remains available to speech controls."""
    return bool(re.fullmatch(
        r"(?:(?:отмени|прекрати|останови)\s+(?:(?:это|эту|текущее|текущую)\s+)?"
        r"(?:задание|задачу|операцию|выполнение)|отмена\s+(?:задания|задачи)|"
        r"(?:cancel|abort|stop)\s+(?:(?:the|this|current)\s+)?(?:task|job|operation|request)|"
        r"(?:anulează|anuleaza|oprește|opreste)\s+(?:(?:această|aceasta)\s+)?(?:sarcina|operația|operatia))",
        _text(text), re.I,
    ))


def needs_adaptive_task(text: str) -> bool:
    """Identify a task to reason about, rather than ordinary conversation."""
    value = _text(text)
    if not value or is_task_cancel(value) or quick_reply(value) is not None:
        return False
    if any((opening_app(value), screenshot_request(value), system_request(value), direct_action_request(value))):
        return True
    if re.match(r"^(?:" + _ACTION_WORD + r"|покажи|проверь|исправь|выполни|скачай|установи|"
                r"show|check|fix|execute|download|install|arată|arata|verifică|verifica|execută|executa|rulează|ruleaza)\b", value, re.I):
        return True
    # How-to questions about Windows are research tasks, not permission to run
    # the operation described in the question (notably power operations).
    return bool(
        re.match(r"^(?:как\b|как\s+мне|how\b|cum\b|найди\b|research\b|cercetează\b|cerceteaza\b)", value, re.I)
        and re.search(r"\b(?:windows|компьютер\w*|пк|дискорд\w*|discord|приложени\w*|"
                      r"экран\w*|скрин\w*|файл\w*|папк\w*|микрофон\w*|"
                      r"desktop|computer|app|screen|screenshot|file|folder|microphone|"
                      r"calculator|aplicați\w*|aplicati\w*|ecran|microfon)\b", value, re.I)
    )
