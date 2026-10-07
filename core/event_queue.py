"""
core/event_queue.py
------------------------------------------------------------------------------
YAKSHA AI v2.0 — Thread-Safe Event Queue + Background Run Executor

Why this exists (v1.0 problem it fixes):
    In v1.0, CrewAI's `crew.kickoff()` ran directly on Streamlit's main
    script thread. Because that call blocks for the entire duration of a
    multi-agent run, the whole dashboard froze — no spinner updates, no
    live status, sometimes the browser tab looked hung.

How it works:
    - EventBus owns one `queue.Queue` per run_id. `queue.Queue` is already
      thread-safe for put/get, so no extra locking is needed for the hot
      path; a small Lock only guards *registry* mutation (creating/removing
      a run's queue).
    - BackgroundExecutor runs the actual long-lived work (CrewAI kickoff,
      or any callable) on a daemon `threading.Thread`, so Streamlit's main
      thread returns immediately after starting it.
    - A lightweight `threading.Timer` watchdog fires a RUN_TIMEOUT warning
      event if the run is still alive past `CREW_EXECUTION_TIMEOUT_SECONDS`
      — Python can't safely force-kill a thread, so this is a visibility
      signal for the dashboard, not a hard kill.

Streamlit integration pattern (this module has zero Streamlit dependency —
it's plain threading + queue, so it's usable from main.py's CLI path too):

    # First render of a run:
    if "event_bus" not in st.session_state:
        st.session_state.event_bus = EventBus()
    if st.button("Run"):
        handle = BackgroundExecutor(st.session_state.event_bus).run_in_background(
            run_id, kickoff_fn
        )
        st.session_state.run_handle = handle

    # On every rerun (e.g. driven by st_autorefresh or a polling loop):
    for event in st.session_state.event_bus.drain(run_id):
        render_event(event)   # e.g. append to a status container
    if st.session_state.run_handle.is_alive():
        time.sleep(EVENT_QUEUE.poll_interval_seconds)
        st.rerun()
------------------------------------------------------------------------------
"""

from __future__ import annotations

import logging
import queue
import threading
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional

from core.config import CREW_EXECUTION_TIMEOUT_SECONDS, EVENT_QUEUE
from core.run_control import RunCancelled

logger = logging.getLogger("yaksha.event_queue")


# ------------------------------------------------------------------------
# Event vocabulary
# ------------------------------------------------------------------------

class EventType(str, Enum):
    RUN_STARTED = "run_started"
    AGENT_STARTED = "agent_started"
    AGENT_PROGRESS = "agent_progress"
    ARTIFACT_SAVED = "artifact_saved"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"
    ASSEMBLY_STARTED = "assembly_started"
    ASSEMBLY_COMPLETED = "assembly_completed"
    QA_REPORT_READY = "qa_report_ready"
    RUN_PAUSED = "run_paused"
    RUN_RESUMED = "run_resumed"
    RUN_CANCELLED = "run_cancelled"
    RUN_TIMEOUT = "run_timeout"          # watchdog warning — run is still alive past budget
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"


@dataclass
class Event:
    run_id: str
    type: EventType
    message: str
    sequence: int
    agent_role: Optional[str] = None
    payload: Optional[dict[str, Any]] = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "type": self.type.value,
            "message": self.message,
            "sequence": self.sequence,
            "agent_role": self.agent_role,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }


# ------------------------------------------------------------------------
# EventBus — thread-safe, per-run event queues
# ------------------------------------------------------------------------

class EventBus:
    """
    Owns one bounded, thread-safe queue per run_id.

    Bounded queues are a deliberate choice: if a Streamlit tab is left
    unattended and never drains events, memory usage must stay flat. When a
    run's queue is full, the OLDEST event is dropped to make room for the
    newest one — a live dashboard cares about the current status far more
    than a stale one from seconds ago.
    """

    def __init__(self, max_queue_size: int = EVENT_QUEUE.max_queue_size) -> None:
        self._max_queue_size = max_queue_size
        self._queues: dict[str, "queue.Queue[Event]"] = {}
        self._sequence_counters: dict[str, int] = {}
        self._registry_lock = threading.Lock()

    # -- registry management -------------------------------------------------

    def _get_or_create_queue(self, run_id: str) -> "queue.Queue[Event]":
        with self._registry_lock:
            q = self._queues.get(run_id)
            if q is None:
                q = queue.Queue(maxsize=self._max_queue_size)
                self._queues[run_id] = q
                self._sequence_counters[run_id] = 0
            return q

    def close_run(self, run_id: str) -> None:
        """Drops a run's queue entirely. Safe no-op if it never existed."""
        with self._registry_lock:
            self._queues.pop(run_id, None)
            self._sequence_counters.pop(run_id, None)

    def active_runs(self) -> list[str]:
        with self._registry_lock:
            return list(self._queues.keys())

    def _next_sequence(self, run_id: str) -> int:
        with self._registry_lock:
            seq = self._sequence_counters.get(run_id, 0) + 1
            self._sequence_counters[run_id] = seq
            return seq

    # -- publish / consume ----------------------------------------------------

    def publish(
        self,
        run_id: str,
        event_type: EventType,
        message: str,
        *,
        agent_role: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> Event:
        """
        Thread-safe from any thread (background worker or main thread).
        Never blocks: if the run's queue is full, the oldest event is
        dropped to make room.
        """
        q = self._get_or_create_queue(run_id)
        event = Event(
            run_id=run_id,
            type=event_type,
            message=message,
            sequence=self._next_sequence(run_id),
            agent_role=agent_role,
            payload=payload,
        )
        try:
            q.put_nowait(event)
        except queue.Full:
            try:
                dropped = q.get_nowait()
                logger.warning(
                    "[run=%s] event queue full — dropped event #%d (%s) to make room",
                    run_id, dropped.sequence, dropped.type.value,
                )
            except queue.Empty:
                pass
            q.put_nowait(event)
        return event

    def drain(self, run_id: str, max_items: Optional[int] = None) -> list[Event]:
        """
        Non-blocking: returns every event currently available for `run_id`
        (up to max_items), in the order they were published. Returns an
        empty list if the run doesn't exist yet or has no pending events —
        this is the method a Streamlit polling loop calls every tick.
        """
        q = self._queues.get(run_id)
        if q is None:
            return []

        events: list[Event] = []
        while max_items is None or len(events) < max_items:
            try:
                events.append(q.get_nowait())
            except queue.Empty:
                break
        return events

    def pending_count(self, run_id: str) -> int:
        q = self._queues.get(run_id)
        return q.qsize() if q is not None else 0


# ------------------------------------------------------------------------
# BackgroundExecutor — runs the long-lived work off the main thread
# ------------------------------------------------------------------------

@dataclass
class RunHandle:
    run_id: str
    thread: threading.Thread
    started_at: str

    def is_alive(self) -> bool:
        return self.thread.is_alive()

    def join(self, timeout: Optional[float] = None) -> None:
        self.thread.join(timeout=timeout)


class BackgroundExecutor:
    """
    Runs a target callable (typically a CrewAI `crew.kickoff()` wrapper) on
    a daemon thread and publishes lifecycle events to an EventBus as it goes,
    so the caller's main thread (Streamlit, CLI, FastAPI) never blocks.
    """

    def __init__(
        self,
        event_bus: EventBus,
        timeout_seconds: float = CREW_EXECUTION_TIMEOUT_SECONDS,
    ) -> None:
        self.event_bus = event_bus
        self.timeout_seconds = timeout_seconds

    def run_in_background(
        self,
        run_id: str,
        target: Callable[..., Any],
        *,
        args: tuple = (),
        kwargs: Optional[dict[str, Any]] = None,
    ) -> RunHandle:
        kwargs = kwargs or {}
        timer_holder: dict[str, threading.Timer] = {}

        def _wrapper() -> None:
            self.event_bus.publish(run_id, EventType.RUN_STARTED, "Run started")
            try:
                result = target(*args, **kwargs)
                self.event_bus.publish(
                    run_id,
                    EventType.RUN_COMPLETED,
                    "Run completed successfully",
                    payload={"result_summary": self._safe_summary(result)},
                )
            except RunCancelled as exc:
                logger.info("Run '%s' cancelled: %s", run_id, exc)
                self.event_bus.publish(run_id, EventType.RUN_CANCELLED, str(exc))
            except Exception as exc:  # noqa: BLE001 — surface any agent/crew failure to the UI
                tb = traceback.format_exc()
                logger.error("Run '%s' failed: %s", run_id, exc)
                self.event_bus.publish(
                    run_id,
                    EventType.RUN_FAILED,
                    f"Run failed: {exc}",
                    payload={"traceback": tb},
                )
            finally:
                timer = timer_holder.get("timer")
                if timer is not None:
                    timer.cancel()

        thread = threading.Thread(
            target=_wrapper, name=f"yaksha-run-{run_id}", daemon=True
        )

        def _watchdog() -> None:
            if thread.is_alive():
                self.event_bus.publish(
                    run_id,
                    EventType.RUN_TIMEOUT,
                    f"Run has exceeded its expected budget of "
                    f"{self.timeout_seconds:.0f}s and is still running "
                    f"(this is a visibility warning, not a hard stop)",
                )

        timer = threading.Timer(self.timeout_seconds, _watchdog)
        timer.daemon = True
        timer_holder["timer"] = timer

        thread.start()
        timer.start()

        return RunHandle(
            run_id=run_id,
            thread=thread,
            started_at=datetime.now(timezone.utc).isoformat(),
        )

    @staticmethod
    def _safe_summary(result: Any) -> str:
        """Best-effort, truncated string summary — never let logging itself crash a run."""
        try:
            text = str(result)
        except Exception:
            return "<unrepresentable result>"
        return text if len(text) <= 500 else text[:500] + "...(truncated)"


if __name__ == "__main__":
    # Manual smoke test: python -m core.event_queue
    # Exercises (a) background execution not blocking the caller, (b) live
    # draining of events while the job runs, (c) bounded-queue drop-oldest
    # behavior, (d) the timeout watchdog firing on a slow job.
    import time as _time

    logging.basicConfig(level=logging.INFO)

    # --- (a) + (b): normal run, drained live ---
    bus = EventBus()
    executor = BackgroundExecutor(bus, timeout_seconds=5)

    def fake_crew_job(run_id: str) -> str:
        for i, agent in enumerate(["pm", "backend", "frontend", "qa"], start=1):
            bus.publish(run_id, EventType.AGENT_STARTED, f"{agent} started", agent_role=agent)
            _time.sleep(0.15)
            bus.publish(run_id, EventType.AGENT_COMPLETED, f"{agent} completed", agent_role=agent)
        return "app.py generated"

    run_id = "demo-run-1"
    handle = executor.run_in_background(run_id, fake_crew_job, args=(run_id,))
    print("Main thread is free immediately:", not handle.thread is threading.current_thread())

    seen_types = []
    while handle.is_alive() or bus.pending_count(run_id) > 0:
        for event in bus.drain(run_id):
            seen_types.append(event.type)
            print(f"  [{event.sequence}] {event.type.value}: {event.message}")
        _time.sleep(0.05)
    handle.join()
    assert EventType.RUN_COMPLETED in seen_types
    print("Scenario A/B passed: background run drained live, ended with RUN_COMPLETED.\n")

    # --- (c): bounded queue drop-oldest behavior ---
    tiny_bus = EventBus(max_queue_size=3)
    for i in range(10):
        tiny_bus.publish("overflow-run", EventType.AGENT_PROGRESS, f"tick {i}")
    remaining = tiny_bus.drain("overflow-run")
    assert len(remaining) == 3
    assert remaining[-1].message == "tick 9"  # newest always survives
    print(f"Scenario C passed: queue capped at 3, newest event kept ({remaining[-1].message}).\n")

    # --- (d): timeout watchdog fires on a slow job ---
    slow_bus = EventBus()
    slow_executor = BackgroundExecutor(slow_bus, timeout_seconds=0.2)

    def slow_job() -> str:
        _time.sleep(0.5)
        return "done late"

    slow_handle = slow_executor.run_in_background("slow-run", slow_job)
    slow_handle.join()
    slow_events = slow_bus.drain("slow-run")
    types = [e.type for e in slow_events]
    assert EventType.RUN_TIMEOUT in types
    assert EventType.RUN_COMPLETED in types
    print("Scenario D passed: RUN_TIMEOUT warning fired, job still completed afterward.\n")

    print("All event_queue smoke-test scenarios passed.")