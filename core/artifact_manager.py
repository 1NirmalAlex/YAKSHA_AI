"""
core/artifact_manager.py
------------------------------------------------------------------------------
YAKSHA AI v2.0 — Artifact-Based Architecture Core Module

Why this exists (v1.0 problem it fixes):
    In v1.0, each agent returned its full generated code as a giant string
    that got passed through the CrewAI task chain and finally handed to
    FileWriterTool as a single JSON argument. That caused:
        - Context overwrite / truncation when the QA agent tried to merge
          everything at the end.
        - JSON parsing failures when large code blocks with quotes/newlines
          were serialized as tool-call arguments.

    ArtifactManager fixes this by giving every run an isolated folder on
    disk (runs/<run_id>/). Agents no longer pass code through the prompt
    chain at all — they call save_artifact() to persist their output as a
    named file, and downstream steps (QA, Assembly Engine) call
    read_artifact() to pull it back. Only small metadata (run_id, filename)
    ever needs to travel through an LLM tool call.
------------------------------------------------------------------------------
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import RUNS_DIR

logger = logging.getLogger("yaksha.artifact_manager")


class ArtifactError(Exception):
    """Base exception for all artifact-related failures."""


class RunNotFoundError(ArtifactError):
    """Raised when an operation targets a run_id that doesn't exist."""


class ArtifactNotFoundError(ArtifactError):
    """Raised when read_artifact() is called for a file that isn't there."""


@dataclass(frozen=True)
class ArtifactMeta:
    """Small, LLM-tool-call-friendly descriptor for a saved artifact."""
    run_id: str
    filename: str
    size_bytes: int
    saved_at: str  # ISO-8601 UTC timestamp


class ArtifactManager:
    """
    Manages the lifecycle of a single run's on-disk workspace:

        runs/<run_id>/
            requirements.json
            backend.py
            frontend.html
            ai_ml_module.py
            qa_report.json
            _manifest.json      <- bookkeeping: what's been saved, when

    All paths are resolved under RUNS_DIR and defensively checked so an
    agent can never write (or read) outside its own run folder.
    """

    def __init__(self, runs_dir: Path | str = RUNS_DIR) -> None:
        self.runs_dir = Path(runs_dir)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        # Parallel agents (backend/frontend/ai_ml) save into the SAME run at the
        # same time; the manifest is a read-modify-write file, so serialize it.
        self._manifest_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------

    def create_run(self, run_id: str | None = None) -> str:
        """
        Creates a fresh runs/<run_id>/ workspace and an empty manifest.
        If run_id is None, a UUID4 is generated. Returns the run_id used.
        """
        run_id = run_id or str(uuid.uuid4())
        run_path = self._run_path(run_id, create_if_missing=False)

        if run_path.exists():
            raise ArtifactError(
                f"Run '{run_id}' already exists at {run_path}. "
                f"Use a new run_id or call delete_run() first."
            )

        run_path.mkdir(parents=True, exist_ok=False)
        self._write_manifest(run_id, {})
        logger.info("Created run workspace: %s", run_path)
        return run_id

    def run_exists(self, run_id: str) -> bool:
        return self._run_path(run_id, create_if_missing=False).exists()

    def delete_run(self, run_id: str) -> None:
        """Removes a run's entire workspace. Safe no-op if it never existed."""
        run_path = self._run_path(run_id, create_if_missing=False)
        if run_path.exists():
            shutil.rmtree(run_path)
            logger.info("Deleted run workspace: %s", run_path)

    def list_runs(self) -> list[str]:
        """Returns all known run_ids currently on disk, newest first."""
        if not self.runs_dir.exists():
            return []
        runs = [p.name for p in self.runs_dir.iterdir() if p.is_dir()]
        runs.sort(
            key=lambda r: (self.runs_dir / r).stat().st_mtime, reverse=True
        )
        return runs

    # ------------------------------------------------------------------
    # Artifact save / read
    # ------------------------------------------------------------------

    def save_artifact(
        self, run_id: str, filename: str, content: str
    ) -> ArtifactMeta:
        """
        Persists `content` as `filename` inside runs/<run_id>/.
        This is the ONLY way agent output should reach disk — never pass
        large code strings back through the CrewAI task chain.

        Raises RunNotFoundError if the run workspace doesn't exist yet
        (call create_run() first).
        """
        run_path = self._run_path(run_id, create_if_missing=False)
        if not run_path.exists():
            raise RunNotFoundError(
                f"Cannot save artifact — run '{run_id}' does not exist. "
                f"Call create_run('{run_id}') first."
            )

        safe_filename = self._sanitize_filename(filename)
        file_path = run_path / safe_filename

        # Write atomically: temp file then rename, so a crash mid-write
        # never leaves a half-written artifact for QA/Assembly to read.
        tmp_path = file_path.with_suffix(file_path.suffix + ".tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(file_path)

        meta = ArtifactMeta(
            run_id=run_id,
            filename=safe_filename,
            size_bytes=file_path.stat().st_size,
            saved_at=datetime.now(timezone.utc).isoformat(),
        )
        self._update_manifest(run_id, safe_filename, meta)
        logger.info(
            "Saved artifact '%s' (%d bytes) for run '%s'",
            safe_filename, meta.size_bytes, run_id,
        )
        return meta

    def read_artifact(self, run_id: str, filename: str) -> str:
        """
        Returns the text content of a previously saved artifact.
        Raises ArtifactNotFoundError if it isn't there yet.
        """
        file_path = self._artifact_path(run_id, filename)
        if not file_path.exists():
            raise ArtifactNotFoundError(
                f"Artifact '{filename}' not found for run '{run_id}' "
                f"(looked in {file_path.parent})."
            )
        return file_path.read_text(encoding="utf-8")

    def artifact_exists(self, run_id: str, filename: str) -> bool:
        return self._artifact_path(run_id, filename).exists()

    def list_artifacts(self, run_id: str) -> list[ArtifactMeta]:
        """Returns metadata for every artifact saved so far in this run."""
        manifest = self._read_manifest(run_id)
        return [
            ArtifactMeta(
                run_id=run_id,
                filename=fname,
                size_bytes=meta["size_bytes"],
                saved_at=meta["saved_at"],
            )
            for fname, meta in manifest.items()
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_path(self, run_id: str, *, create_if_missing: bool) -> Path:
        if not run_id or "/" in run_id or "\\" in run_id or run_id in (".", ".."):
            raise ArtifactError(f"Invalid run_id: {run_id!r}")
        path = self.runs_dir / run_id
        if create_if_missing:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def _artifact_path(self, run_id: str, filename: str) -> Path:
        run_path = self._run_path(run_id, create_if_missing=False)
        return run_path / self._sanitize_filename(filename)

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """Prevents path traversal — agents only ever get a bare filename."""
        name = Path(filename).name
        if name != filename or not name:
            raise ArtifactError(
                f"Invalid artifact filename (must be a bare filename): {filename!r}"
            )
        return name

    def _manifest_path(self, run_id: str) -> Path:
        return self._run_path(run_id, create_if_missing=False) / "_manifest.json"

    def _read_manifest(self, run_id: str) -> dict[str, Any]:
        manifest_path = self._manifest_path(run_id)
        if not manifest_path.exists():
            return {}
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    def _write_manifest(self, run_id: str, data: dict[str, Any]) -> None:
        manifest_path = self._manifest_path(run_id)
        # Atomic replace so concurrent readers never see a half-written file.
        tmp_path = manifest_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp_path.replace(manifest_path)

    def _update_manifest(
        self, run_id: str, filename: str, meta: ArtifactMeta
    ) -> None:
        with self._manifest_lock:
            manifest = self._read_manifest(run_id)
            manifest[filename] = {
                "size_bytes": meta.size_bytes,
                "saved_at": meta.saved_at,
            }
            self._write_manifest(run_id, manifest)


# ------------------------------------------------------------------------
# Module-level convenience singleton (most callers just need one instance)
# ------------------------------------------------------------------------

artifact_manager = ArtifactManager()


if __name__ == "__main__":
    # Quick manual smoke test: python -m core.artifact_manager
    logging.basicConfig(level=logging.INFO)
    am = ArtifactManager()
    rid = am.create_run()
    am.save_artifact(rid, "requirements.json", json.dumps({"app": "demo"}))
    am.save_artifact(rid, "backend.py", "print('hello from backend')")
    print("Artifacts:", am.list_artifacts(rid))
    print("Read back:", am.read_artifact(rid, "backend.py"))
    am.delete_run(rid)