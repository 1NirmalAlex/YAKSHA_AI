"""
core/run_control.py
------------------------------------------------------------------------------
YAKSHA AI v2.0 — Cooperative Pause / Resume / Cancel for a pipeline run

Python cannot safely kill a thread, and an in-flight LLM HTTP call can't be
interrupted. So control is COOPERATIVE: the pipeline calls `checkpoint()` at
safe points (between stages, and before/after every LLM call via the
InstrumentedRouter). At a checkpoint:

    - paused    -> the calling thread blocks until resumed (or cancelled)
    - cancelled -> RunCancelled is raised, unwinding the pipeline cleanly

Consequence worth knowing: an LLM call that is already in flight when the user
clicks Pause/Stop finishes first (its result is discarded on cancel). Nothing
new is started after that.

The active run's control object travels in a ContextVar so deeply nested code
(e.g. the router wrapper) can find it without every function taking a
`control` argument. NOTE: ContextVars are not inherited by new threads — code
that spawns worker threads must use `contextvars.copy_context().run(...)`.
------------------------------------------------------------------------------
"""

from __future__ import annotations

import threading
import time
from contextvars import ContextVar
from typing import Optional

CANCEL_MESSAGE = "Run cancelled by user"


class RunCancelled(Exception):
    """Raised at a checkpoint after the user cancelled the run."""


class RunControl:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._lock = threading.Lock()
        self._resume = threading.Event()
        self._resume.set()                 # set == "allowed to run"
        self._cancel = threading.Event()
        self._started = time.monotonic()
        self._finished: Optional[float] = None
        self._paused_at: Optional[float] = None
        self._paused_total = 0.0

    # -- state ---------------------------------------------------------------

    @property
    def is_paused(self) -> bool:
        return not self._resume.is_set() and not self._cancel.is_set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    @property
    def state(self) -> str:
        if self._cancel.is_set():
            return "cancelled"
        return "paused" if not self._resume.is_set() else "running"

    def elapsed_seconds(self) -> float:
        """Wall-clock run time, EXCLUDING time spent paused."""
        with self._lock:
            end = self._finished if self._finished is not None else time.monotonic()
            paused = self._paused_total
            if self._paused_at is not None:
                paused += end - self._paused_at
            return max(0.0, end - self._started - paused)

    # -- commands (called from the UI thread) ---------------------------------

    def pause(self) -> bool:
        with self._lock:
            if self._cancel.is_set() or self._finished is not None or not self._resume.is_set():
                return False
            self._paused_at = time.monotonic()
            self._resume.clear()
            return True

    def resume(self) -> bool:
        with self._lock:
            if self._resume.is_set() or self._cancel.is_set():
                return False
            self._close_pause_window()
            self._resume.set()
            return True

    def cancel(self) -> bool:
        with self._lock:
            if self._cancel.is_set() or self._finished is not None:
                return False
            self._close_pause_window()
            self._cancel.set()
            self._resume.set()             # wake any thread blocked in checkpoint()
            return True

    def mark_finished(self) -> None:
        with self._lock:
            if self._finished is None:
                self._close_pause_window()
                self._finished = time.monotonic()

    def _close_pause_window(self) -> None:
        if self._paused_at is not None:
            self._paused_total += time.monotonic() - self._paused_at
            self._paused_at = None

    # -- checkpoint (called from pipeline threads) ------------------------------

    def checkpoint(self, poll_seconds: float = 0.2) -> None:
        while True:
            if self._cancel.is_set():
                raise RunCancelled(CANCEL_MESSAGE)
            if self._resume.wait(timeout=poll_seconds):
                if self._cancel.is_set():
                    raise RunCancelled(CANCEL_MESSAGE)
                return


current_control: ContextVar[Optional[RunControl]] = ContextVar(
    "yaksha_current_control", default=None
)


def checkpoint() -> None:
    """Checkpoint against the run bound to the current context (no-op if none)."""
    control = current_control.get()
    if control is not None:
        control.checkpoint()