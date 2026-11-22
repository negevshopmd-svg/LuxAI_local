"""Small, bounded retry policy for read-only cloud inference/discovery calls.

Only explicit gateway/unavailable responses are retried, once, against the
identical URL, headers and body. Timeouts and authentication/quota errors are
not retried. These calls propose actions; they never execute local actions.
"""
from __future__ import annotations

import http.client
import json
import time
import urllib.error
from email.utils import parsedate_to_datetime

TRANSIENT_STATUSES = frozenset({502, 503, 504})


def request_timeout(settings: dict) -> int:
    """Use the same effective timeout as the Settings UI and command planner."""
    try:
        configured = int(settings.get("online_timeout", 60))
    except (ValueError, TypeError, OverflowError):
        configured = 60
    return 60 if configured < 35 else min(configured, 120)


def _retry_delay(error: urllib.error.HTTPError) -> float | None:
    value = error.headers.get("Retry-After", "") if error.headers else ""
    if not value:
        return 0.4
    try:
        delay = float(int(value))
    except (ValueError, TypeError, OverflowError):
        try:
            delay = parsedate_to_datetime(value).timestamp() - time.time()
        except (ValueError, TypeError, OverflowError):
            return 0.4
    # Do not hammer a service that explicitly asks for a longer pause. Let
    # the UI report its availability instead of tying up a worker for minutes.
    return max(0.0, delay) if delay <= 2 else None


def _set_socket_timeout(response, seconds: float) -> None:
    raw = getattr(getattr(response, "fp", None), "raw", None)
    sock = getattr(raw, "_sock", None)
    if sock is not None:
        try:
            sock.settimeout(max(0.05, seconds))
        except OSError:
            pass


def _read_body(response, limit: int, deadline: float) -> bytes:
    """The body within the SAME deadline (audit 7 #6).

    ``read(n)`` waited for every byte of a slow server (a 0.25 s budget took 1.2 s): each wait of the
    socket counted separately. The body is read piece by piece now, the socket waits only for the time
    left, and the read stops at the deadline."""
    if not isinstance(response, http.client.HTTPResponse):
        return response.read(limit + 1)  # test doubles / other transports
    chunks, total = [], 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("The cloud response took longer than its time limit.")
        _set_socket_timeout(response, remaining)
        chunk = response.read1(min(65536, limit + 1 - total))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > limit:
            return b"".join(chunks)


def read_json_response(opener, request, timeout: float, limit: int = 1024 * 1024):
    """Read one JSON response, with at most one retry inside the time budget."""
    budget = max(0.1, float(timeout))
    deadline = time.monotonic() + budget
    for attempt in range(2):
        remaining = max(0.1, deadline - time.monotonic())
        try:
            with opener.open(request, timeout=min(budget, remaining)) as response:
                if response.status != 200:
                    raise ValueError("Unexpected API response status")
                raw = _read_body(response, limit, deadline)
                if len(raw) > limit:
                    raise ValueError("API response exceeds size limit")
            return json.loads(raw)
        except urllib.error.HTTPError as error:
            delay = _retry_delay(error) if error.code in TRANSIENT_STATUSES else None
            if attempt or delay is None or deadline - time.monotonic() <= delay + 0.25:
                raise
            error.close()
            time.sleep(delay)
