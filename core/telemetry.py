"""
core/telemetry.py
------------------------------------------------------------------------------
YAKSHA AI v2.0 — LLM call telemetry

The dashboard needs per-agent tokens, latency, active model/provider and a
"what did the model see / say" trace. None of that flows through the event
bus, and the agents shouldn't be modified to report it. Instead,
InstrumentedRouter wraps any router exposing `.complete(role, messages, ...)`
and records every call into a thread-safe TelemetryStore.

Attribution:
    - agent   -> the `role` argument (matches the agent roles in config)
    - run     -> the RunControl bound to the current ContextVar (see
                 core/run_control.py), so parallel developer threads are
                 attributed to the right run.

The wrapper is also the pause/cancel gate: it checkpoints BEFORE a call (so a
paused run starts nothing new) and AFTER it (so a cancelled run discards the
result instead of acting on it).

Honesty note on "thought process": what's captured is the prompt sent and the
raw text the model returned — not hidden chain-of-thought, which providers
don't expose.
------------------------------------------------------------------------------
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from core.llm_router import LLMRouterError
from core.run_control import checkpoint, current_control

MAX_TEXT_CHARS = 20_000  # per stored prompt/response, to keep memory bounded
UNKNOWN_RUN = "unknown"


def _clip(text: str) -> str:
    if len(text) <= MAX_TEXT_CHARS:
        return text
    return text[:MAX_TEXT_CHARS] + f"\n…[truncated, {len(text) - MAX_TEXT_CHARS} more chars]"


@dataclass
class CallRecord:
    run_id: str
    role: str
    ok: bool
    provider: str
    model: str
    tokens: int
    latency_s: float
    attempt: int
    started_at: str
    prompt: str
    response: str
    warnings: list[str] = field(default_factory=list)
    error: Optional[str] = None
    finished_ts: float = field(default_factory=time.time)


class TelemetryStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: dict[str, list[CallRecord]] = defaultdict(list)

    def record(self, rec: CallRecord) -> None:
        with self._lock:
            self._calls[rec.run_id].append(rec)

    def calls(self, run_id: str, role: Optional[str] = None) -> list[CallRecord]:
        with self._lock:
            items = list(self._calls.get(run_id, []))
        return [c for c in items if role is None or c.role == role]

    def total_tokens(self, run_id: str) -> int:
        return sum(c.tokens for c in self.calls(run_id) if c.ok)

    def latest(self, run_id: str) -> Optional[CallRecord]:
        items = self.calls(run_id)
        return items[-1] if items else None

    def tokens_last_minute(self, provider: str) -> int:
        """Tokens spent on `provider` across ALL runs in the trailing 60 seconds."""
        cutoff = time.time() - 60
        with self._lock:
            all_calls = [c for calls in self._calls.values() for c in calls]
        return sum(c.tokens for c in all_calls if c.ok and c.provider == provider and c.finished_ts >= cutoff)


def _render_messages(messages: list[dict[str, str]]) -> str:
    return "\n\n".join(f"[{m.get('role', '?')}]\n{m.get('content', '')}" for m in messages)


class InstrumentedRouter:
    """Drop-in wrapper: agents call `.complete()` exactly as they would on LLMRouter."""

    def __init__(self, inner: Any, store: TelemetryStore) -> None:
        self.inner = inner
        self.store = store

    def complete(self, role: str, messages: list[dict[str, str]], max_output_tokens: int = 2048, **kwargs: Any):
        checkpoint()  # paused -> block here; cancelled -> raise RunCancelled

        control = current_control.get()
        run_id = control.run_id if control else UNKNOWN_RUN
        started_at = datetime.now(timezone.utc).isoformat()
        prompt = _clip(_render_messages(messages))
        t0 = time.monotonic()

        try:
            result = self.inner.complete(role, messages, max_output_tokens=max_output_tokens, **kwargs)
        except Exception as exc:
            self.store.record(CallRecord(
                run_id=run_id, role=role, ok=False, provider="-", model="-", tokens=0,
                latency_s=round(time.monotonic() - t0, 3), attempt=0, started_at=started_at,
                prompt=prompt, response="", error=_clip(str(exc)),
                warnings=list(getattr(exc, "attempts", []) or []) if isinstance(exc, LLMRouterError) else [],
            ))
            raise

        self.store.record(CallRecord(
            run_id=run_id, role=role, ok=True, provider=result.provider, model=result.model_name,
            tokens=result.tokens_used, latency_s=round(time.monotonic() - t0, 3), attempt=result.attempt,
            started_at=started_at, prompt=prompt, response=_clip(result.text),
            warnings=list(result.warnings),
        ))
        checkpoint()  # cancelled while in flight -> discard the result
        return result