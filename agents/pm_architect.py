"""
agents/pm_architect.py
------------------------------------------------------------------------------
YAKSHA AI v2.0 — PM & System Architect Agent

Role in the v2.0 pipeline (per the Artifact-Based Architecture):
    This agent is the ONLY one that talks to the user's raw prompt. Its
    entire job is to turn that prompt into a single, strictly-validated
    `requirements.json` artifact — the contract that every downstream piece
    (Backend, Frontend, AI/ML agents running in PARALLEL, and later the
    Assembly Engine) reads instead of re-interpreting the user's words
    themselves.

    It never writes application code and never touches backend.py or
    frontend.html — keeping those concerns fully separated is what lets
    Backend/Frontend/AI-ML run in parallel once this artifact exists.

Why the strict schema + self-correction loop (v1.0 problem it fixes):
    v1.0 had no enforced contract between agents, so ambiguous/missing
    fields propagated silently until the final merge step blew up. Here,
    `requirements.json` is validated against a fixed schema the moment it's
    produced. If the LLM's JSON is malformed or missing required fields,
    the agent sends ONE corrective follow-up (with the exact validation
    error) before giving up — cheap, deterministic self-healing instead of
    discovering a broken contract three agents later.
------------------------------------------------------------------------------
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from core.artifact_manager import ArtifactManager, ArtifactError, artifact_manager
from core.assembly_engine import (
    DEFAULT_FLASK_APP_VAR,
    DEFAULT_FRONTEND_ROUTE,
    DEFAULT_PORT,
)
from core.config import ARTIFACT_REQUIREMENTS
from core.event_queue import EventBus, EventType
from core.llm_router import LLMRouter, LLMRouterError, llm_router

logger = logging.getLogger("yaksha.agents.pm_architect")

ROLE = "pm_architect"
MAX_JSON_ATTEMPTS = 3

REQUIRED_STRING_FIELDS = ("app_name", "backend_brief", "frontend_brief")


class PMArchitectError(Exception):
    """Raised when the agent cannot produce a valid requirements.json after all attempts."""


class PMArchitectAgent:
    """
    Turns a natural-language user prompt into a validated requirements.json
    artifact for run `run_id`. The run must already exist
    (ArtifactManager.create_run) before calling `run()`.
    """

    SYSTEM_PROMPT = f"""You are the PM & System Architect for an autonomous software \
engineering crew. You receive one natural-language request describing a web \
app and must respond with EXACTLY ONE JSON object — no markdown fences, no \
commentary before or after it.

The JSON object MUST contain these fields:
  "app_name" (string, required)         — short, human-readable app name
  "description" (string, optional)      — one or two sentence summary
  "port" (integer, optional)            — default {DEFAULT_PORT}
  "frontend_route" (string, optional)   — default "{DEFAULT_FRONTEND_ROUTE}"
  "flask_app_var" (string, optional)    — default "{DEFAULT_FLASK_APP_VAR}"
  "dependencies" (array of strings, optional) — pip package names beyond flask
  "backend_brief" (string, required)    — precise instructions for the Backend \
Developer agent: routes, data model, business logic needed
  "frontend_brief" (string, required)   — precise instructions for the Frontend \
Developer agent: layout, key UI elements, interactivity needed
  "needs_ai_ml" (boolean, optional)     — true if any ML/data-science logic is needed
  "ai_ml_brief" (string or null, optional) — instructions for the AI/ML Specialist \
agent, required only when needs_ai_ml is true

Respond with the JSON object only."""

    def __init__(
        self,
        manager: ArtifactManager = artifact_manager,
        router: LLMRouter = llm_router,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        self.manager = manager
        self.router = router
        self.event_bus = event_bus

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(
        self, run_id: str, user_prompt: str, *, max_output_tokens: int = 1500
    ) -> dict[str, Any]:
        if not self.manager.run_exists(run_id):
            raise PMArchitectError(
                f"Run '{run_id}' does not exist. Call "
                f"artifact_manager.create_run('{run_id}') before running an agent."
            )

        self._publish(run_id, EventType.AGENT_STARTED, "PM & System Architect started")

        try:
            requirements = self._produce_requirements(
                run_id, user_prompt, max_output_tokens
            )
        except Exception as exc:
            self._publish(
                run_id, EventType.AGENT_FAILED, f"PM & System Architect failed: {exc}"
            )
            raise

        self.manager.save_artifact(
            run_id, ARTIFACT_REQUIREMENTS, json.dumps(requirements, indent=2)
        )
        self._publish(
            run_id, EventType.ARTIFACT_SAVED, "requirements.json saved",
            payload={"app_name": requirements["app_name"]},
        )
        self._publish(
            run_id, EventType.AGENT_COMPLETED, "PM & System Architect completed",
        )
        return requirements

    # ------------------------------------------------------------------
    # LLM call + self-correction loop
    # ------------------------------------------------------------------

    def _produce_requirements(
        self, run_id: str, user_prompt: str, max_output_tokens: int
    ) -> dict[str, Any]:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        last_error: Optional[str] = None
        for attempt in range(1, MAX_JSON_ATTEMPTS + 1):
            try:
                result = self.router.complete(
                    ROLE, messages, max_output_tokens=max_output_tokens
                )
            except LLMRouterError as exc:
                raise PMArchitectError(
                    f"LLM router exhausted while producing requirements.json: {exc}"
                ) from exc

            try:
                raw = self._extract_json_object(result.text)
                validated = self._validate_and_normalize(raw)
                logger.info(
                    "[run=%s] requirements.json produced on attempt %d/%d via %s",
                    run_id, attempt, MAX_JSON_ATTEMPTS, result.model_name,
                )
                return validated
            except ValueError as exc:
                last_error = str(exc)
                logger.warning(
                    "[run=%s] attempt %d/%d produced invalid requirements: %s",
                    run_id, attempt, MAX_JSON_ATTEMPTS, last_error,
                )
                if attempt < MAX_JSON_ATTEMPTS:
                    messages.append({"role": "assistant", "content": result.text})
                    messages.append({
                        "role": "user",
                        "content": (
                            f"Your previous response was invalid: {last_error}. "
                            f"Respond again with ONE corrected JSON object only, "
                            f"following the exact schema — no markdown fences, no commentary."
                        ),
                    })

        raise PMArchitectError(
            f"Could not produce valid requirements.json after {MAX_JSON_ATTEMPTS} "
            f"attempts. Last validation error: {last_error}"
        )

    # ------------------------------------------------------------------
    # JSON extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_json_object(text: str) -> dict[str, Any]:
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start == -1 or end == -1 or end < start:
                raise ValueError("Response did not contain a JSON object.")
            try:
                data = json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError as exc:
                raise ValueError(f"Response is not valid JSON: {exc}") from exc

        if not isinstance(data, dict):
            raise ValueError("Response JSON must be an object, not a list/scalar.")
        return data

    # ------------------------------------------------------------------
    # Schema validation & normalization
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_and_normalize(data: dict[str, Any]) -> dict[str, Any]:
        missing = [
            field for field in REQUIRED_STRING_FIELDS
            if not isinstance(data.get(field), str) or not data.get(field, "").strip()
        ]
        if missing:
            raise ValueError(
                f"Missing or empty required field(s): {', '.join(missing)}"
            )

        app_name = data["app_name"].strip()
        description = str(data.get("description", "")).strip()
        backend_brief = data["backend_brief"].strip()
        frontend_brief = data["frontend_brief"].strip()

        port = data.get("port", DEFAULT_PORT)
        if not isinstance(port, int) or not (1 <= port <= 65535):
            raise ValueError(f"'port' must be an integer in [1, 65535], got {port!r}")

        frontend_route = str(data.get("frontend_route", DEFAULT_FRONTEND_ROUTE))
        if not frontend_route.startswith("/"):
            raise ValueError(f"'frontend_route' must start with '/', got {frontend_route!r}")

        flask_app_var = str(data.get("flask_app_var", DEFAULT_FLASK_APP_VAR))
        if not flask_app_var.isidentifier():
            raise ValueError(
                f"'flask_app_var' must be a valid Python identifier, got {flask_app_var!r}"
            )

        raw_deps = data.get("dependencies", [])
        if not isinstance(raw_deps, list) or not all(isinstance(d, str) for d in raw_deps):
            raise ValueError("'dependencies' must be an array of strings.")
        dependencies: list[str] = []
        for dep in ["flask", *raw_deps]:
            if dep not in dependencies:
                dependencies.append(dep)

        ai_ml_brief = data.get("ai_ml_brief")
        if ai_ml_brief is not None and not isinstance(ai_ml_brief, str):
            raise ValueError("'ai_ml_brief' must be a string or null.")
        needs_ai_ml = bool(data.get("needs_ai_ml", bool(ai_ml_brief)))
        if needs_ai_ml and not ai_ml_brief:
            raise ValueError("'needs_ai_ml' is true but 'ai_ml_brief' is missing.")

        return {
            "app_name": app_name,
            "description": description,
            "port": port,
            "frontend_route": frontend_route,
            "flask_app_var": flask_app_var,
            "dependencies": dependencies,
            "backend_brief": backend_brief,
            "frontend_brief": frontend_brief,
            "needs_ai_ml": needs_ai_ml,
            "ai_ml_brief": ai_ml_brief,
        }

    # ------------------------------------------------------------------
    # Event helper
    # ------------------------------------------------------------------

    def _publish(
        self, run_id: str, event_type: EventType, message: str, **kwargs: Any
    ) -> None:
        if self.event_bus is not None:
            self.event_bus.publish(run_id, event_type, message, agent_role=ROLE, **kwargs)


if __name__ == "__main__":
    # Manual smoke test: python -m agents.pm_architect
    # Exercises (a) a clean valid response on the first try, and (b) the
    # self-correction loop recovering from an invalid first response —
    # all without any network calls.
    logging.basicConfig(level=logging.INFO)

    am = ArtifactManager(runs_dir="runs")

    call_count = {"n": 0}

    def fake_completion(model_cfg, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # First call: missing required 'frontend_brief' -> should trigger self-correction.
            bad = json.dumps({
                "app_name": "Habit Tracker",
                "backend_brief": "CRUD API for habits with SQLite storage.",
            })
            return (bad, 50)
        # Second call (after corrective follow-up): valid.
        good = json.dumps({
            "app_name": "Habit Tracker",
            "description": "Track daily habits and streaks.",
            "backend_brief": "CRUD API for habits with SQLite storage.",
            "frontend_brief": "Tailwind dashboard with a habit grid and streak counters.",
            "dependencies": ["flask-sqlalchemy"],
        })
        return (good, 120)

    router = LLMRouter(completion_fn=fake_completion, sleeper=lambda s: None)
    agent = PMArchitectAgent(manager=am, router=router)

    run_id = am.create_run()
    requirements = agent.run(run_id, "Build me a habit tracker web app")
    print(json.dumps(requirements, indent=2))

    assert call_count["n"] == 2, "expected exactly one self-correction round-trip"
    assert requirements["app_name"] == "Habit Tracker"
    assert "flask" in requirements["dependencies"]
    assert requirements["needs_ai_ml"] is False

    saved = json.loads(am.read_artifact(run_id, ARTIFACT_REQUIREMENTS))
    assert saved == requirements

    am.delete_run(run_id)
    print("\nAll pm_architect smoke-test scenarios passed.")