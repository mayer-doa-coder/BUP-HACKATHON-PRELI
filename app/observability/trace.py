"""Per-request diagnostic trace.

The field list is Guide §23's: enough to reconstruct why a hidden case behaved as it did, with
nothing in it that could leak a note, a prompt, a provider payload, or a credential.

**It lives in a context variable, not on the service.** The service is a process-wide singleton,
so an attribute on it would be shared by every request in flight and two concurrent requests
would overwrite each other's telemetry — which is exactly what the earlier ``_last_run``
attribute did. Context variables are task-local under asyncio, so each request gets its own.

The trace is also what the demo layer (P18) will render. It never reaches the judge response.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - import only for typing
    from app.llm.repair import InterpretationRun

_current_trace: ContextVar[RequestTrace | None] = ContextVar("gridwise_trace", default=None)


@dataclass
class RequestTrace:
    """Sanitized diagnostics for one request."""

    correlation_id: str = ""
    scenario_id: str = ""
    endpoint: str = ""
    http_status: int = 0
    total_latency_ms: float = 0.0

    note_count: int = 0

    # --- interpretation ---------------------------------------------------------
    llm_provider: str = ""
    llm_model_version: str = ""
    llm_attempts: int = 0
    llm_latency_ms: float = 0.0
    llm_repairs: list[str] = field(default_factory=list)
    llm_used_backup: bool = False
    parser_cache_hit: bool = False
    response_cache_hit: bool = False
    guardrail_fail_reasons: list[str] = field(default_factory=list)

    # --- optimization -----------------------------------------------------------
    baseline_lp_status: str = ""
    lp_status: str = ""
    lp_objective: float | None = None
    milp_status: str = ""
    milp_objective: float | None = None
    milp_gap: float | None = None
    solver_latency_ms: float = 0.0
    proven_optimal: bool = False
    solve_status: str = ""
    solve_detail: list[str] = field(default_factory=list)

    # --- validation -------------------------------------------------------------
    validator_status: str = ""
    replay_failure_codes: list[str] = field(default_factory=list)
    max_balance_error: float | None = None
    max_state_error: float | None = None
    final_energy_error: float | None = None

    # --- versions ---------------------------------------------------------------
    prompt_version: str = ""
    schema_version: str = ""
    optimizer_version: str = ""
    app_commit_sha: str = ""

    failure_code: str = ""

    #: The full interpretation result, for callers that need more than the flattened fields.
    #: Excluded from log output — it is a live object, not a diagnostic field.
    interpretation_run: InterpretationRun | None = field(default=None, repr=False, compare=False)

    def as_log_fields(self) -> dict[str, Any]:
        """Flatten for a structured log line, dropping empty values to keep lines readable."""
        payload = asdict(self)
        payload.pop("interpretation_run", None)
        return {
            key: value
            for key, value in payload.items()
            if value not in ("", None, [], False, 0, 0.0) or key in ("http_status", "total_latency_ms")
        }


def start_trace(**fields: Any) -> RequestTrace:
    trace = RequestTrace(**fields)
    _current_trace.set(trace)
    return trace


def current_trace() -> RequestTrace | None:
    """The trace for the request being handled, or ``None`` outside a request."""
    return _current_trace.get()


def clear_trace() -> None:
    _current_trace.set(None)


__all__ = ["RequestTrace", "clear_trace", "current_trace", "start_trace"]
