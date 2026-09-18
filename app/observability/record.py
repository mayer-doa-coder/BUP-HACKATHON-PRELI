"""Bridge between the pipeline's results and the trace + metrics.

Each stage already returns rich telemetry — ``InterpretationRun`` knows its attempts, repairs
and cache hit; ``SolveOutcome`` carries both solver statuses and objectives; ``ValidationReport``
carries the replay residuals. This module is the one place that reads those and records them, so
the pipeline stages stay free of instrumentation and there is a single place to audit for leaks.

Nothing recorded here contains note text, prompts, provider payloads or credentials: only
statuses, counts, durations, codes and versions.
"""

from __future__ import annotations

from app.config import Settings, get_settings
from app.guardrails.directive_validator import GuardrailReport
from app.llm.repair import InterpretationRun
from app.observability import metrics
from app.observability.trace import current_trace
from app.optimizer.hybrid_solve import BaselineScreen, SolveOutcome, SolveStatus
from app.validation.replay import ValidationReport


def record_versions(settings: Settings | None = None) -> None:
    """Stamp the trace with the versions that produced this answer."""
    settings = settings or get_settings()
    trace = current_trace()
    if trace is None:
        return
    trace.prompt_version = settings.prompt_version
    trace.schema_version = settings.schema_version
    trace.optimizer_version = settings.optimizer_version
    trace.app_commit_sha = settings.app_commit_sha


def record_response_cache(hit: bool) -> None:
    metrics.cache_hits_total.inc(labels=("response",)) if hit else metrics.cache_misses_total.inc(
        labels=("response",)
    )
    trace = current_trace()
    if trace is not None:
        trace.response_cache_hit = hit


def record_baseline(screen: BaselineScreen) -> None:
    trace = current_trace()
    if trace is not None:
        trace.baseline_lp_status = str(screen.lp.status)
    if not screen.feasible:
        metrics.baseline_lp_failures_total.inc()
    metrics.lp_duration_seconds.observe(screen.lp.duration_ms / 1000.0)


def record_interpretation(run: InterpretationRun) -> None:
    """Record one interpretation attempt sequence."""
    trace = current_trace()
    if trace is not None:
        trace.llm_provider = run.provider
        trace.llm_model_version = run.model_version
        trace.llm_attempts += run.attempts
        trace.llm_latency_ms += run.llm_latency_ms
        trace.llm_repairs.extend(str(reason) for reason in run.repairs)
        trace.llm_used_backup = trace.llm_used_backup or run.used_backup
        trace.parser_cache_hit = trace.parser_cache_hit or run.cache_hit
        trace.interpretation_run = run
        if run.failure_codes:
            trace.guardrail_fail_reasons.extend(run.failure_codes)

    provider = run.provider or "unknown"
    if run.cache_hit:
        metrics.cache_hits_total.inc(labels=("parser",))
    else:
        metrics.cache_misses_total.inc(labels=("parser",))
        if run.attempts:
            metrics.llm_attempts_total.inc(run.attempts, labels=(provider,))
            metrics.llm_duration_seconds.observe(run.llm_latency_ms / 1000.0, labels=(provider,))

    for reason in run.repairs:
        metrics.llm_repairs_total.inc(labels=(str(reason),))
    for code in run.failure_codes:
        metrics.llm_validation_failures_total.inc(labels=(code,))
    if run.used_backup:
        metrics.llm_fallback_total.inc(labels=(provider,))
    if run.last_error and not run.ok:
        metrics.provider_errors_total.inc(labels=(provider, run.last_error))


def record_guardrails(report: GuardrailReport) -> None:
    """Record guardrail outcomes reached outside the retry runner."""
    if report.ok:
        return
    trace = current_trace()
    if trace is not None:
        trace.guardrail_fail_reasons.extend(str(code) for code in report.codes)
    for code in report.codes:
        metrics.llm_validation_failures_total.inc(labels=(str(code),))


def record_solve(outcome: SolveOutcome) -> None:
    trace = current_trace()
    if trace is not None:
        trace.solve_status = str(outcome.status)
        trace.proven_optimal = outcome.proven_optimal
        trace.solve_detail = list(outcome.detail)
        if outcome.lp is not None:
            trace.lp_status = str(outcome.lp.status)
            trace.lp_objective = outcome.lp.cost
            trace.solver_latency_ms += outcome.lp.duration_ms
        if outcome.milp is not None:
            trace.milp_status = str(outcome.milp.status)
            trace.milp_objective = outcome.milp.cost
            trace.milp_gap = outcome.milp.mip_gap
            trace.solver_latency_ms += outcome.milp.duration_ms

    if outcome.lp is not None:
        metrics.lp_duration_seconds.observe(outcome.lp.duration_ms / 1000.0)
    if outcome.milp is not None:
        metrics.milp_duration_seconds.observe(outcome.milp.duration_ms / 1000.0)

    if outcome.status is SolveStatus.SOLVER_FAILURE:
        stage = "milp" if outcome.milp is not None else "lp"
        status = str(outcome.milp.status) if outcome.milp is not None else str(
            outcome.lp.status if outcome.lp is not None else "unknown"
        )
        metrics.solver_failures_total.inc(labels=(stage, status))
    elif outcome.status is SolveStatus.DIRECTIVE_INFEASIBLE:
        metrics.solver_failures_total.inc(labels=("directive", "infeasible"))


def record_replay(report: ValidationReport) -> None:
    trace = current_trace()
    if trace is not None:
        trace.validator_status = "pass" if report.ok else "fail"
        trace.max_balance_error = report.max_balance_error
        trace.max_state_error = report.max_state_error
        trace.final_energy_error = report.final_energy_error
        if not report.ok:
            trace.replay_failure_codes = [str(code) for code in report.codes]

    if not report.ok:
        for code in report.codes:
            metrics.replay_failures_total.inc(labels=(str(code),))


__all__ = [
    "record_baseline",
    "record_guardrails",
    "record_interpretation",
    "record_replay",
    "record_response_cache",
    "record_solve",
    "record_versions",
]
