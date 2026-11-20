"""Small background workers shared by the extensions (audit 2 #15, #16, #23).

``LatestWorker`` is ONE daemon thread per purpose instead of a new thread per request:

* jobs run one at a time, in the order they were accepted, so an old snapshot can never be
  written after a newer one;
* a job still WAITING is replaced by a newer one (coalescing): a burst of clipboard copies or
  settings saves costs one run, and memory stays bounded;
* ``wait()`` lets the owner wait, with a limit, for the last accepted job when it closes.

``SerialQueue`` keeps every job (bounded), for work where each request needs its own answer
(translations): one worker, explicit queue, answers in request order.
"""
from __future__ import annotations

import logging
import queue
import threading


class LatestWorker:
    def __init__(self, name: str):
        self.name = name
        self._condition = threading.Condition()
        self._waiting = None  # (generation, job) not started yet
        self._running = 0
        self._accepted = 0
        self._thread = None
        self._closed = False

    @property
    def generation(self) -> int:
        """The number of the last accepted job."""
        return self._accepted

    def submit(self, job) -> int:
        """Accept ``job`` (replacing one that has not started); returns its generation, 0 when closed."""
        with self._condition:
            if self._closed:
                return 0
            self._accepted += 1
            self._waiting = (self._accepted, job)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
                self._thread.start()
            self._condition.notify_all()
            return self._accepted

    def _run(self):
        while True:
            with self._condition:
                while self._waiting is None and not self._closed:
                    if not self._condition.wait(30):
                        if self._waiting is None:
                            self._thread = None  # idle: the thread ends, the next submit starts one
                            return
                if self._waiting is None:
                    self._thread = None
                    return
                generation, job = self._waiting
                self._waiting = None
                self._running = generation
            try:
                job()
            except Exception:
                logging.getLogger(__name__).exception("%s job failed", self.name)
            with self._condition:
                self._running = 0
                self._condition.notify_all()

    def idle(self) -> bool:
        with self._condition:
            return self._waiting is None and not self._running

    def wait(self, timeout: float) -> bool:
        """Wait until the last accepted job finished (True) or ``timeout`` passed (False)."""
        import time
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            while self._waiting is not None or self._running:
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self._condition.wait(left)
            return True

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()


class SerialQueue:
    """One worker thread and an explicit, bounded queue; ``submit`` returns False when it is full."""

    def __init__(self, name: str, limit: int = 16):
        self.name = name
        self._queue = queue.Queue(maxsize=limit)
        self._thread = None
        self._lock = threading.Lock()

    def submit(self, job) -> bool:
        try:
            self._queue.put_nowait(job)
        except queue.Full:
            return False
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
                self._thread.start()
        return True

    def _run(self):
        while True:
            try:
                job = self._queue.get(timeout=30)
            except queue.Empty:
                with self._lock:
                    if self._queue.empty():
                        self._thread = None
                        return
                continue
            try:
                job()
            except Exception:
                logging.getLogger(__name__).exception("%s job failed", self.name)

    def pending(self) -> int:
        return self._queue.qsize()
