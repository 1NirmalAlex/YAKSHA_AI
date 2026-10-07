"""
core/run_view.py
------------------------------------------------------------------------------
YAKSHA AI v2.0 — Dashboard view-models (pure logic, no Streamlit)

Everything the dashboard *derives* from raw data lives here so it can be unit
tested without a UI: per-agent status/latency/tokens, pipeline stage states,
overall run status, engine health, and the merged list of warnings/errors.

Inputs are plain data: Event objects (core.event_queue), CallRecord objects
(core.telemetry) and already-parsed artifact dicts.
------------------------------------------------------------------------------
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Optional

from core.event_queue import Event, EventType
from core.run_control import CANCEL_MESSAGE
from core.telemetry import CallRecord


@dataclass(frozen=True)
class AgentSpec:
    key: str
    label: str
    artifact: str
    language: str


AGENTS: list[AgentSpec] = [
    AgentSpec("pm_architect", "PM Architect", "requirements.json", "json"),
    AgentSpec("backend_dev", "Backend Dev", "backend.py", "python"),
    AgentSpec("frontend_dev", "Frontend Dev", "frontend.html", "html"),
    AgentSpec("ai_ml_specialist", "AI/ML Specialist", "ai_ml_module.py", "python"),
    AgentSpec("qa_reviewer", "QA Reviewer", "qa_report.json", "json"),
]
DEV_KEYS = ("backend_dev", "frontend_dev", "ai_ml_specialist")

PROVIDER_LABELS = {"gemini": "Gemini", "groq": "Groq"}


def parse_ts(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp()


def fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m {secs:02d}s"


def fmt_tokens(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 10_000 else f"{n:,}"


def provider_label(provider: str) -> str:
    return PROVIDER_LABELS.get(provider, provider or "—")


# ------------------------------------------------------------------------
# Per-agent view
# ------------------------------------------------------------------------

@dataclass
class AgentView:
    key: str
    label: str
    artifact: str
    language: str
    status: str = "pending"          # pending | running | done | skipped | failed | cancelled
    started_ts: Optional[float] = None
    finished_ts: Optional[float] = None
    duration_s: float = 0.0
    tokens: int = 0
    calls: int = 0
    failed_calls: int = 0
    avg_latency_s: float = 0.0
    models: list[str] = field(default_factory=list)
    last_message: str = ""
    events: list[Event] = field(default_factory=list)


def build_agent_views(
    events: Iterable[Event], calls: Iterable[CallRecord], now: Optional[float] = None
) -> list[AgentView]:
    now = now if now is not None else time.time()
    events, calls = list(events), list(calls)
    views: list[AgentView] = []

    for spec in AGENTS:
        v = AgentView(spec.key, spec.label, spec.artifact, spec.language)
        for e in events:
            if e.agent_role != spec.key:
                continue
            v.events.append(e)
            v.last_message = e.message
            ts = parse_ts(e.timestamp)
            if e.type == EventType.AGENT_STARTED:
                v.status, v.started_ts, v.finished_ts = "running", ts, None
            elif e.type == EventType.AGENT_COMPLETED:
                v.status = "skipped" if "skipped" in e.message.lower() else "done"
                v.finished_ts = ts
            elif e.type == EventType.AGENT_FAILED:
                v.status = "cancelled" if CANCEL_MESSAGE.lower() in e.message.lower() else "failed"
                v.finished_ts = ts

        if v.started_ts is not None:
            end = v.finished_ts if v.finished_ts is not None else now
            v.duration_s = max(0.0, end - v.started_ts)

        agent_calls = [c for c in calls if c.role == spec.key]
        ok = [c for c in agent_calls if c.ok]
        v.calls = len(ok)
        v.failed_calls = len(agent_calls) - len(ok)
        v.tokens = sum(c.tokens for c in ok)
        v.avg_latency_s = round(sum(c.latency_s for c in ok) / len(ok), 2) if ok else 0.0
        v.models = sorted({c.model for c in ok})
        views.append(v)
    return views


# ------------------------------------------------------------------------
# Pipeline stages + overall status
# ------------------------------------------------------------------------

_TERMINAL = {
    EventType.RUN_COMPLETED: ("Completed", "ok"),
    EventType.RUN_FAILED: ("Failed", "err"),
    EventType.RUN_CANCELLED: ("Cancelled", "warn"),
}


def terminal_event(events: Iterable[Event]) -> Optional[Event]:
    last = None
    for e in events:
        if e.type in _TERMINAL:
            last = e
    return last


def run_status(events: list[Event], control_state: Optional[str], alive: bool) -> tuple[str, str]:
    """Returns (label, tone) where tone is one of: live, ok, warn, err, muted."""
    end = terminal_event(events)
    if end is not None and not alive:
        return _TERMINAL[end.type]
    if control_state == "cancelled" and alive:
        return "Cancelling…", "warn"
    if control_state == "paused":
        return "Paused", "warn"
    if alive or any(e.type == EventType.RUN_STARTED for e in events):
        return ("Running", "live") if alive else ("Idle", "muted")
    return "Idle", "muted"


def stage_states(events: list[Event], views: list[AgentView]) -> list[tuple[str, str]]:
    by_key = {v.key: v for v in views}
    dev = [by_key[k] for k in DEV_KEYS]

    if any(v.status in ("failed",) for v in dev):
        build = "failed"
    elif any(v.status == "cancelled" for v in dev):
        build = "cancelled"
    elif any(v.status == "running" for v in dev):
        build = "running"
    elif all(v.status in ("done", "skipped") for v in dev):
        build = "done"
    elif any(v.status in ("done", "skipped") for v in dev):
        build = "running"
    else:
        build = "pending"

    asm = "pending"
    for e in events:
        if e.type == EventType.ASSEMBLY_STARTED:
            asm = "running"
        elif e.type == EventType.ASSEMBLY_COMPLETED:
            asm = "done"
        elif e.type == EventType.AGENT_FAILED and e.agent_role == "assembly_engine":
            asm = "failed"

    stages = [
        ("Plan", by_key["pm_architect"].status),
        ("Build", build),
        ("Assemble", asm),
        ("QA review", by_key["qa_reviewer"].status),
    ]
    end = terminal_event(events)
    if end is not None and end.type in (EventType.RUN_CANCELLED, EventType.RUN_FAILED):
        fallback = "cancelled" if end.type == EventType.RUN_CANCELLED else "failed"
        stages = [(n, fallback if s == "running" else s) for n, s in stages]
    return stages


# ------------------------------------------------------------------------
# Engine health
# ------------------------------------------------------------------------

def compute_health(
    calls: list[CallRecord], keys_present: dict[str, bool], demo: bool
) -> tuple[str, str, str]:
    """Returns (label, tone, detail)."""
    if not demo and not any(keys_present.values()):
        return "Offline", "err", "No API keys configured"
    failed = [c for c in calls if not c.ok]
    if failed:
        return "Errors", "err", f"{len(failed)} LLM call(s) failed after all fallbacks"
    fallbacks = [c for c in calls if c.ok and (c.warnings or c.attempt > 1)]
    if fallbacks:
        return "Degraded", "warn", f"{len(fallbacks)} call(s) needed a retry or fallback model"
    return "Healthy", "ok", "All providers responding" if calls else "Ready"


# ------------------------------------------------------------------------
# Warnings & errors
# ------------------------------------------------------------------------

@dataclass(frozen=True)
class Issue:
    level: str      # "error" | "warning"
    source: str
    message: str


def collect_issues(
    events: Iterable[Event], calls: Iterable[CallRecord], qa_report: Optional[dict[str, Any]] = None
) -> list[Issue]:
    found: list[Issue] = []

    for e in events:
        if e.type in (EventType.AGENT_FAILED, EventType.RUN_FAILED):
            if CANCEL_MESSAGE.lower() not in e.message.lower():
                found.append(Issue("error", e.agent_role or "run", e.message))
        elif e.type == EventType.RUN_TIMEOUT:
            found.append(Issue("warning", "run", e.message))
        elif e.type == EventType.ASSEMBLY_COMPLETED:
            for w in (e.payload or {}).get("warnings", []):
                found.append(Issue("warning", "assembly_engine", w))

    for c in calls:
        if not c.ok:
            found.append(Issue("error", c.role, f"LLM call failed: {(c.error or '').splitlines()[0][:200]}"))
        else:
            for w in c.warnings:
                found.append(Issue("warning", c.role, w))
            if c.attempt > 1:
                found.append(Issue("warning", c.role, f"{c.model} needed {c.attempt} attempts"))

    if qa_report:
        for msg in qa_report.get("critical_issues", []):
            found.append(Issue("error", "qa_reviewer", msg))
        for msg in qa_report.get("warnings", []):
            found.append(Issue("warning", "qa_reviewer", msg))

    seen: set[tuple[str, str]] = set()
    unique: list[Issue] = []
    for issue in found:
        # QA re-lists assembly warnings with an "[assembly] " prefix — dedupe those.
        norm = issue.message.removeprefix("[assembly] ")
        if (issue.level, norm) in seen:
            continue
        seen.add((issue.level, norm))
        unique.append(issue)
    return unique


# ------------------------------------------------------------------------
# Exportable run report
# ------------------------------------------------------------------------

def build_run_report(
    run_id: str,
    prompt: str,
    status: str,
    elapsed_s: float,
    views: list[AgentView],
    calls: list[CallRecord],
    issues: list[Issue],
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "prompt": prompt,
        "status": status,
        "execution_seconds": round(elapsed_s, 2),
        "total_tokens": sum(c.tokens for c in calls if c.ok),
        "agents": [
            {
                "agent": v.key, "status": v.status, "duration_s": round(v.duration_s, 2),
                "tokens": v.tokens, "llm_calls": v.calls, "avg_latency_s": v.avg_latency_s,
                "models": v.models,
            }
            for v in views
        ],
        "llm_calls": [
            {
                "agent": c.role, "ok": c.ok, "provider": c.provider, "model": c.model,
                "tokens": c.tokens, "latency_s": c.latency_s, "attempt": c.attempt,
                "started_at": c.started_at, "error": c.error,
            }
            for c in calls
        ],
        "issues": [{"level": i.level, "source": i.source, "message": i.message} for i in issues],
    }