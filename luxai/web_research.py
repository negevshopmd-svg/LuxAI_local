"""Bounded, source-backed Wikipedia research for general desktop tasks.

This returns remote article text as data, never as instructions or authority.
It is independent of Discord recipients, message limits and send workflows.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request


MAX_RESPONSE_BYTES = 160_000
MAX_TEXT_CHARS = 3000
LANGUAGES = frozenset({"en", "ro", "ru"})
_SOURCE_LABEL = {"en": "Source", "ro": "Sursă", "ru": "Источник"}
_HTML_TAG = re.compile(r"</?[A-Za-z][^>]*>")


def researched_summary(query: str, language: str = "en") -> tuple[str, str]:
    """Return one actual Wikipedia plaintext extract and its source URL.

    Queries contain 2–450 characters. The returned text, including title and
    localized citation, is at most 3000 characters. A missing, ambiguous or
    malformed article raises ValueError; transport errors remain OSError.
    No HTML page is scraped and no text is invented to fill missing results.
    """
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 450:
        raise ValueError("Research query must contain 2 to 450 characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in query):
        raise ValueError("Research query must not contain control characters")
    if not isinstance(language, str) or language not in LANGUAGES:
        raise ValueError("Research language must be en, ro or ru")
    query = query.strip()
    host = language + ".wikipedia.org"
    parameters = urllib.parse.urlencode({
        "action": "query", "generator": "search", "gsrsearch": query,
        "gsrnamespace": "0", "gsrlimit": "1", "prop": "extracts|pageprops",
        "ppprop": "disambiguation", "exintro": "1", "explaintext": "1",
        "exchars": "3000", "format": "json", "formatversion": "2",
    })
    request = urllib.request.Request(
        "https://" + host + "/w/api.php?" + parameters,
        headers={"User-Agent": "LuxAI-DesktopAssistant/0.3 (Wikipedia research)",
                 "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=14) as response:
        if response.status != 200:
            raise OSError("Wikipedia API returned an error")
        destination = urllib.parse.urlsplit(response.geturl())
        if (destination.scheme != "https" or destination.hostname != host
                or destination.username or destination.password or destination.port not in (None, 443)):
            raise OSError("Wikipedia response left the requested HTTPS source")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if not isinstance(raw, bytes) or len(raw) > MAX_RESPONSE_BYTES:
        raise OSError("Wikipedia response exceeds the research size limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ValueError("Wikipedia did not return a valid JSON response") from exc
    if not isinstance(payload, dict) or "error" in payload:
        raise ValueError("Wikipedia research returned no usable result")
    result = payload.get("query")
    pages = result.get("pages") if isinstance(result, dict) else None
    if not isinstance(pages, list) or len(pages) != 1 or not isinstance(pages[0], dict):
        raise ValueError("Wikipedia did not find a unique article")
    page = pages[0]
    title, extract = page.get("title"), page.get("extract")
    properties = page.get("pageprops", {})
    if ("missing" in page or page.get("invalid") is not None
            or (isinstance(properties, dict) and "disambiguation" in properties)
            or not isinstance(title, str) or not 1 <= len(title.strip()) <= 300
            or not isinstance(extract, str) or not extract.strip()
            or _HTML_TAG.search(title) or _HTML_TAG.search(extract)
            or any(ord(character) < 32 for character in title)):
        raise ValueError("Wikipedia has no usable plaintext article for this query")
    title = title.strip()
    extract = re.sub(r"\s+", " ", extract).strip()
    source = "https://" + host + "/wiki/" + urllib.parse.quote(title.replace(" ", "_"), safe="()_")
    heading = title + ": "
    citation = "\n" + _SOURCE_LABEL[language] + ": " + source
    available = MAX_TEXT_CHARS - len(heading) - len(citation)
    if available < 1:
        raise ValueError("Wikipedia article citation exceeds the research limit")
    if len(extract) > available:
        snippet = extract[:available - 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
        if not snippet:
            snippet = extract[:available - 1]
        extract = snippet + "…"
    return heading + extract + citation, source
