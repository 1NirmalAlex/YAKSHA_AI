"""
core/llm_router.py
------------------------------------------------------------------------------
YAKSHA AI v2.0 — Multi-LLM Router with Fallback, Retry Backoff & TPM Budgeting

Why this exists (v1.0 problems it fixes):
    1. Gemini 250k TPM Rate Limits (429 errors): agents would blow past
       Gemini's free-tier token budget mid-run with no recovery path.
    2. No fallback: a single provider hiccup (429/404/5xx) killed the whole
       crew run instead of failing over to the next configured model.

How it works:
    - core/config.py defines an ordered model chain per agent ROLE
      (e.g. "backend_dev" -> [groq-120b, gemini-flash]).
    - Before every call, the router does a PROACTIVE budget check: it keeps
      a rolling 60-second token-usage window per model and refuses to call
      a model that would cross `tpm_limit * safety_margin`, skipping
      straight to the next model in the chain instead of waiting for a 429.
    - If a call is attempted and still fails with a retryable error
      (429 / 404 / 5xx per config.RETRY.retry_on_status), the router retries
      that SAME model with exponential backoff + jitter up to
      config.RETRY.max_retries times before giving up on it and moving to
      the next model in the chain.
    - Only after every model in the role's chain is exhausted does
      `complete()` raise LLMRouterError, with the full attempt log attached.

This module never decides WHAT to generate — that's the agents' job. It only
decides WHICH model handles a given call, and how patiently to retry it.
------------------------------------------------------------------------------
"""

from __future__ import annotations

import logging
import random
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from core.config import (
    API_KEYS,
    RATE_LIMIT,
    RETRY,
    ModelConfig,
    get_model_chain,
)

logger = logging.getLogger("yaksha.llm_router")

Message = dict[str, str]  # {"role": "user"/"system"/"assistant", "content": str}

# A completion function has this shape: (ModelConfig, messages, **kwargs) -> raw_response
CompletionFn = Callable[..., Any]


# ------------------------------------------------------------------------
# Exceptions
# ------------------------------------------------------------------------

class LLMRouterError(Exception):
    """Raised when every model in a role's fallback chain has been exhausted."""

    def __init__(self, role: str, attempts: list[str]):
        self.role = role
        self.attempts = attempts
        joined = "\n  - ".join(attempts) if attempts else "(no attempts recorded)"
        super().__init__(
            f"LLM router exhausted every model configured for role '{role}'. "
            f"Attempts:\n  - {joined}"
        )


# ------------------------------------------------------------------------
# Result type
# ------------------------------------------------------------------------

@dataclass
class RouterResult:
    text: str
    provider: str
    model_name: str
    role: str
    attempt: int          # 1-indexed attempt number that finally succeeded
    tokens_used: int
    warnings: list[str] = field(default_factory=list)


# ------------------------------------------------------------------------
# Token estimation (pre-flight budget checks don't require a real tokenizer)
# ------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, int(len(text) / RATE_LIMIT.chars_per_token_estimate))


def _estimate_messages_tokens(messages: list[Message]) -> int:
    joined = "\n".join(m.get("content", "") for m in messages)
    return estimate_tokens(joined)


# ------------------------------------------------------------------------
# Rolling per-model token usage window (drives proactive TPM budgeting)
# ------------------------------------------------------------------------

class _UsageWindow:
    """Tracks tokens consumed by a single model over a trailing time window."""

    def __init__(self, window_seconds: float = 60.0) -> None:
        self.window_seconds = window_seconds
        self._entries: list[tuple[float, int]] = []

    def add(self, tokens: int, now: float) -> None:
        self._entries.append((now, tokens))

    def current_usage(self, now: float) -> int:
        cutoff = now - self.window_seconds
        self._entries = [(t, tok) for t, tok in self._entries if t >= cutoff]
        return sum(tok for _, tok in self._entries)


# ------------------------------------------------------------------------
# The router
# ------------------------------------------------------------------------

class LLMRouter:
    """
    Routes a completion request for a given agent ROLE across its configured
    model chain, applying proactive TPM budgeting and reactive retry/backoff.

    `completion_fn` is injectable so this class is fully unit-testable
    without network access or real API keys — production code leaves it as
    the default, which calls litellm.
    """

    def __init__(
        self,
        completion_fn: Optional[CompletionFn] = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._completion_fn: CompletionFn = completion_fn or self._litellm_completion
        self._clock = clock
        self._sleep = sleeper
        self._usage: dict[str, _UsageWindow] = defaultdict(_UsageWindow)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def complete(
        self,
        role: str,
        messages: list[Message],
        max_output_tokens: int = 2048,
        **kwargs: Any,
    ) -> RouterResult:
        """
        Attempts the completion across every model configured for `role`,
        in priority order, applying budget checks and retry/backoff.
        Raises LLMRouterError only if every model in the chain fails.
        """
        chain = get_model_chain(role)
        prompt_tokens_est = _estimate_messages_tokens(messages)
        projected_tokens = prompt_tokens_est + max_output_tokens

        attempt_log: list[str] = []

        for model_cfg in chain:
            if not self._has_budget(model_cfg, projected_tokens):
                msg = (
                    f"[{model_cfg.model_name}] skipped — projected usage "
                    f"({projected_tokens} tok) would exceed "
                    f"{RATE_LIMIT.safety_margin:.0%} of its {model_cfg.tpm_limit} TPM budget"
                )
                logger.warning(msg)
                attempt_log.append(msg)
                continue

            result = self._call_with_retry(
                role, model_cfg, messages, max_output_tokens, attempt_log, **kwargs
            )
            if result is not None:
                if attempt_log:
                    result.warnings = list(attempt_log)
                return result

        raise LLMRouterError(role=role, attempts=attempt_log)

    # ------------------------------------------------------------------
    # Budgeting
    # ------------------------------------------------------------------

    def _has_budget(self, model_cfg: ModelConfig, projected_tokens: int) -> bool:
        now = self._clock()
        used = self._usage[model_cfg.model_name].current_usage(now)
        budget = model_cfg.tpm_limit * RATE_LIMIT.safety_margin
        return (used + projected_tokens) <= budget

    def _record_usage(self, model_name: str, tokens: int) -> None:
        self._usage[model_name].add(tokens, self._clock())

    # ------------------------------------------------------------------
    # Retry / backoff around a single model
    # ------------------------------------------------------------------

    def _call_with_retry(
        self,
        role: str,
        model_cfg: ModelConfig,
        messages: list[Message],
        max_output_tokens: int,
        attempt_log: list[str],
        **kwargs: Any,
    ) -> Optional[RouterResult]:
        total_tries = RETRY.max_retries + 1  # +1 for the initial attempt

        for attempt in range(1, total_tries + 1):
            try:
                raw = self._completion_fn(
                    model_cfg, messages, max_tokens=max_output_tokens, **kwargs
                )
                text, tokens_used = self._parse_response(raw)
                self._record_usage(model_cfg.model_name, tokens_used)
                logger.info(
                    "[%s] role=%s succeeded on attempt %d/%d (%d tokens)",
                    model_cfg.model_name, role, attempt, total_tries, tokens_used,
                )
                return RouterResult(
                    text=text,
                    provider=model_cfg.provider,
                    model_name=model_cfg.model_name,
                    role=role,
                    attempt=attempt,
                    tokens_used=tokens_used,
                )
            except Exception as exc:  # noqa: BLE001 — deliberately broad: any provider SDK error
                status = self._extract_status_code(exc)
                retryable = (
                    status in RETRY.retry_on_status
                    if status is not None
                    else self._looks_retryable(exc)
                )
                is_last_try = attempt == total_tries

                if not retryable or is_last_try:
                    msg = (
                        f"[{model_cfg.model_name}] gave up after "
                        f"{attempt}/{total_tries} attempt(s), status={status}: {exc}"
                    )
                    logger.error(msg)
                    attempt_log.append(msg)
                    return None

                delay = min(
                    RETRY.base_delay_seconds * (2 ** (attempt - 1)),
                    RETRY.max_delay_seconds,
                )
                jitter = delay * random.uniform(0, 0.25)
                total_delay = round(delay + jitter, 2)
                logger.warning(
                    "[%s] transient error (status=%s) on attempt %d/%d, "
                    "retrying in %.2fs: %s",
                    model_cfg.model_name, status, attempt, total_tries, total_delay, exc,
                )
                self._sleep(total_delay)

        return None  # defensive; loop always returns above

    # ------------------------------------------------------------------
    # Error classification
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_status_code(exc: BaseException) -> Optional[int]:
        """
        Tries several common shapes used by provider SDKs (OpenAI-style,
        litellm, requests) to find an HTTP-like status code on an exception.
        """
        for attr in ("status_code", "http_status", "code"):
            val = getattr(exc, attr, None)
            if isinstance(val, int):
                return val

        response = getattr(exc, "response", None)
        if response is not None:
            val = getattr(response, "status_code", None)
            if isinstance(val, int):
                return val

        # Last resort: scan the message text for a 3-digit HTTP-looking code.
        match = re.search(r"\b([1-5]\d{2})\b", str(exc))
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def _looks_retryable(exc: BaseException) -> bool:
        """Fallback classification by exception class name when no status code is found."""
        name = type(exc).__name__.lower()
        return any(
            token in name
            for token in ("ratelimit", "timeout", "connection", "servererror", "notfound", "apierror")
        )

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_response(raw: Any) -> tuple[str, int]:
        """
        Normalizes a provider response into (text, tokens_used).
        Supports: litellm/OpenAI-style objects, plain dicts, and a raw
        (text, tokens) tuple (handy for injected test completion_fns).
        """
        if isinstance(raw, tuple) and len(raw) == 2:
            return raw[0], int(raw[1])

        text: str
        try:
            text = raw.choices[0].message.content  # litellm / OpenAI SDK object
        except AttributeError:
            try:
                text = raw["choices"][0]["message"]["content"]  # plain dict
            except Exception:
                text = str(raw)

        tokens: Optional[int] = None
        usage = getattr(raw, "usage", None)
        if usage is None and isinstance(raw, dict):
            usage = raw.get("usage")
        if usage is not None:
            tokens = getattr(usage, "total_tokens", None)
            if tokens is None and isinstance(usage, dict):
                tokens = usage.get("total_tokens")

        if tokens is None:
            tokens = estimate_tokens(text)
        return text, int(tokens)

    # ------------------------------------------------------------------
    # Default (production) completion function — wraps litellm
    # ------------------------------------------------------------------

    @staticmethod
    def _litellm_completion(
        model_cfg: ModelConfig, messages: list[Message], **kwargs: Any
    ) -> Any:
        try:
            import litellm
        except ImportError as exc:
            raise RuntimeError(
                "litellm is not installed. Install it (`pip install litellm`) "
                "for live LLM calls, or inject a completion_fn for testing."
            ) from exc

        return litellm.completion(
            model=model_cfg.model_name,
            messages=messages,
            api_key=API_KEYS.get(model_cfg.provider) or None,
            **kwargs,
        )


# Module-level convenience singleton, mirroring artifact_manager/assembly_engine.
llm_router = LLMRouter()


if __name__ == "__main__":
    # Manual smoke test: python -m core.llm_router
    # Exercises (a) retry-then-succeed on the same model, (b) full fallback
    # to the next model after exhausting retries, (c) proactive budget skip —
    # all WITHOUT any network calls or real API keys.
    logging.basicConfig(level=logging.INFO)

    class FakeRateLimitError(Exception):
        status_code = 429

    call_counts: dict[str, int] = defaultdict(int)

    def fake_completion(model_cfg: ModelConfig, messages, **kwargs):
        call_counts[model_cfg.model_name] += 1
        n = call_counts[model_cfg.model_name]

        if model_cfg.model_name == "groq/openai/gpt-oss-120b" and n < 3:
            # Fails twice, succeeds on the 3rd attempt.
            raise FakeRateLimitError("rate limited, try again")

        if model_cfg.model_name == "gemini-3.6-flash" and n <= 10:
            # Always fails -> forces fallback to the next model in the chain.
            raise FakeRateLimitError("gemini is out of quota")

        return ("Hello from " + model_cfg.model_name, 42)

    router = LLMRouter(
        completion_fn=fake_completion,
        sleeper=lambda s: None,  # skip real sleeping in the smoke test
    )

    print("--- Scenario A: retry-then-succeed on the primary model ---")
    result = router.complete("backend_dev", [{"role": "user", "content": "build me an app"}])
    print(result)
    assert result.model_name == "groq/openai/gpt-oss-120b" and result.attempt == 3

    print("\n--- Scenario B: primary exhausts retries, falls back to next model ---")
    result = router.complete("pm_architect", [{"role": "user", "content": "plan an app"}])
    print(result)
    assert result.provider == "groq"  # gemini (primary for pm_architect) always fails above

    print("\n--- Scenario C: proactive budget skip ---")
    tight_router = LLMRouter(completion_fn=fake_completion, sleeper=lambda s: None)
    # Pre-load gemini's usage window to just under its cap so the very next
    # call's projected usage pushes it over the safety margin -> skipped.
    tight_router._usage["gemini-3.6-flash"].add(249_000, tight_router._clock())
    result = tight_router.complete("qa_reviewer", [{"role": "user", "content": "x" * 100}])
    print(result)
    assert result.provider == "groq"
    assert any("skipped" in w for w in result.warnings)

    print("\nAll smoke-test scenarios passed.")