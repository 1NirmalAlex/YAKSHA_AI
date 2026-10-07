"""
agents/frontend_dev.py
------------------------------------------------------------------------------
YAKSHA AI v2.0 — Frontend Developer Agent

Reads `frontend_brief` from requirements.json and produces frontend.html: a
single self-contained HTML document (Tailwind CDN + inline/interactive JS).
Runs in PARALLEL with backend_dev and ai_ml_specialist — this agent has no
knowledge of backend.py's routes beyond whatever the brief tells it to call,
and it never touches any other artifact.

Unlike backend_dev, there's no AST to validate HTML against — validation
here is deliberately lightweight (well-formed shell, Tailwind present,
non-trivial length). The Assembly Engine treats this file as an opaque
string it embeds verbatim, so DEEP correctness (does the JS actually work)
is out of scope for this agent; QA's static checks and, eventually, a
human/browser check catch the rest.
------------------------------------------------------------------------------
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from ._code_gen_base import BaseCodeGenAgent
from core.config import ARTIFACT_FRONTEND

logger = logging.getLogger("yaksha.agents.frontend_dev")

ROLE = "frontend_dev"

MIN_LENGTH_CHARS = 80


class FrontendDevAgent(BaseCodeGenAgent):
    ROLE = ROLE
    ARTIFACT_FILENAME = ARTIFACT_FRONTEND

    SYSTEM_PROMPT = """You are the Frontend Developer for an autonomous software \
engineering crew. You will be given a brief and must respond with EXACTLY ONE \
raw, self-contained HTML document — no markdown fences, no commentary before \
or after the code.

Hard rules:
1. Include Tailwind CSS via the CDN script tag: \
<script src="https://cdn.tailwindcss.com"></script>
2. Put all CSS and JavaScript inline in this one file — no separate files, \
no build step, no bundler.
3. Implement the brief's layout and interactivity completely using plain \
DOM APIs (fetch() for any backend calls) — do not assume any frontend \
framework is available.
4. Produce a complete, valid HTML document from <!DOCTYPE html> to </html>.

Respond with the raw HTML document only."""

    def _extract_brief(self, requirements: dict[str, Any]) -> Optional[str]:
        return requirements.get("frontend_brief")

    def _build_user_message(self, requirements: dict[str, Any], brief: str) -> str:
        return (
            f"App name: {requirements['app_name']}\n"
            f"Backend routes this page may call (base path {requirements['frontend_route']} "
            f"is reserved for THIS page itself, don't route to it): see the brief below.\n\n"
            f"Frontend brief:\n{brief}"
        )

    def _validate(self, code: str, requirements: dict[str, Any]) -> None:
        if len(code) < MIN_LENGTH_CHARS:
            raise ValueError(
                f"Output is too short ({len(code)} chars) to be a real page — "
                f"produce a complete HTML document."
            )

        lowered = code.lower()
        if "<html" not in lowered or "</html>" not in lowered:
            raise ValueError(
                "Output must be a complete HTML document with <html> and </html> tags."
            )

        if "tailwindcss" not in lowered:
            raise ValueError(
                'Missing the Tailwind CDN script tag — add '
                '<script src="https://cdn.tailwindcss.com"></script> in <head>.'
            )


if __name__ == "__main__":
    # Manual smoke test: python -m agents.frontend_dev
    # Exercises (a) self-correction when Tailwind is missing, (b) success
    # on the corrected attempt.
    import json

    from core.artifact_manager import ArtifactManager
    from core.config import ARTIFACT_REQUIREMENTS
    from core.llm_router import LLMRouter

    logging.basicConfig(level=logging.INFO)

    am = ArtifactManager(runs_dir="runs")
    run_id = am.create_run()
    am.save_artifact(run_id, ARTIFACT_REQUIREMENTS, json.dumps({
        "app_name": "Habit Tracker",
        "frontend_route": "/",
        "frontend_brief": "A dashboard with a habit grid and streak counters.",
    }))

    call_count = {"n": 0}

    def fake_completion(model_cfg, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Missing Tailwind CDN tag -> triggers self-correction.
            bad = (
                "<!DOCTYPE html><html><head><title>Habit Tracker</title></head>"
                "<body><h1>Habits</h1></body></html>"
            )
            return (bad, 40)
        good = (
            "<!DOCTYPE html><html><head><title>Habit Tracker</title>"
            '<script src="https://cdn.tailwindcss.com"></script></head>'
            '<body class="bg-gray-900 text-white"><h1 class="text-2xl">Habits</h1>'
            "<script>console.log('loaded');</script></body></html>"
        )
        return (good, 80)

    router = LLMRouter(completion_fn=fake_completion, sleeper=lambda s: None)
    agent = FrontendDevAgent(manager=am, router=router)

    code = agent.run(run_id)
    print(code)
    assert call_count["n"] == 2, "expected exactly one self-correction round-trip"
    assert "tailwindcss" in code.lower()
    assert am.read_artifact(run_id, ARTIFACT_FRONTEND) == code

    am.delete_run(run_id)
    print("\nAll frontend_dev smoke-test scenarios passed.")