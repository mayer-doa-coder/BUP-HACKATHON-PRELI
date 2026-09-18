"""Bounded, failure-class-specific interpretation retries.

Not a generic retry loop. Guide §20 makes the point sharply: a 429, a provider 5xx, a refusal,
a truncated response, a schema violation and a semantic violation are six different problems,
and treating them as one wastes the single retry the latency budget affords. So each class has
its own response:

============================  =========================================================
failure                       response
============================  =========================================================
provider 5xx / connection     one short-backoff retry, budget permitting
provider timeout              one retry with the remaining budget as the timeout
provider 429                  honor ``retry_after`` if it fits, else the backup provider
refusal / truncation          one bounded retry
schema violation              one repair call listing the structural problems
semantic guardrail violation  one focused repair re-reading the ORIGINAL notes
directive-LP infeasible       one focused reinterpretation (see :meth:`reinterpret_for_feasibility`)
============================  =========================================================

Two rules hold throughout:

* **Attempts are capped** by ``LLM_MAX_ATTEMPTS`` and by the request deadline. A retry that
  cannot finish in time is worse than no retry, because the request fails either way and the
  slow path also burns the provider quota.
* **A repair never supplies the answer.** Feedback describes what was wrong structurally or
  which rule was broken; it never says what the directive should have been. Otherwise the
  pipeline would look correct while the model's actual understanding stayed wrong.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import StrEnum

from app.cache.request_cache import TtlLruCache, build_cache, parser_cache_key
from app.config import Settings, get_settings
from app.guardrails.directive_validator import GuardrailReport, validate_directives
from app.llm.base import (
    InterpreterError,
    MalformedModelOutput,
    ModelRefusal,
    ModelTruncated,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.llm.interpreter import LlmDirectiveInterpreter
from app.llm.prompts import (
    build_feasibility_repair_note,
    build_schema_repair_note,
    build_semantic_repair_note,
    build_system_prompt,
    build_user_payload,
)
from app.schemas.directive import DirectiveInterpretation
from app.schemas.request import OptimizeRequest
from app.services.deadline import Deadline

logger = logging.getLogger("gridwise.repair")

#: Short pause before retrying a transport-level failure. Long enough to clear a blip, short
#: enough to leave room for the retry itself.
TRANSPORT_BACKOFF_SECONDS = 0.25

#: A retry is only started if at least this much budget remains; otherwise it cannot land.
MINIMUM_ATTEMPT_SECONDS = 0.5


class RepairReason(StrEnum):
    """Why a second attempt happened. Recorded for telemetry, not shown to callers."""

    NONE = "none"
    TRANSPORT = "transport"
    RATE_LIMIT = "rate_limit"
    REFUSAL = "refusal"
    TRUNCATION = "truncation"
    SCHEMA = "schema"
    SEMANTIC = "semantic"
    FEASIBILITY = "feasibility"


@dataclass(frozen=True)
class _Decision:
    """How to respond to one provider-level failure."""

    reason: RepairReason
    interpreter: LlmDirectiveInterpreter
    repair_note: str | None = None
    #: Pause before the next attempt. Only meaningful when retrying the *same* provider.
    wait_seconds: float = 0.0


@dataclass
class InterpretationRun:
    """Result of running the interpretation path, including how it got there."""

    directives: list[DirectiveInterpretation] = field(default_factory=list)
    ok: bool = False
    attempts: int = 0
    repairs: list[RepairReason] = field(default_factory=list)
    provider: str = ""
    model_version: str = ""
    llm_latency_ms: float = 0.0
    used_backup: bool = False
    failure_codes: list[str] = field(default_factory=list)
    last_error: str = ""
    cache_hit: bool = False


class InterpretationRunner:
    """Owns the attempt budget for one request's interpretation."""

    def __init__(
        self,
        interpreter: LlmDirectiveInterpreter,
        settings: Settings | None = None,
        backup: LlmDirectiveInterpreter | None = None,
        cache: TtlLruCache | None = None,
    ) -> None:
        self._interpreter = interpreter
        self._settings = settings or get_settings()
        self._backup = backup
        self._cache = cache if cache is not None else build_cache(self._settings)
        # Separate from the request-level limit: the provider has its own quota and rate limits,
        # and a burst of judge traffic must not turn into a burst of 429s.
        self._llm_slots = asyncio.Semaphore(max(1, self._settings.max_concurrent_llm_calls))

    @property
    def cache_stats(self):
        return self._cache.stats

    def cache_key_for(self, request: OptimizeRequest) -> str:
        """The parser cache key for this request, derived from the prompt it would send."""
        return parser_cache_key(
            system_prompt=build_system_prompt(self._settings),
            user_payload=build_user_payload(request),
            settings=self._settings,
            provider=self._interpreter.provider_name,
            model=self._settings.llm_model,
        )

    def remember(self, request: OptimizeRequest, directives: list[DirectiveInterpretation]) -> None:
        """Store a guardrail-validated interpretation against this request's prompt."""
        self._cache.set(self.cache_key_for(request), list(directives))

    async def run(self, request: OptimizeRequest, deadline: Deadline) -> InterpretationRun:
        """Interpret the notes, repairing once if the first attempt is unusable."""
        run = InterpretationRun(provider=self._interpreter.provider_name)

        cache_key = self.cache_key_for(request)
        cached = self._cache.get(cache_key)
        if cached is not None:
            # Only guardrail-validated interpretations are ever stored, so a hit is as
            # trustworthy as a fresh call — and costs no provider quota.
            run.ok = True
            run.cache_hit = True
            run.directives = list(cached)
            return run

        max_attempts = max(1, self._settings.llm_max_attempts)

        repair_note: str | None = None
        interpreter = self._interpreter

        while run.attempts < max_attempts:
            if not self._budget_allows(deadline, run):
                return run

            run.attempts += 1
            try:
                async with self._llm_slots:
                    outcome = await interpreter.interpret(
                        request,
                        timeout_s=deadline.timeout_for(self._settings.llm_attempt_timeout_seconds),
                        repair_note=repair_note,
                    )
            except InterpreterError as exc:
                decision = self._decide_after_provider_error(exc, deadline, run)
                if decision is None:
                    return run
                run.repairs.append(decision.reason)
                interpreter = decision.interpreter
                repair_note = decision.repair_note
                if decision.wait_seconds > 0:
                    await self._sleep(decision.wait_seconds, deadline)
                continue

            run.model_version = outcome.model_version
            run.provider = outcome.provider
            run.llm_latency_ms += outcome.latency_ms

            report = validate_directives(outcome.raw_items, request, self._settings)
            if report.ok:
                run.ok = True
                run.directives = report.directives
                # Cached only after the guardrails accepted it — never raw model output.
                self._cache.set(cache_key, list(report.directives))
                return run

            run.failure_codes = [str(code) for code in report.codes]
            if run.attempts >= max_attempts:
                run.last_error = "guardrail failure after the final attempt"
                return run

            # Semantic failure: re-read the original notes with the broken rules named.
            run.repairs.append(RepairReason.SEMANTIC)
            repair_note = build_semantic_repair_note(_problem_list(report))

        return run

    async def reinterpret_for_feasibility(
        self,
        request: OptimizeRequest,
        deadline: Deadline,
    ) -> InterpretationRun:
        """One focused reinterpretation after a directive-constrained LP proved infeasible.

        Only reached when the *baseline* scenario was already schedulable, which makes a wrong
        reading of a note the most likely explanation. Constraints are never weakened to
        manufacture feasibility — the model may only revise what it thinks a note said.
        """
        run = InterpretationRun(provider=self._interpreter.provider_name)
        if not self._budget_allows(deadline, run):
            return run

        run.attempts += 1
        run.repairs.append(RepairReason.FEASIBILITY)
        try:
            # Deliberately does not consult the cache: the cached entry is the interpretation
            # that just proved infeasible, so reusing it would defeat the whole retry.
            async with self._llm_slots:
                outcome = await self._interpreter.interpret(
                    request,
                    timeout_s=deadline.timeout_for(self._settings.llm_attempt_timeout_seconds),
                    repair_note=build_feasibility_repair_note(),
                )
        except InterpreterError as exc:
            run.last_error = type(exc).__name__
            return run

        run.model_version = outcome.model_version
        run.provider = outcome.provider
        run.llm_latency_ms += outcome.latency_ms

        report = validate_directives(outcome.raw_items, request, self._settings)
        if report.ok:
            run.ok = True
            run.directives = report.directives
        else:
            run.failure_codes = [str(code) for code in report.codes]
        return run

    # ------------------------------------------------------------------ internals

    def _budget_allows(self, deadline: Deadline, run: InterpretationRun) -> bool:
        if deadline.allows(MINIMUM_ATTEMPT_SECONDS):
            return True
        run.last_error = "request budget exhausted"
        logger.warning("interpretation budget exhausted", extra={"attempts": run.attempts})
        return False

    def _decide_after_provider_error(
        self,
        error: InterpreterError,
        deadline: Deadline,
        run: InterpretationRun,
    ) -> _Decision | None:
        """Pick the response for a provider-level failure, or ``None`` to stop trying."""
        run.last_error = type(error).__name__

        if run.attempts >= max(1, self._settings.llm_max_attempts):
            return None

        if isinstance(error, ProviderRateLimited):
            # Honor the provider's own hint only when waiting it out still leaves time to work.
            wait = error.retry_after or TRANSPORT_BACKOFF_SECONDS
            if deadline.allows(wait + MINIMUM_ATTEMPT_SECONDS):
                return _Decision(RepairReason.RATE_LIMIT, self._interpreter, wait_seconds=wait)
            if self._backup is not None:
                # A different provider is not the one rate limiting us, so the hint does not
                # apply to it — waiting here would spend the budget for nothing.
                run.used_backup = True
                return _Decision(RepairReason.RATE_LIMIT, self._backup)
            return None

        if isinstance(error, ProviderTimeout | ProviderUnavailable):
            if self._backup is not None and not deadline.allows(
                self._settings.llm_attempt_timeout_seconds + MINIMUM_ATTEMPT_SECONDS
            ):
                run.used_backup = True
                return _Decision(RepairReason.TRANSPORT, self._backup)
            return _Decision(
                RepairReason.TRANSPORT, self._interpreter, wait_seconds=TRANSPORT_BACKOFF_SECONDS
            )

        # A refusal, a truncation, or malformed output is not a load problem, so there is
        # nothing to wait for — retry immediately and keep the budget for the work.
        if isinstance(error, ModelRefusal):
            return _Decision(RepairReason.REFUSAL, self._interpreter)

        if isinstance(error, ModelTruncated):
            return _Decision(RepairReason.TRUNCATION, self._interpreter)

        if isinstance(error, MalformedModelOutput):
            # Structural feedback only: name what was wrong with the shape, never the answer.
            return _Decision(
                RepairReason.SCHEMA,
                self._interpreter,
                repair_note=build_schema_repair_note(error.problems),
            )

        return None

    async def _sleep(self, wait_seconds: float, deadline: Deadline) -> None:
        """Pause, never past the point where the retry itself would no longer fit."""
        capped = min(wait_seconds, max(0.0, deadline.remaining() - MINIMUM_ATTEMPT_SECONDS))
        if capped > 0:
            await asyncio.sleep(capped)


def _problem_list(report: GuardrailReport) -> list[str]:
    return list(report.messages)


def build_runner(
    interpreter: LlmDirectiveInterpreter | None,
    settings: Settings | None = None,
) -> InterpretationRunner | None:
    """Build the runner, wiring in a backup provider when one is configured."""
    if interpreter is None:
        return None
    settings = settings or get_settings()

    backup: LlmDirectiveInterpreter | None = None
    if settings.backup_llm_provider:
        from app.llm.providers import build_backup_provider

        backup_provider = build_backup_provider(settings)
        if backup_provider is not None:
            backup = LlmDirectiveInterpreter(backup_provider, settings)

    return InterpretationRunner(interpreter, settings, backup)


__all__ = [
    "MINIMUM_ATTEMPT_SECONDS",
    "TRANSPORT_BACKOFF_SECONDS",
    "InterpretationRun",
    "InterpretationRunner",
    "RepairReason",
    "build_runner",
]
