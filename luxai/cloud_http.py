"""Small, bounded retry policy for read-only cloud inference/discovery calls.

Only explicit gateway/unavailable responses are retried, once, against the
identical URL, headers and body. Timeouts and authentication/quota errors are
not retried. These calls propose actions; they never execute local actions.
"""
from __future__ import annotations

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
                raw = response.read(limit + 1)
                if len(raw) > limit:
                    raise ValueError("API response exceeds size limit")
            return json.loads(raw)
        except urllib.error.HTTPError as error:
            delay = _retry_delay(error) if error.code in TRANSIENT_STATUSES else None
            if attempt or delay is None or deadline - time.monotonic() <= delay + 0.25:
                raise
            error.close()
            time.sleep(delay)
