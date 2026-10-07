"""
dashboard.py
------------------------------------------------------------------------------
YAKSHA AI v2.0 — Streamlit Dashboard

Run with:   streamlit run dashboard.py

Wires a Streamlit UI directly to the real pipeline — the SAME
YakshaOrchestrator, EventBus, TelemetryStore, ArtifactManager and
GeneratedAppRunner that main.py's CLI and the test suite use. There is no
separate "UI data layer" with its own copy of pipeline logic; view-model
shaping lives in core/run_view.py and is shared with anything else that
wants to render a run (a future API, a notebook, etc.).

Live updates use st.fragment(run_every=...) so the sidebar metrics, the
status/agent cards, and the Playground poll on their own without a full-page
rerun; the chat transcript lives in the same fragment as its own echo logic
so newly-appended messages (QA verdict, completion, etc.) appear on the next
tick without disturbing the chat_input widget, which stays outside the
fragment so typing is never interrupted by a refresh.
------------------------------------------------------------------------------
"""

from __future__ import annotations

try:
    from dotenv import load_dotenv

    load_dotenv()  # before any `core` import — core.config reads API keys at import time
except ImportError:
    pass

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import streamlit as st

from core.app_runner import GeneratedAppRunner
from core.artifact_manager import ArtifactError
from core.config import API_KEYS, EVENT_QUEUE, MODEL_ROUTES
from core.event_queue import Event, EventType
from core.llm_router import llm_router
from core.run_view import (
    AGENTS,
    DEV_KEYS,
    build_agent_views,
    build_run_report,
    collect_issues,
    compute_health,
    fmt_duration,
    fmt_tokens,
    provider_label,
    run_status,
    stage_states,
)
from core.telemetry import InstrumentedRouter, TelemetryStore
from main import PipelineError, YakshaOrchestrator, _demo_router

st.set_page_config(
    page_title="YAKSHA AI — v2.0", page_icon="⚡", layout="wide",
    initial_sidebar_state="expanded",
)

STATUS_TONE = {
    "pending": "muted", "running": "live", "done": "ok", "skipped": "muted",
    "failed": "err", "cancelled": "warn",
}
LANG_BY_EXT = {".py": "python", ".json": "json", ".html": "html", ".log": "text", ".txt": "text"}


# ==========================================================================
# Theme — dark, rounded-card SaaS aesthetic (lime accent), not cyberpunk
# ==========================================================================

def inject_css() -> None:
    st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {
  --bg: #0a0b0c; --bg-elev: #141617; --bg-elev-2: #1c1f20;
  --border: rgba(255,255,255,0.08); --text: #f3f5f1; --text-muted: #8f9890;
  --lime: #c6ff3d; --lime-dim: rgba(198,255,61,0.14);
  --red: #ff6b6b; --red-dim: rgba(255,107,107,0.14);
  --amber: #ffbe5c; --amber-dim: rgba(255,190,92,0.14);
}
html, body, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
  background: var(--bg) !important; color: var(--text);
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}
[data-testid="stHeader"] { background: transparent !important; }
[data-testid="stSidebar"] { background: var(--bg-elev) !important; border-right: 1px solid var(--border); }
[data-testid="stSidebar"] * { color: var(--text) !important; }
h1,h2,h3,h4 { font-weight: 700 !important; letter-spacing: -0.02em; }
p, span, label, div { color: var(--text); }
.yk-muted { color: var(--text-muted) !important; }

div[class*="st-key-metric_"], div[class*="st-key-agentcard_"],
div[class*="st-key-panel_"], div[class*="st-key-gauge_"] {
  background: var(--bg-elev); border: 1px solid var(--border);
  border-radius: 18px; padding: 18px 22px; margin-bottom: 4px;
}
div[class*="st-key-agentcard_"] { transition: border-color .15s ease; }
div[class*="st-key-agentcard_"]:hover { border-color: rgba(198,255,61,0.4); }

.stButton>button, .stDownloadButton>button {
  border-radius: 999px !important; border: 1px solid var(--border) !important;
  background: var(--bg-elev-2) !important; color: var(--text) !important; font-weight: 600 !important;
}
.stButton>button:hover { border-color: var(--lime) !important; color: var(--lime) !important; }
.stButton>button[kind="primary"] { background: var(--lime) !important; color: #0a0b0c !important; border: none !important; }
.stButton>button[kind="primary"]:hover { filter: brightness(1.1); }
.stButton>button:disabled { opacity: .35 !important; }

.yk-badge { display:inline-flex; align-items:center; gap:7px; padding:4px 13px; border-radius:999px; font-size:12.5px; font-weight:600; white-space:nowrap; }
.yk-badge.ok { background: var(--lime-dim); color: var(--lime); }
.yk-badge.live { background: var(--lime-dim); color: var(--lime); animation: yk-pulse 1.4s infinite; }
.yk-badge.err { background: var(--red-dim); color: var(--red); }
.yk-badge.warn { background: var(--amber-dim); color: var(--amber); }
.yk-badge.muted { background: rgba(255,255,255,0.06); color: var(--text-muted); }
.yk-dot { width:7px; height:7px; border-radius:50%; display:inline-block; }
.yk-dot.ok,.yk-dot.live{background:var(--lime);} .yk-dot.err{background:var(--red);}
.yk-dot.warn{background:var(--amber);} .yk-dot.muted{background:#5a615b;}
@keyframes yk-pulse { 0%,100%{opacity:1;} 50%{opacity:.5;} }

.yk-stage { display:flex; align-items:center; gap:8px; padding:10px 16px; border-radius:14px; background: var(--bg-elev-2); border:1px solid var(--border); flex:1; }
.yk-stage .n { font-weight:700; font-size:13px; }
.yk-stage .l { font-size:12.5px; color: var(--text-muted); }

[data-testid="stProgress"] > div > div > div { background: var(--lime) !important; }
[data-testid="stCodeBlock"] { border-radius: 12px; border: 1px solid var(--border); }
[data-testid="stChatMessage"] { background: var(--bg-elev-2); border-radius: 16px; border: 1px solid var(--border); }
[data-testid="stMetricValue"] { color: var(--text) !important; font-size: 1.5rem !important; }
[data-testid="stMetricLabel"] { color: var(--text-muted) !important; }

[data-baseweb="tab-list"] { gap: 6px; background: var(--bg-elev-2); padding: 6px; border-radius: 999px; width: fit-content; }
[data-baseweb="tab"] { border-radius: 999px !important; color: var(--text-muted) !important; padding: 6px 18px !important; }
[data-baseweb="tab"][aria-selected="true"] { background: var(--lime) !important; color: #0a0b0c !important; }
[data-baseweb="tab-highlight"], [data-baseweb="tab-border"] { display: none !important; }
hr { border-color: var(--border) !important; }
</style>
""", unsafe_allow_html=True)


def badge(label: str, tone: str) -> str:
    return f'<span class="yk-badge {tone}"><span class="yk-dot {tone}"></span>{label}</span>'


# ==========================================================================
# Shared process-wide state (survives Streamlit reruns; one per demo/live mode)
# ==========================================================================

@dataclass
class DashboardState:
    orchestrator: YakshaOrchestrator
    telemetry: TelemetryStore
    app_runner: GeneratedAppRunner = field(default_factory=GeneratedAppRunner)
    event_log: dict[str, list[Event]] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def pump(self, run_id: str) -> list[Event]:
        """Drains any new events into the persistent log and returns the full log so far."""
        with self.lock:
            log = self.event_log.setdefault(run_id, [])
            log.extend(self.orchestrator.event_bus.drain(run_id))
            return list(log)


@st.cache_resource(show_spinner=False)
def get_state(demo: bool) -> DashboardState:
    store = TelemetryStore()
    base_router = _demo_router() if demo else llm_router
    orchestrator = YakshaOrchestrator(
        router=InstrumentedRouter(base_router, store), use_llm_qa_review=True
    )
    return DashboardState(orchestrator=orchestrator, telemetry=store)


def archived_status(state: DashboardState, run_id: str) -> tuple[str, str]:
    """Status derived from artifacts on disk — works even after a server restart
    wiped in-memory events, since ArtifactManager just reads files."""
    am = state.orchestrator.manager
    try:
        qa = json.loads(am.read_artifact(run_id, "qa_report.json"))
        return ("Completed", "ok") if qa.get("passed") else ("Failed QA", "err")
    except (ArtifactError, json.JSONDecodeError):
        pass
    if am.artifact_exists(run_id, "assembly_report.json"):
        return "Assembled", "warn"
    if am.artifact_exists(run_id, "requirements.json"):
        return "Incomplete", "muted"
    return "Unknown", "muted"


# ==========================================================================
# Session state
# ==========================================================================

def init_session() -> None:
    ss = st.session_state
    ss.setdefault("chat", [])
    ss.setdefault("chat_echo_seq", {})
    ss.setdefault("run_handles", {})
    ss.setdefault("active_run_id", st.query_params.get("run"))
    ss.setdefault("playground_risk_ack", False)
    ss.setdefault("explorer_run_id", None)
    ss.setdefault("show_modify_form", False)


def set_active_run(run_id: Optional[str]) -> None:
    st.session_state.active_run_id = run_id
    if run_id:
        st.query_params["run"] = run_id
    else:
        st.query_params.pop("run", None)


def is_alive(run_id: Optional[str]) -> bool:
    handle = st.session_state.run_handles.get(run_id) if run_id else None
    return bool(handle and handle.is_alive())


# ==========================================================================
# Sidebar — system metrics + run history
# ==========================================================================

@st.fragment(run_every=1.5)
def sidebar_metrics(state: DashboardState, demo: bool) -> None:
    run_id = st.session_state.active_run_id
    events = state.pump(run_id) if run_id else []
    calls = state.telemetry.calls(run_id) if run_id else []
    alive = is_alive(run_id)
    control = state.orchestrator.get_control(run_id) if run_id else None

    label, tone = run_status(events, control.state if control else None, alive) if run_id else ("No active run", "muted")
    st.markdown("##### 📊 System Metrics")
    st.markdown(badge(label, tone), unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    c1.metric("Tokens used", fmt_tokens(sum(c.tokens for c in calls if c.ok)))
    elapsed = control.elapsed_seconds() if control else 0.0
    c2.metric("Run time", fmt_duration(elapsed) if run_id else "—")

    latest_ok = next((c for c in reversed(calls) if c.ok), None)
    st.caption("Active provider")
    st.markdown(
        badge(f"{provider_label(latest_ok.provider)} · {latest_ok.model}", "ok") if latest_ok
        else badge("—", "muted"),
        unsafe_allow_html=True,
    )

    keys_present = {"gemini": bool(API_KEYS.get("gemini")), "groq": bool(API_KEYS.get("groq"))}
    health_label, health_tone, health_detail = compute_health(calls, keys_present, demo)
    st.caption("Engine health")
    st.markdown(badge(health_label, health_tone), unsafe_allow_html=True)
    st.caption(health_detail)

    st.markdown("<br>", unsafe_allow_html=True)
    st.caption("Provider TPM budget (last 60s)")
    for provider in ("gemini", "groq"):
        limit = max(
            (mc.tpm_limit for chain in MODEL_ROUTES.values() for mc in chain if mc.provider == provider),
            default=0,
        )
        used = state.telemetry.tokens_last_minute(provider)
        pct = min(1.0, used / limit) if limit else 0.0
        st.caption(f"{provider_label(provider)} — {fmt_tokens(used)} / {fmt_tokens(limit)}")
        st.progress(pct)

    st.divider()
    st.markdown("##### 🗂️ Run history")
    runs = state.orchestrator.manager.list_runs()[:12]
    if not runs:
        st.caption("No runs yet — start one from the Chat tab.")
    for rid in runs:
        rlabel, rtone = (
            run_status(state.event_log.get(rid, []), None, is_alive(rid))
            if rid in state.event_log else archived_status(state, rid)
        )
        cols = st.columns([3, 1])
        if cols[0].button(f"{rid[:8]}…", key=f"hist_{rid}", use_container_width=True):
            set_active_run(rid)
            st.rerun()
        cols[1].markdown(badge(rlabel, rtone), unsafe_allow_html=True)


# ==========================================================================
# Chat + status + stage tracker + controls (one fragment: ticking + chat log)
# ==========================================================================

def start_run(state: DashboardState, prompt: str) -> None:
    st.session_state.chat.append({"role": "user", "content": prompt})
    run_id = st.session_state.active_run_id
    if is_alive(run_id):
        st.session_state.chat.append({
            "role": "assistant",
            "content": "⏳ A run is already in progress — pause or cancel it first, "
                       "or wait for it to finish before starting a new one.",
        })
        return
    try:
        handle = state.orchestrator.start(prompt)
    except PipelineError as exc:
        st.session_state.chat.append({"role": "assistant", "content": f"⚠️ Couldn't start: {exc}"})
        return
    st.session_state.run_handles[handle.run_id] = handle
    set_active_run(handle.run_id)
    st.session_state.chat.append({
        "role": "assistant",
        "content": f"🚀 Got it — kicking off the crew. Run `{handle.run_id[:8]}` started.",
    })


def echo_events_to_chat(state: DashboardState, run_id: str, events: list[Event]) -> None:
    last = st.session_state.chat_echo_seq.get(run_id, 0)
    fresh = [e for e in events if e.sequence > last]
    am = state.orchestrator.manager
    for e in fresh:
        if e.type == EventType.AGENT_COMPLETED and e.agent_role == "pm_architect" and "skipped" not in e.message.lower():
            try:
                reqs = json.loads(am.read_artifact(run_id, "requirements.json"))
                lines = [f"📋 Plan ready — **{reqs['app_name']}**", f"- Backend: {reqs['backend_brief']}",
                         f"- Frontend: {reqs['frontend_brief']}"]
                if reqs.get("needs_ai_ml"):
                    lines.append(f"- AI/ML: {reqs['ai_ml_brief']}")
                st.session_state.chat.append({"role": "assistant", "content": "\n".join(lines)})
            except (ArtifactError, json.JSONDecodeError):
                pass
        elif e.type == EventType.QA_REPORT_READY:
            passed = (e.payload or {}).get("passed")
            st.session_state.chat.append({
                "role": "assistant",
                "content": ("✅ QA passed — the app looks good." if passed else "❌ QA flagged issues — see the Agents tab."),
            })
        elif e.type == EventType.RUN_COMPLETED:
            st.session_state.chat.append({"role": "assistant", "content": "🏁 Done! Open the Playground tab to run your app."})
            st.toast("Run completed", icon="⚡")
        elif e.type == EventType.RUN_FAILED:
            st.session_state.chat.append({"role": "assistant", "content": f"💥 The run failed: {e.message}"})
            st.toast("Run failed", icon="🛑")
        elif e.type == EventType.RUN_CANCELLED:
            st.session_state.chat.append({"role": "assistant", "content": "⏹️ Run cancelled."})
            st.toast("Run cancelled", icon="⏹️")
    if fresh:
        st.session_state.chat_echo_seq[run_id] = fresh[-1].sequence


@st.fragment(run_every=1.2)
def run_cockpit(state: DashboardState) -> None:
    run_id = st.session_state.active_run_id

    for msg in st.session_state.chat:
        with st.chat_message(msg["role"], avatar="⚡" if msg["role"] == "assistant" else None):
            st.markdown(msg["content"])

    if not run_id:
        st.caption("No run yet — describe an app below to get started.")
        return

    events = state.pump(run_id)
    echo_events_to_chat(state, run_id, events)
    calls = state.telemetry.calls(run_id)
    alive = is_alive(run_id)
    control = state.orchestrator.get_control(run_id)
    views = build_agent_views(events, calls)

    label, tone = run_status(events, control.state if control else None, alive)
    st.markdown(f"**Run** `{run_id[:8]}` &nbsp; {badge(label, tone)}", unsafe_allow_html=True)

    cols = st.columns(4)
    for col, (name, status) in zip(cols, stage_states(events, views)):
        stone = STATUS_TONE.get(status, "muted")
        col.markdown(
            f'<div class="yk-stage"><span class="yk-dot {stone}"></span>'
            f'<div><div class="n">{name}</div><div class="l">{status}</div></div></div>',
            unsafe_allow_html=True,
        )

    if alive and control:
        bc1, bc2, bc3 = st.columns(3)
        if control.state == "running":
            if bc1.button("⏸️ Pause", key="pause_btn", use_container_width=True):
                state.orchestrator.pause(run_id)
                st.rerun()  # the status badge above was already drawn with the pre-click state
        elif control.state == "paused":
            if bc1.button("▶️ Resume", key="resume_btn", use_container_width=True, type="primary"):
                state.orchestrator.resume(run_id)
                st.rerun()
        if bc2.button("⏹️ Stop", key="cancel_btn", use_container_width=True, disabled=control.state == "cancelled"):
            state.orchestrator.cancel(run_id)
            st.rerun()
        bc3.caption(f"⏱️ {fmt_duration(control.elapsed_seconds())} elapsed" + (" (paused)" if control.state == "paused" else ""))
    elif not alive and run_id:
        bc1, bc2 = st.columns([1, 3])
        if bc1.button("✏️ Modify & re-run", key="modify_btn", use_container_width=True):
            st.session_state.show_modify_form = True

    issues = collect_issues(events, calls, _safe_qa_report(state, run_id))
    errs = [i for i in issues if i.level == "error"]
    warns = [i for i in issues if i.level == "warning"]
    if errs or warns:
        with st.expander(f"⚠️ Issues ({len(errs)} error, {len(warns)} warning)", expanded=bool(errs)):
            for i in errs:
                st.markdown(badge(f"{i.source}", "err") + f" &nbsp; {i.message}", unsafe_allow_html=True)
            for i in warns:
                st.markdown(badge(f"{i.source}", "warn") + f" &nbsp; {i.message}", unsafe_allow_html=True)

    if st.session_state.show_modify_form:
        render_modify_form(state, run_id)


def _safe_qa_report(state: DashboardState, run_id: str) -> Optional[dict]:
    try:
        return json.loads(state.orchestrator.manager.read_artifact(run_id, "qa_report.json"))
    except (ArtifactError, json.JSONDecodeError):
        return None


def render_modify_form(state: DashboardState, run_id: str) -> None:
    try:
        reqs = json.loads(state.orchestrator.manager.read_artifact(run_id, "requirements.json"))
    except (ArtifactError, json.JSONDecodeError):
        st.warning("No requirements.json to edit for this run.")
        st.session_state.show_modify_form = False
        return

    with st.form(f"modify_{run_id}"):
        st.markdown("###### Edit requirements and start a new run (planning is skipped)")
        app_name = st.text_input("App name", reqs.get("app_name", ""))
        backend_brief = st.text_area("Backend brief", reqs.get("backend_brief", ""), height=90)
        frontend_brief = st.text_area("Frontend brief", reqs.get("frontend_brief", ""), height=90)
        needs_ai_ml = st.checkbox("Needs AI/ML module", bool(reqs.get("needs_ai_ml")))
        ai_ml_brief = st.text_area("AI/ML brief", reqs.get("ai_ml_brief") or "", height=70, disabled=not needs_ai_ml)
        c1, c2 = st.columns(2)
        submit = c1.form_submit_button("🔁 Re-run with these edits", type="primary", use_container_width=True)
        cancel = c2.form_submit_button("Cancel", use_container_width=True)

    if cancel:
        st.session_state.show_modify_form = False
        st.rerun()
    if submit:
        edited = {**reqs, "app_name": app_name, "backend_brief": backend_brief,
                  "frontend_brief": frontend_brief, "needs_ai_ml": needs_ai_ml,
                  "ai_ml_brief": ai_ml_brief if needs_ai_ml else None}
        try:
            handle = state.orchestrator.start("", requirements=edited)
        except PipelineError as exc:
            st.error(f"Couldn't start: {exc}")
            return
        st.session_state.run_handles[handle.run_id] = handle
        set_active_run(handle.run_id)
        st.session_state.show_modify_form = False
        st.session_state.chat.append({
            "role": "assistant",
            "content": f"🔁 Re-running with your edits. Run `{handle.run_id[:8]}` started.",
        })
        st.rerun()


# ==========================================================================
# Agent breakdown tab
# ==========================================================================

@st.fragment(run_every=1.5)
def agents_panel(state: DashboardState) -> None:
    run_id = st.session_state.active_run_id
    if not run_id:
        st.caption("Start a run from the Chat tab to see agent activity here.")
        return

    events = state.pump(run_id)
    calls = state.telemetry.calls(run_id)
    views = build_agent_views(events, calls)
    am = state.orchestrator.manager

    cols = st.columns(len(views))
    for col, v in zip(cols, views):
        with col:
            with st.container(key=f"agentcard_{v.key}", border=False):
                st.markdown(f"**{v.label}**")
                st.markdown(badge(v.status, STATUS_TONE.get(v.status, "muted")), unsafe_allow_html=True)
                st.caption(f"⏱️ {fmt_duration(v.duration_s)}  ·  🔤 {fmt_tokens(v.tokens)} tok  ·  📡 {v.calls} call(s)")
                if v.avg_latency_s:
                    st.caption(f"avg latency {v.avg_latency_s}s" + (f" · {', '.join(v.models)}" if v.models else ""))
                if v.last_message:
                    st.caption(v.last_message[:90])

    st.divider()
    selected = st.tabs([v.label for v in views])
    for tab, v in zip(selected, views):
        with tab:
            agent_calls = [c for c in calls if c.role == v.key]
            if v.status == "skipped":
                st.info("Skipped — not needed for this app.")
            elif not agent_calls:
                st.caption("No activity yet.")
            else:
                for i, c in enumerate(agent_calls, 1):
                    with st.expander(
                        f"Call {i} · {provider_label(c.provider)}/{c.model} · {c.latency_s}s · "
                        f"{fmt_tokens(c.tokens)} tok" + ("" if c.ok else " · FAILED"),
                        expanded=(i == len(agent_calls)),
                    ):
                        st.caption("Prompt sent")
                        st.code(c.prompt, language="text", height=160)
                        if c.ok:
                            st.caption("Response")
                            st.code(c.response, language="text", height=160)
                        else:
                            st.error(c.error or "unknown error")
                        if c.warnings:
                            for w in c.warnings:
                                st.caption(f"⚠️ {w}")

            if am.artifact_exists(run_id, v.artifact):
                st.caption(f"Artifact: `{v.artifact}`")
                st.code(am.read_artifact(run_id, v.artifact), language=LANG_BY_EXT.get(Path(v.artifact).suffix, "text"), height=240)


# ==========================================================================
# Playground tab — run the generated app
# ==========================================================================

@st.fragment(run_every=1.5)
def playground_panel(state: DashboardState) -> None:
    run_id = st.session_state.active_run_id
    if not run_id:
        st.caption("Build an app first — then run it here with one click.")
        return

    am = state.orchestrator.manager
    if not am.artifact_exists(run_id, "assembly_report.json"):
        st.caption("This run hasn't produced a buildable app yet.")
        return
    report = json.loads(am.read_artifact(run_id, "assembly_report.json"))
    app_path = Path(report["output_path"])

    runner = state.app_runner
    st_state = runner.state()
    is_this_run = st_state.run_id == run_id and st_state.status in ("starting", "running")

    if not st.session_state.playground_risk_ack:
        st.warning(
            "⚠️ Starting a generated app EXECUTES LLM-written code on this machine. "
            "Review the Backend/AI-ML tabs in **Agents** first if you don't trust the output."
        )
        if st.button("I understand — enable Playground", key="risk_ack"):
            st.session_state.playground_risk_ack = True
            st.rerun()
        return

    c1, c2, c3 = st.columns([1, 1, 2])
    if c1.button("▶️ Start app", type="primary", use_container_width=True,
                 disabled=st_state.status in ("starting", "running")):
        runner.start(run_id, app_path, report.get("flask_app_var", "app"))
        st.rerun()
    if c2.button("⏹️ Stop app", use_container_width=True, disabled=st_state.status not in ("starting", "running")):
        runner.stop()
        st.rerun()

    st_state = runner.state()
    tone = {"running": "ok", "starting": "warn", "crashed": "err", "stopped": "muted"}[st_state.status]
    c3.markdown(badge(st_state.status, tone) + (f" &nbsp; `{st_state.url}`" if st_state.url else ""), unsafe_allow_html=True)

    if st_state.status == "running" and is_this_run:
        colp, _ = st.columns([1, 3])
        if colp.button("🩺 Smoke test (GET /)", key="probe_btn"):
            code, ms, err = runner.probe("/")
            if err:
                st.error(f"Request failed: {err}")
            else:
                st.success(f"HTTP {code} in {ms}ms")
        st.caption("Live preview")
        st.iframe(st_state.url, height=480)
    elif st_state.status == "crashed":
        st.error(f"The app crashed (exit code {st_state.returncode}). Server log:")
        st.code(runner.log_tail(60), language="text", height=200)
    elif st_state.status == "starting":
        st.info("Starting…")

    with st.expander("Server log"):
        st.code(runner.log_tail(60) or "(empty)", language="text", height=200)


# ==========================================================================
# Artifact explorer tab
# ==========================================================================

def artifacts_panel(state: DashboardState) -> None:
    am = state.orchestrator.manager
    runs = am.list_runs()
    if not runs:
        st.caption("No runs yet.")
        return

    default_idx = runs.index(st.session_state.active_run_id) if st.session_state.active_run_id in runs else 0
    run_id = st.selectbox("Run", runs, index=default_idx, format_func=lambda r: r[:12] + "…")
    st.session_state.explorer_run_id = run_id

    artifacts = am.list_artifacts(run_id)
    entries = [(a.filename, a.size_bytes) for a in artifacts if not a.filename.startswith("_")]
    final_app = Path("project_files") / run_id / "app.py"
    if final_app.exists():
        entries.append((f"⭐ app.py (assembled)", final_app.stat().st_size))

    if not entries:
        st.caption("No artifacts saved for this run yet.")
        return

    labels = [f"{name}  ·  {size:,} B" for name, size in entries]
    pick = st.radio("Files", labels, label_visibility="collapsed")
    chosen_name = entries[labels.index(pick)][0]

    if chosen_name.startswith("⭐"):
        content = final_app.read_text(encoding="utf-8")
        lang = "python"
    else:
        content = am.read_artifact(run_id, chosen_name)
        lang = LANG_BY_EXT.get(Path(chosen_name).suffix, "text")

    st.code(content, language=lang, height=420)
    st.download_button("⬇️ Download file", content, file_name=chosen_name.replace("⭐ ", ""), use_container_width=False)

    events = state.event_log.get(run_id, [])
    calls = state.telemetry.calls(run_id)
    if events or calls:
        views = build_agent_views(events, calls)
        issues = collect_issues(events, calls, _safe_qa_report(state, run_id))
        control = state.orchestrator.get_control(run_id)
        label, _ = run_status(events, control.state if control else None, is_alive(run_id))
        report = build_run_report(run_id, "", label, control.elapsed_seconds() if control else 0.0, views, calls, issues)
        st.download_button(
            "⬇️ Download full run report (JSON)", json.dumps(report, indent=2),
            file_name=f"yaksha_run_{run_id[:8]}_report.json", key="dl_report",
        )


# ==========================================================================
# Main
# ==========================================================================

QUICK_IDEAS = {
    "📝 Todo list": "Build a todo list app with add, complete, and delete tasks.",
    "💰 Expense tracker": "Build an expense tracker that auto-categorizes spending by keyword.",
    "⏱️ Pomodoro timer": "Build a pomodoro timer with work/break cycles and a session log.",
    "📋 Habit tracker": "Build a habit tracker with daily check-ins and streaks.",
}


def main() -> None:
    inject_css()
    init_session()

    st.sidebar.markdown("### ⚡ YAKSHA AI")
    st.sidebar.caption("v2.0 — Autonomous Engineering Studio")
    demo = st.sidebar.toggle(
        "🧪 Demo mode (offline, fake LLM)",
        value=not (API_KEYS.get("gemini") or API_KEYS.get("groq")),
        help="No Gemini/Groq keys configured yet? Flip this on to try the full pipeline with a scripted fake LLM.",
    )
    state = get_state(demo)
    sidebar_metrics(state, demo)

    st.markdown("## ⚡ YAKSHA AI Studio")
    st.caption("Describe an app once — PM plans it, Backend/Frontend/AI-ML build it in parallel, QA reviews it.")

    tab_chat, tab_agents, tab_play, tab_files = st.tabs(["💬 Chat & Status", "🤖 Agents", "🚀 Playground", "📁 Artifacts"])

    with tab_chat:
        run_cockpit(state)
        qcols = st.columns(len(QUICK_IDEAS))
        clicked = None
        for col, (label, text) in zip(qcols, QUICK_IDEAS.items()):
            if col.button(label, key=f"quick_{label}", use_container_width=True):
                clicked = text
        prompt = st.chat_input("Describe the app you want to build…") or clicked
        if prompt:
            start_run(state, prompt)
            st.rerun()

    with tab_agents:
        agents_panel(state)

    with tab_play:
        playground_panel(state)

    with tab_files:
        artifacts_panel(state)


if __name__ == "__main__":
    main()