"""
agents/_code_gen_base.py
------------------------------------------------------------------------------
YAKSHA AI v2.0 — Shared base for the three parallel code-generation agents
(Backend Developer, Frontend Developer, AI/ML Specialist).

Why a shared base:
    All three agents follow the exact same shape — read requirements.json,
    pull out their own brief, ask the LLM for ONE artifact, validate it
    deterministically, self-correct once on failure, save via
    ArtifactManager. Centralizing that shape here means the self-correction
    loop, code-fence stripping, and event publishing are written and tested
    ONCE instead of drifting across three near-identical copies.

Design note on parallelism (v2.0 golden rule #4):
    These agents share nothing but a `run_id` and the requirements.json they
    all read from. None of them write to each other's artifacts, none call
    each other, and none depend on another's output existing first. That's
    what makes it safe for main.py's orchestrator to launch all three at
    once (e.g. via a ThreadPoolExecutor) right after PM Architect finishes.
------------------------------------------------------------------------------
"""

from __future__ import annotations

import ast
import json
import logging
import re
from typing import Any, Optional

from core.artifact_manager import ArtifactManager, artifact_manager
from core.config import ARTIFACT_REQUIREMENTS
from core.event_queue import EventBus, EventType
from core.llm_router import LLMRouter, LLMRouterError, llm_router

logger = logging.getLogger("yaksha.agents.code_gen_base")


class CodeGenError(Exception):
    """Raised when an agent cannot produce valid output after all self-correction attempts."""


def strip_code_fences(text: str) -> str:
    """
    Removes a single leading/trailing markdown code fence (```lang ... ```)
    if the model wrapped its answer in one despite instructions not to.
    Leaves plain, unfenced text untouched.
    """
    cleaned = text.strip()
    cleaned = re.sub(r"^```[a-zA-Z0-9_+-]*\s*\n?", "", cleaned)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    return cleaned.strip()


class BaseCodeGenAgent:
    """
    Template-method base class. Subclasses set the four class attributes
    plus the three hook methods below; `run()` itself is not overridden.
    """

    ROLE: str = ""                 # must match a key in core.config.MODEL_ROUTES
    ARTIFACT_FILENAME: str = ""    # e.g. ARTIFACT_BACKEND from core.config
    SYSTEM_PROMPT: str = ""
    MAX_ATTEMPTS: int = 3

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
    # Hooks subclasses must implement
    # ------------------------------------------------------------------

    def _extract_brief(self, requirements: dict[str, Any]) -> Optional[str]:
        """Returns this agent's task brief from requirements.json, or None to skip entirely."""
        raise NotImplementedError

    def _build_user_message(self, requirements: dict[str, Any], brief: str) -> str:
        """Builds the user-turn prompt sent alongside SYSTEM_PROMPT."""
        raise NotImplementedError

    def _validate(self, code: str, requirements: dict[str, Any]) -> None:
        """Raises ValueError with a corrective, model-facing message if `code` is invalid."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Template method
    # ------------------------------------------------------------------

    def run(self, run_id: str, *, max_output_tokens: int = 4000) -> Optional[str]:
        if not self.manager.run_exists(run_id):
            raise CodeGenError(
                f"Run '{run_id}' does not exist. Call "
                f"artifact_manager.create_run('{run_id}') before running an agent."
            )

        requirements = json.loads(self.manager.read_artifact(run_id, ARTIFACT_REQUIREMENTS))
        brief = self._extract_brief(requirements)

        if brief is None:
            self._publish(
                run_id, EventType.AGENT_COMPLETED,
                f"{self.ROLE} skipped — not needed for this app",
            )
            return None

        self._publish(run_id, EventType.AGENT_STARTED, f"{self.ROLE} started")

        try:
            code = self._generate_with_self_correction(
                run_id, requirements, brief, max_output_tokens
            )
        except Exception as exc:
            self._publish(run_id, EventType.AGENT_FAILED, f"{self.ROLE} failed: {exc}")
            raise

        self.manager.save_artifact(run_id, self.ARTIFACT_FILENAME, code)
        self._publish(
            run_id, EventType.ARTIFACT_SAVED, f"{self.ARTIFACT_FILENAME} saved",
        )
        self._publish(run_id, EventType.AGENT_COMPLETED, f"{self.ROLE} completed")
        return code

    # ------------------------------------------------------------------
    # Self-correction loop (mirrors pm_architect's JSON self-correction,
    # generalized to any text artifact with a validate() callback)
    # ------------------------------------------------------------------

    def _generate_with_self_correction(
        self,
        run_id: str,
        requirements: dict[str, Any],
        brief: str,
        max_output_tokens: int,
    ) -> str:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": self._build_user_message(requirements, brief)},
        ]

        last_error: Optional[str] = None
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                result = self.router.complete(
                    self.ROLE, messages, max_output_tokens=max_output_tokens
                )
            except LLMRouterError as exc:
                raise CodeGenError(
                    f"[{self.ROLE}] LLM router exhausted while generating "
                    f"{self.ARTIFACT_FILENAME}: {exc}"
                ) from exc

            code = strip_code_fences(result.text)
            try:
                self._validate(code, requirements)
                logger.info(
                    "[run=%s][%s] %s produced on attempt %d/%d via %s",
                    run_id, self.ROLE, self.ARTIFACT_FILENAME, attempt,
                    self.MAX_ATTEMPTS, result.model_name,
                )
                return code
            except ValueError as exc:
                last_error = str(exc)
                logger.warning(
                    "[run=%s][%s] attempt %d/%d invalid: %s",
                    run_id, self.ROLE, attempt, self.MAX_ATTEMPTS, last_error,
                )
                if attempt < self.MAX_ATTEMPTS:
                    messages.append({"role": "assistant", "content": result.text})
                    messages.append({
                        "role": "user",
                        "content": (
                            f"Your previous response was invalid: {last_error}. "
                            f"Respond again with the corrected, complete output only — "
                            f"no markdown fences, no commentary."
                        ),
                    })

        raise CodeGenError(
            f"[{self.ROLE}] could not produce valid {self.ARTIFACT_FILENAME} after "
            f"{self.MAX_ATTEMPTS} attempts. Last validation error: {last_error}"
        )

    # ------------------------------------------------------------------
    # Shared AST helper (used by backend_dev and ai_ml_specialist validators)
    # ------------------------------------------------------------------

    @staticmethod
    def _find_assigned_flask_var(tree: ast.Module) -> Optional[str]:
        for node in tree.body:
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                continue
            func = node.value.func
            is_flask_call = (
                (isinstance(func, ast.Name) and func.id == "Flask")
                or (isinstance(func, ast.Attribute) and func.attr == "Flask")
            )
            if not is_flask_call:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    return target.id
        return None

    # ------------------------------------------------------------------
    # Event helper
    # ------------------------------------------------------------------

    def _publish(
        self, run_id: str, event_type: EventType, message: str, **kwargs: Any
    ) -> None:
        if self.event_bus is not None:
            self.event_bus.publish(run_id, event_type, message, agent_role=self.ROLE, **kwargs)