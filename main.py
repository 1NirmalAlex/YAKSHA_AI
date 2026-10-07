"""
main.py
------------------------------------------------------------------------------
YAKSHA AI v2.0 — Pipeline Orchestrator

Runs the full v2.0 workflow for one user prompt:

    1. PM & System Architect   -> requirements.json
    2. Backend + Frontend + AI/ML developers, IN PARALLEL
                               -> backend.py, frontend.html, ai_ml_module.py
    3. Assembly Engine         -> project_files/<run_id>/app.py   (pure Python)
    4. QA Reviewer             -> qa_report.json                  (read-only)

Every stage publishes events to the EventBus, so any UI (Streamlit) or the
CLI below can render live progress by draining the run's queue. The heavy
work always runs on a background thread (BackgroundExecutor), so callers
never block.

Library usage (e.g. from the Streamlit dashboard):

    orchestrator = YakshaOrchestrator()               # owns an EventBus
    handle = orchestrator.start("Build a habit tracker")
    ...
    for event in orchestrator.event_bus.drain(handle.run_id):
        render(event)
    if not handle.is_alive():
        result = orchestrator.get_result(handle.run_id)   # None if it failed

CLI usage:

    python main.py --prompt "Build a habit tracker with streak analytics"
    python main.py --demo            # offline run with a scripted fake LLM
------------------------------------------------------------------------------
"""

from __future__ import annotations

# IMPORTANT: load .env BEFORE importing anything from `core`. core.config reads
# API keys from the environment at import time, so a later load_dotenv() would
# leave them empty.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional; plain environment variables still work
    pass

import argparse
import contextvars
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Optional

from agents.ai_ml_specialist import AIMLSpecialistAgent
from agents.backend_dev import BackendDevAgent
from agents.frontend_dev import FrontendDevAgent
from agents.pm_architect import PMArchitectAgent
from agents.qa_reviewer import QAReviewerAgent
from core.artifact_manager import ArtifactManager, artifact_manager
from core.assembly_engine import AssemblyEngine
from core.config import ARTIFACT_REQUIREMENTS, EVENT_QUEUE
from core.event_queue import BackgroundExecutor, EventBus, EventType, RunHandle
from core.llm_router import LLMRouter, llm_router
from core.run_control import CANCEL_MESSAGE, RunCancelled, RunControl, current_control

logger = logging.getLogger("yaksha.orchestrator")

ORCHESTRATOR_ROLE = "orchestrator"
ASSEMBLY_ROLE = "assembly_engine"


class PipelineError(Exception):
    """Raised when any pipeline stage fails or QA rejects the assembled app."""


@dataclass
class PipelineResult:
    run_id: str
    app_name: str
    output_path: str
    qa_passed: bool
    warnings: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0


class YakshaOrchestrator:
    """
    Owns the pipeline. All collaborators are injectable, so the whole thing
    can be tested offline by handing it an LLMRouter with a fake completion_fn.
    """

    def __init__(
        self,
        manager: ArtifactManager = artifact_manager,
        router: LLMRouter = llm_router,
        event_bus: Optional[EventBus] = None,
        engine: Optional[AssemblyEngine] = None,
        use_llm_qa_review: bool = True,
    ) -> None:
        self.manager = manager
        self.router = router
        self.event_bus = event_bus or EventBus()
        self.engine = engine or AssemblyEngine(manager=manager)
        self.use_llm_qa_review = use_llm_qa_review
        self._executor = BackgroundExecutor(self.event_bus)
        self._results: dict[str, PipelineResult] = {}
        self._controls: dict[str, RunControl] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(
        self,
        user_prompt: str,
        run_id: Optional[str] = None,
        requirements: Optional[dict[str, Any]] = None,
    ) -> RunHandle:
        """
        Creates the run workspace and launches the pipeline on a background
        thread. Returns immediately with a handle (handle.run_id is what to
        drain events for). RUN_STARTED / RUN_COMPLETED / RUN_FAILED /
        RUN_CANCELLED are published by the BackgroundExecutor around it.

        If `requirements` is given (e.g. edited by the user after a previous
        run), planning is skipped and the pipeline starts from stage 2.
        """
        if requirements is not None:
            try:
                requirements = PMArchitectAgent._validate_and_normalize(requirements)
            except ValueError as exc:
                raise PipelineError(f"Invalid requirements: {exc}") from exc
        elif not user_prompt or not user_prompt.strip():
            raise PipelineError("Prompt is empty — describe the app you want to build.")

        run_id = self.manager.create_run(run_id)
        self._controls[run_id] = RunControl(run_id)
        return self._executor.run_in_background(
            run_id,
            self.run_pipeline,
            args=(run_id, (user_prompt or "").strip()),
            kwargs={"requirements": requirements},
        )

    def get_result(self, run_id: str) -> Optional[PipelineResult]:
        """The PipelineResult for a successfully finished run, else None."""
        return self._results.get(run_id)

    # -- run control (safe to call from any thread, e.g. the UI) ----------------

    def get_control(self, run_id: str) -> Optional[RunControl]:
        return self._controls.get(run_id)

    def pause(self, run_id: str) -> bool:
        control = self._controls.get(run_id)
        if control is not None and control.pause():
            self.event_bus.publish(
                run_id, EventType.RUN_PAUSED,
                "Run paused — LLM calls already in flight will finish first",
                agent_role=ORCHESTRATOR_ROLE,
            )
            return True
        return False

    def resume(self, run_id: str) -> bool:
        control = self._controls.get(run_id)
        if control is not None and control.resume():
            self.event_bus.publish(
                run_id, EventType.RUN_RESUMED, "Run resumed", agent_role=ORCHESTRATOR_ROLE
            )
            return True
        return False

    def cancel(self, run_id: str) -> bool:
        control = self._controls.get(run_id)
        if control is not None and control.cancel():
            self._progress(run_id, "Cancelling — waiting for in-flight LLM calls to finish")
            return True
        return False

    def run_pipeline(
        self,
        run_id: str,
        user_prompt: str,
        requirements: Optional[dict[str, Any]] = None,
    ) -> PipelineResult:
        """
        The synchronous pipeline body. Raises PipelineError (or the failing
        stage's own exception) on failure, RunCancelled if the user stopped it.
        Normally invoked via start(), but safe to call directly from an
        already-background context.
        """
        control = self._controls.get(run_id)
        if control is None:
            control = self._controls[run_id] = RunControl(run_id)
        token = current_control.set(control)
        try:
            return self._run_stages(run_id, user_prompt, requirements, control)
        except RunCancelled:
            raise
        except Exception as exc:
            # A cancel can surface wrapped in another exception type (e.g. an
            # agent's own error wrapper); normalise it so the run reports
            # "cancelled" rather than "failed".
            if control.is_cancelled:
                raise RunCancelled(CANCEL_MESSAGE) from exc
            raise
        finally:
            control.mark_finished()
            current_control.reset(token)

    def _run_stages(
        self,
        run_id: str,
        user_prompt: str,
        requirements: Optional[dict[str, Any]],
        control: RunControl,
    ) -> PipelineResult:
        started = time.monotonic()

        control.checkpoint()
        if requirements is None:
            self._progress(run_id, "Stage 1/4 — planning (PM & System Architect)")
            requirements = PMArchitectAgent(
                self.manager, self.router, self.event_bus
            ).run(run_id, user_prompt)
        else:
            self._progress(run_id, "Stage 1/4 — using your requirements (planning skipped)")
            self.manager.save_artifact(
                run_id, ARTIFACT_REQUIREMENTS, json.dumps(requirements, indent=2)
            )
            self.event_bus.publish(
                run_id, EventType.ARTIFACT_SAVED, "requirements.json saved (user-provided)",
                agent_role="pm_architect",
            )
            self.event_bus.publish(
                run_id, EventType.AGENT_COMPLETED,
                "PM & System Architect skipped — using user-provided requirements",
                agent_role="pm_architect",
            )

        control.checkpoint()
        self._progress(
            run_id,
            "Stage 2/4 — building in parallel (backend, frontend"
            + (", AI/ML)" if requirements.get("needs_ai_ml") else ")"),
        )
        self._run_developers_in_parallel(run_id)

        control.checkpoint()
        self._progress(run_id, "Stage 3/4 — assembling final app.py")
        assembly = self._assemble(run_id)

        control.checkpoint()
        self._progress(run_id, "Stage 4/4 — QA review")
        qa_report = QAReviewerAgent(
            self.manager, self.router, self.event_bus,
            project_files_dir=self.engine.output_root,
        ).run(run_id, use_llm_review=self.use_llm_qa_review)

        if not qa_report.passed:
            raise PipelineError(
                "QA rejected the assembled app: " + "; ".join(qa_report.critical_issues)
            )

        result = PipelineResult(
            run_id=run_id,
            app_name=requirements["app_name"],
            output_path=assembly.output_path,
            qa_passed=True,
            warnings=list(assembly.warnings) + list(qa_report.warnings),
            elapsed_seconds=round(time.monotonic() - started, 2),
        )
        self._results[run_id] = result
        return result

    # ------------------------------------------------------------------
    # Stages
    # ------------------------------------------------------------------

    def _run_developers_in_parallel(self, run_id: str) -> None:
        """
        Backend, Frontend and AI/ML agents share nothing except run_id and the
        read-only requirements.json, so they run concurrently. We always wait
        for all three to finish (a running LLM call can't be cancelled anyway),
        then report every failure together instead of only the first.
        """
        agents = {
            "backend_dev": BackendDevAgent(self.manager, self.router, self.event_bus),
            "frontend_dev": FrontendDevAgent(self.manager, self.router, self.event_bus),
            "ai_ml_specialist": AIMLSpecialistAgent(self.manager, self.router, self.event_bus),
        }
        errors: dict[str, Exception] = {}

        with ThreadPoolExecutor(
            max_workers=len(agents), thread_name_prefix=f"yaksha-dev-{run_id[:8]}"
        ) as pool:
            # Each worker needs its OWN copy of the context so the run's
            # RunControl (and thus pause/cancel + telemetry attribution)
            # follows the work onto the pool threads.
            futures = {
                pool.submit(contextvars.copy_context().run, agent.run, run_id): name
                for name, agent in agents.items()
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    future.result()
                except Exception as exc:  # noqa: BLE001 — each agent already published AGENT_FAILED
                    errors[name] = exc

        if any(isinstance(exc, RunCancelled) for exc in errors.values()):
            raise RunCancelled(CANCEL_MESSAGE)
        if errors:
            details = "; ".join(f"{name}: {exc}" for name, exc in errors.items())
            raise PipelineError(f"Developer stage failed — {details}")

    def _assemble(self, run_id: str):
        self.event_bus.publish(
            run_id, EventType.ASSEMBLY_STARTED, "Assembly Engine started",
            agent_role=ASSEMBLY_ROLE,
        )
        try:
            assembly = self.engine.assemble(run_id)
        except Exception as exc:
            self.event_bus.publish(
                run_id, EventType.AGENT_FAILED, f"Assembly Engine failed: {exc}",
                agent_role=ASSEMBLY_ROLE,
            )
            raise
        self.event_bus.publish(
            run_id, EventType.ASSEMBLY_COMPLETED, "app.py assembled",
            agent_role=ASSEMBLY_ROLE,
            payload={
                "output_path": assembly.output_path,
                "size_bytes": assembly.output_size_bytes,
                "warnings": assembly.warnings,
            },
        )
        return assembly

    def _progress(self, run_id: str, message: str) -> None:
        self.event_bus.publish(
            run_id, EventType.AGENT_PROGRESS, message, agent_role=ORCHESTRATOR_ROLE
        )


# ------------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------------

_ICONS = {
    EventType.RUN_STARTED: "🚀",
    EventType.AGENT_STARTED: "▶️ ",
    EventType.AGENT_PROGRESS: "📍",
    EventType.ARTIFACT_SAVED: "💾",
    EventType.AGENT_COMPLETED: "✅",
    EventType.AGENT_FAILED: "❌",
    EventType.ASSEMBLY_STARTED: "🧩",
    EventType.ASSEMBLY_COMPLETED: "🧩",
    EventType.QA_REPORT_READY: "🧪",
    EventType.RUN_TIMEOUT: "⏱️ ",
    EventType.RUN_PAUSED: "⏸️ ",
    EventType.RUN_RESUMED: "▶️ ",
    EventType.RUN_CANCELLED: "⏹️ ",
    EventType.RUN_COMPLETED: "🏁",
    EventType.RUN_FAILED: "💥",
}


def _print_event(event) -> None:
    clock = event.timestamp[11:19]
    role = f"[{event.agent_role}] " if event.agent_role else ""
    print(f"{clock}  {_ICONS.get(event.type, '•')} {role}{event.message}", flush=True)


def stream_to_console(orchestrator: YakshaOrchestrator, handle: RunHandle) -> int:
    """Drains the run's event queue live until the run ends. Returns an exit code."""
    failed_message: Optional[str] = None
    interrupted = False
    while handle.is_alive() or orchestrator.event_bus.pending_count(handle.run_id) > 0:
        try:
            for event in orchestrator.event_bus.drain(handle.run_id):
                _print_event(event)
                if event.type in (EventType.RUN_FAILED, EventType.RUN_CANCELLED):
                    failed_message = event.message
            time.sleep(EVENT_QUEUE.poll_interval_seconds)
        except KeyboardInterrupt:
            if interrupted:
                raise  # second Ctrl+C: stop waiting immediately
            interrupted = True
            print("\n⏹️  Ctrl+C — cancelling (in-flight LLM calls finish first; Ctrl+C again to quit now)")
            orchestrator.cancel(handle.run_id)
    handle.join()

    result = orchestrator.get_result(handle.run_id)
    print()
    if result is not None and failed_message is None:
        print(f"✨ Done in {result.elapsed_seconds}s — {result.app_name}")
        print(f"   Output: {result.output_path}")
        print(f"   Run it: python {result.output_path}")
        for warning in result.warnings:
            print(f"   ⚠️  {warning}")
        return 0
    print(f"Run {handle.run_id} did not complete. {failed_message or ''}")
    return 1


def _demo_router(delay: float = 0.4) -> LLMRouter:
    """A scripted fake LLM so the whole pipeline can be exercised with no API keys."""
    import json

    def fake_completion(model_cfg, messages, **kwargs):
        system = messages[0]["content"]
        time.sleep(delay)  # delay makes the parallel stage (and pause/stop) observable
        if "PM & System Architect" in system:
            return (json.dumps({
                "app_name": "Expense Tracker",
                "description": "Track expenses and auto-categorize them.",
                "backend_brief": "CRUD API at /api/expenses; classify each expense with ai_ml_module.classify_expense.",
                "frontend_brief": "A form to add an expense and a list showing each with its category.",
                "needs_ai_ml": True,
                "ai_ml_brief": "classify_expense(description) using simple keyword rules.",
            }), 100)
        if "Backend Developer" in system:
            return (
                "from flask import Flask, jsonify, request\n"
                "from ai_ml_module import classify_expense\n"
                "app = Flask(__name__)\nEXPENSES = []\n\n"
                "@app.route('/api/expenses', methods=['GET', 'POST'])\n"
                "def expenses():\n"
                "    if request.method == 'POST':\n"
                "        data = request.get_json()\n"
                "        data['category'] = classify_expense(data.get('description', ''))\n"
                "        EXPENSES.append(data)\n"
                "        return jsonify(data), 201\n"
                "    return jsonify(EXPENSES)\n", 150)
        if "Frontend Developer" in system:
            return (
                '<!DOCTYPE html><html><head><title>Expense Tracker</title>'
                '<script src="https://cdn.tailwindcss.com"></script></head>'
                '<body class="bg-slate-900 text-white p-8"><h1 class="text-2xl">Expenses</h1>'
                '<ul id="list"></ul><script>'
                "fetch('/api/expenses').then(r => r.json()).then(items => {"
                "document.getElementById('list').innerHTML = "
                "items.map(i => `<li>${i.description} — ${i.category}</li>`).join('');});"
                '</script></body></html>', 120)
        if "AI/ML Specialist" in system:
            return (
                "def classify_expense(description: str) -> str:\n"
                "    keywords = {'food': ['restaurant', 'grocery'], 'transport': ['uber', 'fuel']}\n"
                "    lowered = (description or '').lower()\n"
                "    for category, terms in keywords.items():\n"
                "        if any(t in lowered for t in terms):\n"
                "            return category\n"
                "    return 'misc'\n", 90)
        return ("Demo review: all static checks passed; the app looks ready to run.", 25)

    return LLMRouter(completion_fn=fake_completion)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="YAKSHA AI v2.0 — generate a single-file web app from one prompt."
    )
    parser.add_argument("--prompt", "-p", help="Natural-language description of the app to build.")
    parser.add_argument("--run-id", help="Optional custom run id (default: auto-generated UUID).")
    parser.add_argument("--demo", action="store_true",
                        help="Run offline with a scripted fake LLM (no API keys needed).")
    parser.add_argument("--no-llm-review", action="store_true",
                        help="Skip the optional LLM summary in the QA report.")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show internal INFO logs.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.demo:
        prompt = args.prompt or "Build an expense tracker that auto-categorizes spending"
        router = _demo_router()
        print("🧪 Demo mode — using a scripted fake LLM, no API calls.\n")
    else:
        if not args.prompt:
            parser.error("--prompt is required (or use --demo for an offline run).")
        prompt = args.prompt
        router = llm_router
        if not (os.getenv("GEMINI_API_KEY") or os.getenv("GROQ_API_KEY")):
            print("⚠️  Neither GEMINI_API_KEY nor GROQ_API_KEY is set — add them to your .env file.",
                  file=sys.stderr)
            return 2

    orchestrator = YakshaOrchestrator(router=router, use_llm_qa_review=not args.no_llm_review)
    try:
        handle = orchestrator.start(prompt, run_id=args.run_id)
    except Exception as exc:  # empty prompt, duplicate run id, ...
        print(f"Could not start run: {exc}", file=sys.stderr)
        return 2

    print(f"Run ID: {handle.run_id}\n")
    return stream_to_console(orchestrator, handle)


if __name__ == "__main__":
    sys.exit(main())