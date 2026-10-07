"""
agents/backend_dev.py
------------------------------------------------------------------------------
YAKSHA AI v2.0 — Backend Developer Agent

Reads `backend_brief` from requirements.json and produces backend.py: a
plain Flask module implementing that brief. Runs in PARALLEL with
frontend_dev and ai_ml_specialist once PM Architect's requirements.json
exists — this agent touches nothing but its own artifact.

Contract enforced (must match core/assembly_engine.py's expectations):
    - Exactly one `<flask_app_var> = Flask(__name__)` at module level, using
      the exact variable name requirements.json specifies.
    - No route registered at `frontend_route` — the Assembly Engine injects
      that route itself to serve frontend.html.
    - No `if __name__ == "__main__":` block — the Assembly Engine generates
      the run block from requirements.json's port.
Both rules are stated in the prompt; only the Flask-app-variable rule is
hard-validated here (a wrong/missing app var breaks assembly outright). The
other two are soft — if a model includes them anyway, the Assembly Engine
silently handles the __main__ block by stripping it and just skips
injecting a duplicate frontend route, logging a warning instead of failing
the whole run.
------------------------------------------------------------------------------
"""

from __future__ import annotations

import ast
import logging
from typing import Any, Optional

from ._code_gen_base import BaseCodeGenAgent
from core.config import ARTIFACT_BACKEND

logger = logging.getLogger("yaksha.agents.backend_dev")

ROLE = "backend_dev"


class BackendDevAgent(BaseCodeGenAgent):
    ROLE = ROLE
    ARTIFACT_FILENAME = ARTIFACT_BACKEND

    SYSTEM_PROMPT = """You are the Backend Developer for an autonomous software \
engineering crew. You will be given a brief and must respond with EXACTLY ONE \
raw Python module implementing a Flask backend — no markdown fences, no \
commentary before or after the code.

Hard rules:
1. Instantiate the Flask app at module level using EXACTLY the variable name \
you are given (e.g. `app = Flask(__name__)` if told the variable name is "app").
2. Do NOT register any route at the frontend route path you are given — that \
path is reserved and will be wired up separately.
3. Do NOT include an `if __name__ == "__main__":` block — the entry point is \
generated separately.
4. Implement the brief's routes/logic completely and use in-memory or SQLite \
storage unless told otherwise — never require an external database service.

Respond with the raw Python module only."""

    def _extract_brief(self, requirements: dict[str, Any]) -> Optional[str]:
        return requirements.get("backend_brief")

    def _build_user_message(self, requirements: dict[str, Any], brief: str) -> str:
        return (
            f"App name: {requirements['app_name']}\n"
            f"Flask app variable name (use exactly this): {requirements['flask_app_var']}\n"
            f"Reserved frontend route (do not register a route here): "
            f"{requirements['frontend_route']}\n"
            f"Approved dependencies: {', '.join(requirements['dependencies'])}\n\n"
            f"Backend brief:\n{brief}"
        )

    def _validate(self, code: str, requirements: dict[str, Any]) -> None:
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            raise ValueError(f"Backend code has a syntax error: {exc}")

        expected_var = requirements["flask_app_var"]
        actual_var = self._find_assigned_flask_var(tree)
        if actual_var is None:
            raise ValueError(
                f"No Flask app instantiation found. Add exactly "
                f"`{expected_var} = Flask(__name__)` at module level."
            )
        if actual_var != expected_var:
            raise ValueError(
                f"Flask app was assigned to variable '{actual_var}', but it must "
                f"be named '{expected_var}' exactly."
            )


if __name__ == "__main__":
    # Manual smoke test: python -m agents.backend_dev
    # Exercises (a) self-correction when the wrong app-variable name is used,
    # (b) success on the corrected attempt.
    import json

    from core.artifact_manager import ArtifactManager
    from core.config import ARTIFACT_REQUIREMENTS
    from core.llm_router import LLMRouter

    logging.basicConfig(level=logging.INFO)

    am = ArtifactManager(runs_dir="runs")
    run_id = am.create_run()
    am.save_artifact(run_id, ARTIFACT_REQUIREMENTS, json.dumps({
        "app_name": "Habit Tracker",
        "flask_app_var": "app",
        "frontend_route": "/",
        "dependencies": ["flask"],
        "backend_brief": "CRUD API for habits: GET/POST /api/habits.",
    }))

    call_count = {"n": 0}

    def fake_completion(model_cfg, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Wrong variable name ("flask_app" instead of "app") -> triggers self-correction.
            bad = (
                "from flask import Flask, jsonify\n"
                "flask_app = Flask(__name__)\n\n"
                "@flask_app.route('/api/habits')\n"
                "def habits():\n"
                "    return jsonify([])\n"
            )
            return (bad, 60)
        good = (
            "from flask import Flask, jsonify\n"
            "app = Flask(__name__)\n\n"
            "@app.route('/api/habits')\n"
            "def habits():\n"
            "    return jsonify([])\n"
        )
        return (good, 60)

    router = LLMRouter(completion_fn=fake_completion, sleeper=lambda s: None)
    agent = BackendDevAgent(manager=am, router=router)

    code = agent.run(run_id)
    print(code)
    assert call_count["n"] == 2, "expected exactly one self-correction round-trip"
    assert "app = Flask(__name__)" in code
    assert am.read_artifact(run_id, ARTIFACT_BACKEND) == code

    am.delete_run(run_id)
    print("\nAll backend_dev smoke-test scenarios passed.")