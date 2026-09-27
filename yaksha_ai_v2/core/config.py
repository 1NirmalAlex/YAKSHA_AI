"""
core/config.py
------------------------------------------------------------------------------
YAKSHA AI v2.0 — Centralized Base Configuration

Single source of truth for:
    - Filesystem paths (runs workspace, final output location)
    - LLM provider/model definitions used by the router
    - Rate-limit budgets (e.g. Gemini 250k TPM) used for pre-flight checks
    - Retry / backoff behavior for llm_router.py
    - Event queue tuning

No other module should hardcode a path, model name, or limit — import from
here instead so Phase 2+ changes stay in one place.
------------------------------------------------------------------------------
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# ------------------------------------------------------------------------
# 1. Base Paths
# ------------------------------------------------------------------------

# Project root = the directory that contains this "core" package's parent.
BASE_DIR: Path = Path(__file__).resolve().parent.parent

# Where each run gets its own isolated workspace: runs/<run_id>/
RUNS_DIR: Path = BASE_DIR / "runs"

# Where the final assembled, production-ready app is delivered.
PROJECT_FILES_DIR: Path = BASE_DIR / "project_files"

# Canonical artifact filenames every agent/module agrees on.
ARTIFACT_REQUIREMENTS = "requirements.json"
ARTIFACT_BACKEND = "backend.py"
ARTIFACT_FRONTEND = "frontend.html"
ARTIFACT_AI_ML = "ai_ml_module.py"
ARTIFACT_QA_REPORT = "qa_report.json"
FINAL_OUTPUT_FILENAME = "app.py"

# Ensure the top-level directories exist as soon as config is imported.
for _dir in (RUNS_DIR, PROJECT_FILES_DIR):
    _dir.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------------------
# 2. LLM Provider / Model Configuration
# ------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelConfig:
    """Describes a single callable model target for the LLM router."""
    provider: str            # "gemini" | "groq"
    model_name: str          # exact model string passed to the SDK/LiteLLM
    tpm_limit: int           # tokens-per-minute budget for this model/tier
    priority: int = 0        # lower = tried first within a role's chain


# Per-agent-role model chains. Each role has a PRIMARY model and one or more
# FALLBACKS. llm_router.py walks this list in priority order and switches on
# 429 / 404 / timeout errors.
MODEL_ROUTES: dict[str, list[ModelConfig]] = {
    "pm_architect": [
        ModelConfig(provider="gemini", model_name="gemini-3.6-flash",
                    tpm_limit=250_000, priority=0),
        ModelConfig(provider="groq", model_name="groq/openai/gpt-oss-120b",
                    tpm_limit=300_000, priority=1),
    ],
    "backend_dev": [
        ModelConfig(provider="groq", model_name="groq/openai/gpt-oss-120b",
                    tpm_limit=300_000, priority=0),
        ModelConfig(provider="gemini", model_name="gemini-3.6-flash",
                    tpm_limit=250_000, priority=1),
    ],
    "frontend_dev": [
        ModelConfig(provider="groq", model_name="groq/openai/gpt-oss-120b",
                    tpm_limit=300_000, priority=0),
        ModelConfig(provider="gemini", model_name="gemini-3.6-flash",
                    tpm_limit=250_000, priority=1),
    ],
    "ai_ml_specialist": [
        ModelConfig(provider="groq", model_name="groq/openai/gpt-oss-20b",
                    tpm_limit=300_000, priority=0),
        ModelConfig(provider="gemini", model_name="gemini-3.6-flash",
                    tpm_limit=250_000, priority=1),
    ],
    "qa_reviewer": [
        ModelConfig(provider="gemini", model_name="gemini-3.6-flash",
                    tpm_limit=250_000, priority=0),
        ModelConfig(provider="groq", model_name="groq/openai/gpt-oss-120b",
                    tpm_limit=300_000, priority=1),
    ],
}

# API keys are read from environment (.env loaded by main.py / dashboard).
API_KEYS: dict[str, str] = {
    "gemini": os.getenv("GEMINI_API_KEY", ""),
    "groq": os.getenv("GROQ_API_KEY", ""),
}


# ------------------------------------------------------------------------
# 3. Rate-Limit / Token Budget Settings
# ------------------------------------------------------------------------

@dataclass(frozen=True)
class RateLimitConfig:
    # Stop sending to a model once estimated usage crosses this fraction
    # of its tpm_limit, and fail over to the next model in the chain.
    safety_margin: float = 0.85
    # Rough chars-per-token estimate used for pre-flight budget checks
    # when a real tokenizer isn't available.
    chars_per_token_estimate: float = 4.0


RATE_LIMIT = RateLimitConfig()


# ------------------------------------------------------------------------
# 4. Retry / Backoff Settings (used by llm_router.py)
# ------------------------------------------------------------------------

@dataclass(frozen=True)
class RetryConfig:
    max_retries: int = 4
    base_delay_seconds: float = 2.0     # backoff = base * (2 ** attempt)
    max_delay_seconds: float = 30.0
    retry_on_status: tuple[int, ...] = (429, 404, 500, 502, 503)


RETRY = RetryConfig()


# ------------------------------------------------------------------------
# 5. Event Queue / Streamlit Dashboard Settings
# ------------------------------------------------------------------------

@dataclass(frozen=True)
class EventQueueConfig:
    max_queue_size: int = 1000
    poll_interval_seconds: float = 0.3   # how often Streamlit polls the queue


EVENT_QUEUE = EventQueueConfig()


# ------------------------------------------------------------------------
# 6. Misc / Execution Settings
# ------------------------------------------------------------------------

CREW_EXECUTION_TIMEOUT_SECONDS: int = 900   # 15 min safety timeout per run
LOG_LEVEL: str = os.getenv("YAKSHA_LOG_LEVEL", "INFO")


def get_model_chain(role: str) -> list[ModelConfig]:
    """
    Returns the ordered (primary -> fallback) model chain for an agent role.
    Raises KeyError with a clear message if the role isn't configured,
    instead of silently returning an empty list.
    """
    if role not in MODEL_ROUTES:
        raise KeyError(
            f"No model route configured for role '{role}'. "
            f"Known roles: {list(MODEL_ROUTES.keys())}"
        )
    return sorted(MODEL_ROUTES[role], key=lambda m: m.priority)