"""
agents/qa_reviewer.py
------------------------------------------------------------------------------
YAKSHA AI v2.0 — QA Reviewer & Tester Agent

Role shift from v1.0 (the change the roadmap called for):
    In v1.0, the QA Agent was the one merging Backend + Frontend code and
    calling FileWriterTool itself — which is exactly what caused the
    context-overwrite/truncation bug. In v2.0 the deterministic Assembly
    Engine (core/assembly_engine.py) owns merging and writing entirely.

    This agent's role is now strictly READ -> VALIDATE -> REPORT:
        - READ:     requirements.json, assembly_report.json, and the final
                    assembled project_files/<run_id>/app.py
        - VALIDATE: independent, deterministic AST-based static checks
                    (syntax validity, Flask app present, entry point present,
                    frontend embedded, a lightweight dangerous-pattern scan)
        - REPORT:   writes qa_report.json describing pass/fail and issues

    It NEVER edits backend.py, frontend.html, or app.py. If it did, it would
    reintroduce exactly the single-point-of-failure v2.0 was designed to
    remove. An optional LLM call may add a short qualitative summary, but
    that summary is advisory text in the report only — never code.
------------------------------------------------------------------------------
"""

from __future__ import annotations

import ast
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from core.artifact_manager import ArtifactError, ArtifactManager, artifact_manager
from core.assembly_engine import ASSEMBLY_REPORT_FILENAME
from core.config import (
    ARTIFACT_QA_REPORT,
    ARTIFACT_REQUIREMENTS,
    FINAL_OUTPUT_FILENAME,
    PROJECT_FILES_DIR,
)
from core.event_queue import EventBus, EventType
from core.llm_router import LLMRouter, LLMRouterError

logger = logging.getLogger("yaksha.agents.qa_reviewer")

ROLE = "qa_reviewer"

# Lightweight, non-exhaustive lint list — flagged as WARNINGS (never critical)
# so QA never blocks delivery on this alone; it just surfaces it for a human.
_DANGEROUS_CALL_NAMES = {"eval", "exec"}
_DANGEROUS_ATTR_CALLS = {
    ("os", "system"), ("os", "popen"),
    ("subprocess", "run"), ("subprocess", "call"),
    ("subprocess", "Popen"),
}


class QAReviewerError(Exception):
    """Raised only for unexpected internal failures — never for a failed app review."""


@dataclass
class QAReport:
    run_id: str
    passed: bool
    static_checks: dict[str, bool]
    critical_issues: list[str]
    warnings: list[str]
    llm_review: Optional[str] = None
    reviewed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "passed": self.passed,
            "static_checks": self.static_checks,
            "critical_issues": self.critical_issues,
            "warnings": self.warnings,
            "llm_review": self.llm_review,
            "reviewed_at": self.reviewed_at,
        }


class QAReviewerAgent:
    """
    Reads what the Assembly Engine already produced for `run_id`, runs
    independent static validation, and writes qa_report.json. Optionally
    asks the LLM router for a short qualitative summary — purely advisory,
    and never allowed to block or replace the deterministic verdict.
    """

    SYSTEM_PROMPT = (
        "You are a QA reviewer. You will be given static analysis results for "
        "an auto-generated Flask web app. Write a short (under 120 words) "
        "plain-language review summarizing the app's readiness. Do not "
        "propose code changes — only summarize risk and readiness."
    )

    def __init__(
        self,
        manager: ArtifactManager = artifact_manager,
        router: Optional[LLMRouter] = None,
        event_bus: Optional[EventBus] = None,
        project_files_dir: Path | str = PROJECT_FILES_DIR,
    ) -> None:
        self.manager = manager
        self.router = router
        self.event_bus = event_bus
        self.project_files_dir = Path(project_files_dir)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(
        self, run_id: str, *, use_llm_review: bool = True, max_output_tokens: int = 300
    ) -> QAReport:
        self._publish(run_id, EventType.AGENT_STARTED, "QA Reviewer started")

        try:
            critical_issues: list[str] = []
            warnings: list[str] = []

            self._check_requirements(run_id, critical_issues)
            assembly_report = self._check_assembly_report(run_id, critical_issues, warnings)
            reported_path = assembly_report.get("output_path") if assembly_report else None
            static_checks, source = self._check_final_app(
                run_id, critical_issues, warnings, reported_path
            )

            passed = not critical_issues

            llm_review: Optional[str] = None
            if use_llm_review and self.router is not None:
                llm_review = self._get_llm_review(
                    run_id, static_checks, critical_issues, warnings, source, max_output_tokens
                )

            report = QAReport(
                run_id=run_id,
                passed=passed,
                static_checks=static_checks,
                critical_issues=critical_issues,
                warnings=warnings,
                llm_review=llm_review,
            )
        except Exception as exc:
            self._publish(run_id, EventType.AGENT_FAILED, f"QA Reviewer crashed: {exc}")
            raise QAReviewerError(f"QA Reviewer crashed for run '{run_id}': {exc}") from exc

        self.manager.save_artifact(
            run_id, ARTIFACT_QA_REPORT, json.dumps(report.to_dict(), indent=2)
        )
        self._publish(
            run_id, EventType.QA_REPORT_READY, "qa_report.json saved",
            payload={"passed": report.passed, "critical_issues": len(report.critical_issues)},
        )
        self._publish(
            run_id,
            EventType.AGENT_COMPLETED if passed else EventType.AGENT_FAILED,
            f"QA Reviewer completed — {'PASSED' if passed else 'FAILED'}",
        )
        return report

    # ------------------------------------------------------------------
    # READ + VALIDATE steps
    # ------------------------------------------------------------------

    def _check_requirements(self, run_id: str, critical_issues: list[str]) -> None:
        try:
            raw = self.manager.read_artifact(run_id, ARTIFACT_REQUIREMENTS)
            json.loads(raw)
        except ArtifactError:
            critical_issues.append("requirements.json is missing for this run.")
        except json.JSONDecodeError as exc:
            critical_issues.append(f"requirements.json is not valid JSON: {exc}")

    def _check_assembly_report(
        self, run_id: str, critical_issues: list[str], warnings: list[str]
    ) -> Optional[dict[str, Any]]:
        try:
            raw = self.manager.read_artifact(run_id, ASSEMBLY_REPORT_FILENAME)
            report = json.loads(raw)
            warnings.extend(
                f"[assembly] {w}" for w in report.get("warnings", [])
            )
            return report
        except ArtifactError:
            critical_issues.append(
                "assembly_report.json is missing — the Assembly Engine may not have run."
            )
        except json.JSONDecodeError as exc:
            critical_issues.append(f"assembly_report.json is not valid JSON: {exc}")
        return None

    def _check_final_app(
        self,
        run_id: str,
        critical_issues: list[str],
        warnings: list[str],
        reported_path: Optional[str] = None,
    ) -> tuple[dict[str, bool], Optional[str]]:
        static_checks = {
            "file_found": False,
            "syntax_valid": False,
            "flask_app_found": False,
            "entry_point_found": False,
            "frontend_embedded": False,
        }

        # Prefer the path the Assembly Engine itself recorded; fall back to the
        # configured default location if the report doesn't carry one.
        app_path = (
            Path(reported_path)
            if reported_path
            else self.project_files_dir / run_id / FINAL_OUTPUT_FILENAME
        )
        if not app_path.exists():
            critical_issues.append(f"Final output not found at {app_path}")
            return static_checks, None
        static_checks["file_found"] = True

        source = app_path.read_text(encoding="utf-8")

        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            critical_issues.append(f"Final app.py failed to parse: {exc}")
            return static_checks, source
        static_checks["syntax_valid"] = True

        if self._has_flask_app(tree):
            static_checks["flask_app_found"] = True
        else:
            critical_issues.append("No Flask app instantiation (`X = Flask(__name__)`) found.")

        if self._has_main_guard(tree):
            static_checks["entry_point_found"] = True
        else:
            critical_issues.append('No `if __name__ == "__main__":` entry point found.')

        if self._has_frontend_html(tree):
            static_checks["frontend_embedded"] = True
        else:
            critical_issues.append("No FRONTEND_HTML constant found — frontend may not be embedded.")

        dangerous = self._scan_dangerous_patterns(tree)
        warnings.extend(dangerous)

        return static_checks, source

    # ------------------------------------------------------------------
    # AST helper checks (independent re-implementation of the assembly
    # contract, deliberately not importing assembly_engine's internals —
    # QA verifies the OUTPUT holds the contract, it doesn't trust the
    # engine's own bookkeeping of it)
    # ------------------------------------------------------------------

    @staticmethod
    def _has_flask_app(tree: ast.Module) -> bool:
        for node in tree.body:
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                continue
            func = node.value.func
            if (isinstance(func, ast.Name) and func.id == "Flask") or (
                isinstance(func, ast.Attribute) and func.attr == "Flask"
            ):
                return True
        return False

    @staticmethod
    def _has_main_guard(tree: ast.Module) -> bool:
        for node in tree.body:
            if not isinstance(node, ast.If):
                continue
            test = node.test
            if not isinstance(test, ast.Compare) or len(test.ops) != 1:
                continue
            if not isinstance(test.ops[0], ast.Eq):
                continue
            operands = (test.left, test.comparators[0])
            names = {n.id for n in operands if isinstance(n, ast.Name)}
            consts = {n.value for n in operands if isinstance(n, ast.Constant)}
            if "__name__" in names and "__main__" in consts:
                return True
        return False

    @staticmethod
    def _has_frontend_html(tree: ast.Module) -> bool:
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "FRONTEND_HTML":
                        return True
        return False

    @staticmethod
    def _scan_dangerous_patterns(tree: ast.Module) -> list[str]:
        found: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name) and func.id in _DANGEROUS_CALL_NAMES:
                found.append(
                    f"Potential use of `{func.id}()` at line {node.lineno} — review before deploying."
                )
            elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                pair = (func.value.id, func.attr)
                if pair in _DANGEROUS_ATTR_CALLS:
                    found.append(
                        f"Potential use of `{pair[0]}.{pair[1]}()` at line {node.lineno} "
                        f"— review before deploying."
                    )
        return found

    # ------------------------------------------------------------------
    # Optional qualitative LLM pass — advisory only, never blocking
    # ------------------------------------------------------------------

    def _get_llm_review(
        self,
        run_id: str,
        static_checks: dict[str, bool],
        critical_issues: list[str],
        warnings: list[str],
        source: Optional[str],
        max_output_tokens: int,
    ) -> Optional[str]:
        summary_for_llm = {
            "static_checks": static_checks,
            "critical_issues": critical_issues,
            "warnings": warnings,
            "code_preview": (source or "")[:1500],
        }
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(summary_for_llm, indent=2)},
        ]
        try:
            result = self.router.complete(
                ROLE, messages, max_output_tokens=max_output_tokens
            )
            return result.text.strip()
        except LLMRouterError as exc:
            logger.warning(
                "[run=%s] LLM qualitative review unavailable, continuing with "
                "deterministic checks only: %s", run_id, exc,
            )
            warnings.append(f"LLM qualitative review unavailable: {exc}")
            return None

    # ------------------------------------------------------------------
    # Event helper
    # ------------------------------------------------------------------

    def _publish(
        self, run_id: str, event_type: EventType, message: str, **kwargs: Any
    ) -> None:
        if self.event_bus is not None:
            self.event_bus.publish(run_id, event_type, message, agent_role=ROLE, **kwargs)


if __name__ == "__main__":
    # Manual smoke test: python -m agents.qa_reviewer
    # Exercises (a) a fully passing review with an LLM summary, (b) a
    # critical failure when assembly never ran, (c) graceful degradation
    # when the LLM router itself is exhausted.
    import shutil

    from core.assembly_engine import AssemblyEngine
    from core.config import ARTIFACT_BACKEND, ARTIFACT_FRONTEND

    logging.basicConfig(level=logging.INFO)

    am = ArtifactManager(runs_dir="runs")
    engine = AssemblyEngine(manager=am, output_root="project_files")

    def fake_review_completion(model_cfg, messages, **kwargs):
        return ("Looks solid: valid Flask app, entry point present, no red flags.", 30)

    # --- Scenario A: fully assembled, passing app ---
    run_id = am.create_run()
    am.save_artifact(run_id, ARTIFACT_REQUIREMENTS, json.dumps({
        "app_name": "Demo", "port": 5060, "dependencies": ["flask"],
    }))
    am.save_artifact(run_id, ARTIFACT_BACKEND, (
        "from flask import Flask, jsonify\n"
        "app = Flask(__name__)\n\n"
        "@app.route('/api/ping')\n"
        "def ping():\n"
        "    return jsonify({'status': 'ok'})\n"
    ))
    am.save_artifact(run_id, ARTIFACT_FRONTEND, "<html><body>Demo</body></html>")
    engine.assemble(run_id)

    router = LLMRouter(completion_fn=fake_review_completion, sleeper=lambda s: None)
    qa = QAReviewerAgent(manager=am, router=router)
    report = qa.run(run_id)
    print("Scenario A report:", json.dumps(report.to_dict(), indent=2))
    assert report.passed is True
    assert all(report.static_checks.values())
    assert report.llm_review is not None
    am.delete_run(run_id)
    print("Scenario A passed.\n")

    # --- Scenario B: assembly never ran -> critical failure ---
    run_id_b = am.create_run()
    am.save_artifact(run_id_b, ARTIFACT_REQUIREMENTS, json.dumps({"app_name": "Broken"}))
    qa_b = QAReviewerAgent(manager=am, router=router)
    report_b = qa_b.run(run_id_b)
    print("Scenario B report:", json.dumps(report_b.to_dict(), indent=2))
    assert report_b.passed is False
    assert any("assembly_report.json" in issue for issue in report_b.critical_issues)
    am.delete_run(run_id_b)
    print("Scenario B passed.\n")

    # --- Scenario C: LLM router exhausted -> graceful degradation ---
    def always_fails(model_cfg, messages, **kwargs):
        raise RuntimeError("simulated provider outage")

    failing_router = LLMRouter(completion_fn=always_fails, sleeper=lambda s: None)
    run_id_c = am.create_run()
    am.save_artifact(run_id_c, ARTIFACT_REQUIREMENTS, json.dumps({
        "app_name": "Demo2", "dependencies": ["flask"],
    }))
    am.save_artifact(run_id_c, ARTIFACT_BACKEND, (
        "from flask import Flask\napp = Flask(__name__)\n"
    ))
    am.save_artifact(run_id_c, ARTIFACT_FRONTEND, "<html></html>")
    engine.assemble(run_id_c)

    qa_c = QAReviewerAgent(manager=am, router=failing_router)
    report_c = qa_c.run(run_id_c)
    print("Scenario C report:", json.dumps(report_c.to_dict(), indent=2))
    assert report_c.passed is True  # static checks alone still pass
    assert report_c.llm_review is None
    assert any("LLM qualitative review unavailable" in w for w in report_c.warnings)
    am.delete_run(run_id_c)
    print("Scenario C passed.\n")

    shutil.rmtree("project_files", ignore_errors=True)
    print("All qa_reviewer smoke-test scenarios passed.")