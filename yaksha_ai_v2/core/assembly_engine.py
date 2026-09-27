"""
core/assembly_engine.py
------------------------------------------------------------------------------
YAKSHA AI v2.0 — Deterministic Assembly Engine

Why this exists (v1.0 problem it fixes):
    In v1.0, the QA Agent (an LLM) was responsible for merging the Backend
    Developer's and Frontend Developer's generated code into one final
    app.py, then calling FileWriterTool with the whole thing as a JSON
    argument. Two things broke:
        1. Large outputs got silently truncated/forgotten when the LLM
           tried to hold and reproduce 15k-line UIs in its own output.
        2. FileWriterTool's JSON argument corrupted on quotes/newlines
           inside the merged code.

    This module replaces that LLM merge step entirely. It is PURE PYTHON —
    no LLM call happens anywhere in this file. It reads the three artifacts
    an agent crew already saved to disk via ArtifactManager, validates and
    merges them with the `ast` module (never string-guessing), and writes
    a syntactically-verified, ready-to-run Flask app to project_files/.

CONTRACT the agents must follow (documented here as the single source of
truth for Backend/Frontend/PM prompt design):

    requirements.json
        {
          "app_name": str,                # required
          "port": int,                    # optional, default 5000
          "frontend_route": str,          # optional, default "/"
          "flask_app_var": str,           # optional, default "app"
          "dependencies": [str, ...]      # optional, pip package names
        }

    backend.py
        - A plain Python module.
        - Must instantiate exactly one Flask app: `app = Flask(__name__)`
          (variable name configurable via requirements.json/flask_app_var).
        - Must NOT define a route for `frontend_route` — the Assembly
          Engine injects that route itself to serve frontend.html.
        - Must NOT include an `if __name__ == "__main__":` block — the
          Assembly Engine generates the run block using requirements.json's
          port. If present anyway, it is stripped automatically.

    frontend.html
        - Raw, self-contained HTML (Tailwind CDN + inline/interactive JS).
        - Treated as an opaque string — embedded verbatim, never parsed
          or modified.
------------------------------------------------------------------------------
"""

from __future__ import annotations

import ast
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from core.artifact_manager import ArtifactManager, artifact_manager
from core.config import (
    ARTIFACT_BACKEND,
    ARTIFACT_FRONTEND,
    ARTIFACT_REQUIREMENTS,
    FINAL_OUTPUT_FILENAME,
    PROJECT_FILES_DIR,
)

logger = logging.getLogger("yaksha.assembly_engine")

ASSEMBLY_REPORT_FILENAME = "assembly_report.json"

DEFAULT_PORT = 5000
DEFAULT_FRONTEND_ROUTE = "/"
DEFAULT_FLASK_APP_VAR = "app"


class AssemblyError(Exception):
    """Raised when artifacts are missing, invalid, or fail to merge safely."""


@dataclass
class AssemblyResult:
    run_id: str
    output_path: str
    output_size_bytes: int
    app_name: str
    flask_app_var: str
    frontend_route: str
    port: int
    dependencies: list[str]
    warnings: list[str] = field(default_factory=list)
    assembled_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "output_path": self.output_path,
            "output_size_bytes": self.output_size_bytes,
            "app_name": self.app_name,
            "flask_app_var": self.flask_app_var,
            "frontend_route": self.frontend_route,
            "port": self.port,
            "dependencies": self.dependencies,
            "warnings": self.warnings,
            "assembled_at": self.assembled_at,
        }


class AssemblyEngine:
    """
    Deterministically assembles backend.py + frontend.html + requirements.json
    (all read via ArtifactManager) into a single, runnable project_files/app.py.

    No LLM calls happen in this class. Every decision is made by parsing the
    backend source with `ast` and applying fixed rules.
    """

    def __init__(
        self,
        manager: ArtifactManager = artifact_manager,
        output_root: Path | str = PROJECT_FILES_DIR,
    ) -> None:
        self.manager = manager
        self.output_root = Path(output_root)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def assemble(self, run_id: str) -> AssemblyResult:
        warnings: list[str] = []

        requirements = self._load_requirements(run_id)
        backend_source = self.manager.read_artifact(run_id, ARTIFACT_BACKEND)
        frontend_html = self.manager.read_artifact(run_id, ARTIFACT_FRONTEND)

        app_name = requirements.get("app_name") or "YakshaGeneratedApp"
        port = int(requirements.get("port", DEFAULT_PORT))
        frontend_route = requirements.get("frontend_route", DEFAULT_FRONTEND_ROUTE)
        flask_app_var = requirements.get("flask_app_var", DEFAULT_FLASK_APP_VAR)
        dependencies = requirements.get("dependencies", []) or []

        tree = self._parse_backend(backend_source)

        actual_app_var = self._find_flask_app_var(tree)
        if actual_app_var is None:
            raise AssemblyError(
                f"backend.py for run '{run_id}' does not instantiate a Flask "
                f"app (expected `<name> = Flask(__name__)`). Cannot assemble."
            )
        if actual_app_var != flask_app_var:
            warnings.append(
                f"requirements.json specified flask_app_var='{flask_app_var}' "
                f"but backend.py actually uses '{actual_app_var}'. "
                f"Using '{actual_app_var}' (source of truth)."
            )
            flask_app_var = actual_app_var

        existing_routes = self._find_existing_routes(tree, flask_app_var)
        inject_frontend_route = frontend_route not in existing_routes
        if not inject_frontend_route:
            warnings.append(
                f"backend.py already defines a route for '{frontend_route}'. "
                f"Assembly Engine will NOT inject a duplicate frontend route; "
                f"backend.py is responsible for serving the frontend at that path."
            )

        cleaned_backend_source = self._strip_main_guard(backend_source)
        cleaned_backend_source = self._ensure_flask_import(cleaned_backend_source)

        final_source = self._render_final_source(
            app_name=app_name,
            backend_source=cleaned_backend_source,
            frontend_html=frontend_html,
            flask_app_var=flask_app_var,
            frontend_route=frontend_route,
            inject_frontend_route=inject_frontend_route,
            port=port,
            dependencies=dependencies,
        )

        # Hard safety gate: never write a file that doesn't even parse.
        try:
            ast.parse(final_source)
        except SyntaxError as exc:
            raise AssemblyError(
                f"Assembled source for run '{run_id}' failed syntax validation: {exc}"
            ) from exc

        output_path = self._write_output(run_id, final_source)

        result = AssemblyResult(
            run_id=run_id,
            output_path=str(output_path),
            output_size_bytes=output_path.stat().st_size,
            app_name=app_name,
            flask_app_var=flask_app_var,
            frontend_route=frontend_route,
            port=port,
            dependencies=dependencies,
            warnings=warnings,
        )

        # Persist the report as an artifact too, so QA can read it without
        # re-running assembly logic itself.
        self.manager.save_artifact(
            run_id, ASSEMBLY_REPORT_FILENAME, json.dumps(result.to_dict(), indent=2)
        )

        for w in warnings:
            logger.warning("[run=%s] %s", run_id, w)
        logger.info(
            "Assembled run '%s' -> %s (%d bytes)",
            run_id, output_path, result.output_size_bytes,
        )
        return result

    # ------------------------------------------------------------------
    # Loading & validating inputs
    # ------------------------------------------------------------------

    def _load_requirements(self, run_id: str) -> dict:
        raw = self.manager.read_artifact(run_id, ARTIFACT_REQUIREMENTS)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AssemblyError(
                f"requirements.json for run '{run_id}' is not valid JSON: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise AssemblyError(
                f"requirements.json for run '{run_id}' must be a JSON object."
            )
        return data

    def _parse_backend(self, source: str) -> ast.Module:
        try:
            return ast.parse(source)
        except SyntaxError as exc:
            raise AssemblyError(f"backend.py failed to parse: {exc}") from exc

    # ------------------------------------------------------------------
    # AST inspection helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_flask_app_var(tree: ast.Module) -> str | None:
        """
        Finds the variable assigned a `Flask(...)` (or `flask.Flask(...)`)
        call at module top level, e.g.:
            app = Flask(__name__)
            my_app = flask.Flask(__name__)
        Returns the variable name, or None if not found.
        """
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

    @staticmethod
    def _find_existing_routes(tree: ast.Module, app_var: str) -> set[str]:
        """
        Collects every path string passed to `@<app_var>.route("...")`
        (or `.get`/`.post`/etc. shorthand decorators) anywhere in the module.
        """
        routes: set[str] = set()
        route_like_attrs = {"route", "get", "post", "put", "delete", "patch"}

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call):
                    continue
                if not isinstance(dec.func, ast.Attribute):
                    continue
                if dec.func.attr not in route_like_attrs:
                    continue
                if not (
                    isinstance(dec.func.value, ast.Name)
                    and dec.func.value.id == app_var
                ):
                    continue
                if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(
                    dec.args[0].value, str
                ):
                    routes.add(dec.args[0].value)
        return routes

    @staticmethod
    def _is_main_guard(node: ast.stmt) -> bool:
        """True if `node` is `if __name__ == "__main__":` (either operand order)."""
        if not isinstance(node, ast.If):
            return False
        test = node.test
        if not isinstance(test, ast.Compare) or len(test.ops) != 1:
            return False
        if not isinstance(test.ops[0], ast.Eq):
            return False

        def is_name_dunder(n: ast.expr) -> bool:
            return isinstance(n, ast.Name) and n.id == "__name__"

        def is_main_str(n: ast.expr) -> bool:
            return isinstance(n, ast.Constant) and n.value == "__main__"

        left, right = test.left, test.comparators[0]
        return (is_name_dunder(left) and is_main_str(right)) or (
            is_main_str(left) and is_name_dunder(right)
        )

    def _strip_main_guard(self, source: str) -> str:
        """Removes any top-level `if __name__ == '__main__':` block from source."""
        tree = ast.parse(source)
        guard_nodes = [n for n in tree.body if self._is_main_guard(n)]
        if not guard_nodes:
            return source

        lines = source.splitlines(keepends=True)
        # Remove from the bottom up so earlier line numbers stay valid.
        for node in sorted(guard_nodes, key=lambda n: n.lineno, reverse=True):
            start = node.lineno - 1
            end = getattr(node, "end_lineno", node.lineno)
            del lines[start:end]
        return "".join(lines)

    @staticmethod
    def _ensure_flask_import(source: str) -> str:
        """Prepends `from flask import Flask` if the module doesn't already import it."""
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "flask":
                if any(alias.name == "Flask" for alias in node.names):
                    return source
            if isinstance(node, ast.Import):
                if any(alias.name == "flask" for alias in node.names):
                    return source  # `import flask` covers `flask.Flask(...)` usage
        return "from flask import Flask\n" + source

    # ------------------------------------------------------------------
    # Rendering the final file
    # ------------------------------------------------------------------

    @staticmethod
    def _render_final_source(
        *,
        app_name: str,
        backend_source: str,
        frontend_html: str,
        flask_app_var: str,
        frontend_route: str,
        inject_frontend_route: bool,
        port: int,
        dependencies: list[str],
    ) -> str:
        header = (
            f'"""\n'
            f"{app_name}\n"
            f"Auto-assembled by YAKSHA AI v2.0 Assembly Engine — do not edit by hand;\n"
            f"regenerate via the agent crew instead.\n"
            f"Dependencies: {', '.join(dependencies) if dependencies else '(none declared)'}\n"
            f'"""\n\n'
        )

        # frontend.html is embedded as a JSON string literal. JSON's escaping
        # rules (quotes, backslashes, newlines, unicode) are a strict subset
        # of Python string-literal syntax, so this is a safe, deterministic
        # way to inline arbitrary HTML/JS without triple-quote collisions.
        frontend_literal = json.dumps(frontend_html)
        frontend_block = (
            "# --- Frontend markup (embedded verbatim by Assembly Engine) ---\n"
            f"FRONTEND_HTML = {frontend_literal}\n\n"
        )

        route_block = ""
        if inject_frontend_route:
            route_block = (
                "\n\n# --- Frontend route (injected by Assembly Engine) ---\n"
                f'@{flask_app_var}.route({json.dumps(frontend_route)})\n'
                f"def _yaksha_serve_frontend():\n"
                f"    return FRONTEND_HTML\n"
            )

        run_block = (
            "\n\n# --- Entry point (generated by Assembly Engine) ---\n"
            "if __name__ == \"__main__\":\n"
            f"    {flask_app_var}.run(host=\"0.0.0.0\", port={port}, debug=False)\n"
        )

        body = backend_source
        if not body.endswith("\n"):
            body += "\n"

        return header + frontend_block + body + route_block + run_block

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def _write_output(self, run_id: str, final_source: str) -> Path:
        run_output_dir = self.output_root / run_id
        run_output_dir.mkdir(parents=True, exist_ok=True)
        output_path = run_output_dir / FINAL_OUTPUT_FILENAME

        tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
        tmp_path.write_text(final_source, encoding="utf-8")
        tmp_path.replace(output_path)
        return output_path


# Module-level convenience singleton, mirroring artifact_manager's pattern.
assembly_engine = AssemblyEngine()


if __name__ == "__main__":
    # Manual smoke test: python -m core.assembly_engine
    logging.basicConfig(level=logging.INFO)

    am = artifact_manager
    rid = am.create_run()

    am.save_artifact(rid, ARTIFACT_REQUIREMENTS, json.dumps({
        "app_name": "Demo Habit Tracker",
        "port": 5050,
        "dependencies": ["flask"],
    }))
    am.save_artifact(rid, ARTIFACT_BACKEND, (
        "from flask import Flask, jsonify\n"
        "app = Flask(__name__)\n\n"
        "@app.route('/api/ping')\n"
        "def ping():\n"
        "    return jsonify({'status': 'ok'})\n\n"
        "if __name__ == '__main__':\n"
        "    app.run(debug=True)\n"
    ))
    am.save_artifact(rid, ARTIFACT_FRONTEND, (
        "<html><body><h1>Demo</h1>"
        "<script>console.log(\"has 'quotes' and \\\"escapes\\\"\");</script>"
        "</body></html>"
    ))

    engine = AssemblyEngine(manager=am)
    result = engine.assemble(rid)
    print(json.dumps(result.to_dict(), indent=2))
    print("\n--- Assembled file preview ---\n")
    print(Path(result.output_path).read_text()[:500])

    am.delete_run(rid)