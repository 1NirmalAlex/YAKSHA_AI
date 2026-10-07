"""
agents/ai_ml_specialist.py
------------------------------------------------------------------------------
YAKSHA AI v2.0 — AI/ML Specialist Agent

Reads `ai_ml_brief` from requirements.json and produces ai_ml_module.py: a
plain Python module of reusable functions/classes meant to be imported by
backend.py — this agent never instantiates its own Flask app or defines
routes. Runs in PARALLEL with backend_dev and frontend_dev.

Conditional by design: most generated apps don't need ML/data-science logic
at all. If `requirements.json["needs_ai_ml"]` is false (PM Architect only
sets it true when a real ai_ml_brief exists), this agent's `run()` returns
None immediately and saves nothing — the orchestrator can always launch all
three developer agents in parallel without checking needs_ai_ml itself.
------------------------------------------------------------------------------
"""

from __future__ import annotations

import ast
import logging
from typing import Any, Optional

from ._code_gen_base import BaseCodeGenAgent
from core.config import ARTIFACT_AI_ML

logger = logging.getLogger("yaksha.agents.ai_ml_specialist")

ROLE = "ai_ml_specialist"


class AIMLSpecialistAgent(BaseCodeGenAgent):
    ROLE = ROLE
    ARTIFACT_FILENAME = ARTIFACT_AI_ML

    SYSTEM_PROMPT = """You are the AI/ML Specialist for an autonomous software \
engineering crew. You will be given a brief and must respond with EXACTLY ONE \
raw Python module implementing the requested data-science/ML logic as \
reusable functions and/or classes — no markdown fences, no commentary before \
or after the code.

Hard rules:
1. Do NOT instantiate a Flask app and do NOT define any Flask routes — this \
module is imported and called BY the backend, it does not serve HTTP itself.
2. Do NOT include an `if __name__ == "__main__":` block.
3. Define at least one clearly-named, importable function or class implementing \
the brief. Keep dependencies to well-known packages only (e.g. numpy, pandas, \
scikit-learn) and note any of them the backend will need to install.

Respond with the raw Python module only."""

    def _extract_brief(self, requirements: dict[str, Any]) -> Optional[str]:
        if not requirements.get("needs_ai_ml"):
            return None
        return requirements.get("ai_ml_brief")

    def _build_user_message(self, requirements: dict[str, Any], brief: str) -> str:
        return (
            f"App name: {requirements['app_name']}\n"
            f"This module will be imported by backend.py — expose plain functions/classes.\n\n"
            f"AI/ML brief:\n{brief}"
        )

    def _validate(self, code: str, requirements: dict[str, Any]) -> None:
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            raise ValueError(f"AI/ML module has a syntax error: {exc}")

        has_definition = any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            for node in tree.body
        )
        if not has_definition:
            raise ValueError(
                "No top-level function or class definitions found — implement the "
                "brief as at least one importable function or class."
            )

        if self._find_assigned_flask_var(tree) is not None:
            raise ValueError(
                "This module must not instantiate a Flask app — remove the "
                "`Flask(...)` call; only backend.py owns the Flask app."
            )


if __name__ == "__main__":
    # Manual smoke test: python -m agents.ai_ml_specialist
    # Exercises (a) the skip path when needs_ai_ml is false, (b) self-correction
    # when the model wrongly instantiates its own Flask app, (c) success after
    # correction.
    import json

    from core.artifact_manager import ArtifactManager
    from core.config import ARTIFACT_REQUIREMENTS
    from core.llm_router import LLMRouter

    logging.basicConfig(level=logging.INFO)

    am = ArtifactManager(runs_dir="runs")

    def unreachable_completion(model_cfg, messages, **kwargs):
        raise AssertionError("LLM should never be called when needs_ai_ml is false")

    # --- Scenario A: skip path ---
    run_id_a = am.create_run()
    am.save_artifact(run_id_a, ARTIFACT_REQUIREMENTS, json.dumps({
        "app_name": "Habit Tracker", "needs_ai_ml": False, "ai_ml_brief": None,
    }))
    router_a = LLMRouter(completion_fn=unreachable_completion, sleeper=lambda s: None)
    agent_a = AIMLSpecialistAgent(manager=am, router=router_a)
    result_a = agent_a.run(run_id_a)
    assert result_a is None
    assert not am.artifact_exists(run_id_a, ARTIFACT_AI_ML)
    am.delete_run(run_id_a)
    print("Scenario A passed: skipped cleanly when needs_ai_ml is false.\n")

    # --- Scenario B + C: active path with self-correction ---
    run_id_b = am.create_run()
    am.save_artifact(run_id_b, ARTIFACT_REQUIREMENTS, json.dumps({
        "app_name": "Spending Insights",
        "needs_ai_ml": True,
        "ai_ml_brief": "Classify monthly spending into categories using simple keyword rules.",
    }))

    call_count = {"n": 0}

    def fake_completion(model_cfg, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Wrongly instantiates its own Flask app -> triggers self-correction.
            bad = (
                "from flask import Flask\n"
                "app = Flask(__name__)\n\n"
                "def classify(text):\n"
                "    return 'misc'\n"
            )
            return (bad, 50)
        good = (
            "def classify_spending(description: str) -> str:\n"
            "    keywords = {'food': ['restaurant', 'grocery'], 'transport': ['uber', 'fuel']}\n"
            "    lowered = description.lower()\n"
            "    for category, terms in keywords.items():\n"
            "        if any(term in lowered for term in terms):\n"
            "            return category\n"
            "    return 'misc'\n"
        )
        return (good, 90)

    router_b = LLMRouter(completion_fn=fake_completion, sleeper=lambda s: None)
    agent_b = AIMLSpecialistAgent(manager=am, router=router_b)
    code = agent_b.run(run_id_b)
    print(code)
    assert call_count["n"] == 2, "expected exactly one self-correction round-trip"
    assert "def classify_spending" in code
    assert am.read_artifact(run_id_b, ARTIFACT_AI_ML) == code
    am.delete_run(run_id_b)
    print("Scenario B/C passed: self-corrected away from an illegal Flask app.\n")

    print("All ai_ml_specialist smoke-test scenarios passed.")