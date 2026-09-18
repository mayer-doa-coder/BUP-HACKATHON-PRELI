"""Pre-judging warm canary.

Run this **after deploying and before the judging window opens**. It is the only check that
exercises the exact production model, prompt version and schema version together, and it is
deliberately separate from ``/health``: the readiness probe must never call the provider, or a
transient provider timeout would make the platform restart a perfectly healthy instance.

It answers the five questions from Guide §7.4:

1. are the credentials valid?
2. is there quota?
3. does the structured-output schema compile and parse?
4. does the returned object pass the deterministic guardrails?
5. is latency *warm* — some providers pay a one-off cost compiling a new schema, and that cost
   should be paid here rather than by the first judged request.

It also prints the release record to freeze (Guide §35): exact model version, prompt and schema
versions, optimizer version, solver version and commit SHA.

    python scripts/warm_canary.py
    python scripts/warm_canary.py --rounds 3 --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import __version__  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.guardrails.directive_validator import validate_directives  # noqa: E402
from app.llm.base import InterpreterError  # noqa: E402
from app.llm.interpreter import build_interpreter  # noqa: E402
from app.validation.interpretation_match import compare_interpretations  # noqa: E402
from scripts.semantic_corpus import SemanticCase, load_semantic_cases  # noqa: E402

#: Enough coverage to prove the prompt is doing its job, small enough to be cheap: the
#: percentage-direction contrast, a window, and a distractor that must stay no_op.
CANARY_GROUPS = ("SV-SOLAR-20PCT-REMAINS", "SV-NO-CHARGE", "SV-NOOP-DISTRACTORS")


@dataclass
class CanaryResult:
    case_id: str
    group_id: str
    ok: bool = False
    guardrail_ok: bool = False
    semantics_ok: bool = False
    latency_ms: float = 0.0
    #: What the provider says it actually used, which can differ from the configured alias.
    model_version: str = ""
    problems: list[str] = field(default_factory=list)


def select_canaries() -> list[SemanticCase]:
    """One case per canary group — the cheapest set that still proves the prompt works."""
    chosen: dict[str, SemanticCase] = {}
    for case in load_semantic_cases():
        if case.group_id in CANARY_GROUPS and case.group_id not in chosen:
            chosen[case.group_id] = case
    return list(chosen.values())


async def run_canary(interpreter, cases: list[SemanticCase], rounds: int) -> list[CanaryResult]:
    settings = get_settings()
    results: list[CanaryResult] = []

    for round_index in range(rounds):
        for case in cases:
            result = CanaryResult(
                case_id=f"{case.case_id}#r{round_index}", group_id=case.group_id
            )
            request = case.to_request()
            started = time.perf_counter()
            try:
                outcome = await interpreter.interpret(request)
            except InterpreterError as exc:
                result.latency_ms = (time.perf_counter() - started) * 1000.0
                result.problems.append(f"{type(exc).__name__}: {exc}")
                results.append(result)
                continue
            result.latency_ms = (time.perf_counter() - started) * 1000.0
            result.model_version = outcome.model_version

            report = validate_directives(outcome.raw_items, request, settings)
            result.guardrail_ok = report.ok
            if not report.ok:
                result.problems.extend(report.messages)
                results.append(result)
                continue

            actual = [item.model_dump(mode="json") for item in report.directives]
            comparison = compare_interpretations(actual[:1], [case.expected])
            result.semantics_ok = comparison.matches
            result.problems.extend(comparison.problems)
            result.ok = comparison.matches
            results.append(result)

    return results


def release_record(model_version: str) -> dict[str, str]:
    """Everything to freeze before judging, so a later change is detectable."""
    import scipy

    settings = get_settings()
    return {
        "app_version": __version__,
        "app_commit_sha": settings.app_commit_sha or "(unset — set APP_COMMIT_SHA before release)",
        "llm_provider": settings.llm_provider,
        "llm_model_configured": settings.llm_model,
        "llm_model_reported": model_version,
        "prompt_version": settings.prompt_version,
        "schema_version": settings.schema_version,
        "optimizer_version": settings.optimizer_version,
        "scipy_version": scipy.__version__,
        "python_version": sys.version.split()[0],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--rounds", type=int, default=2, help="passes over the canary set")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--warm-threshold-ms",
        type=float,
        default=None,
        help="fail if the warm p95 exceeds this (default: the soft response budget)",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    interpreter = build_interpreter(settings)
    if interpreter is None:
        print(
            "FAIL: no LLM provider configured. Set LLM_PROVIDER, LLM_MODEL and LLM_API_KEY.",
            file=sys.stderr,
        )
        return 2

    cases = select_canaries()
    if not cases:
        print("FAIL: no canary cases available", file=sys.stderr)
        return 2

    async def _execute() -> list[CanaryResult]:
        # The provider's pooled HTTP client belongs to the loop that created it, so it must be
        # closed inside the same `asyncio.run` — a second one would raise "Event loop is closed".
        try:
            return await run_canary(interpreter, cases, max(1, args.rounds))
        finally:
            await interpreter.aclose()

    results = asyncio.run(_execute())

    # Record what the provider reported using, not just what was configured: a drifting alias
    # is exactly the failure this record exists to make visible.
    reported = next((result.model_version for result in results if result.model_version), "")
    record = release_record(reported or settings.llm_model)

    cold = results[: len(cases)]
    warm = results[len(cases) :] or cold
    warm_latencies = sorted(result.latency_ms for result in warm)
    threshold_ms = args.warm_threshold_ms or settings.soft_response_budget_seconds * 1000

    failures = [result for result in results if not result.ok]
    warm_p95 = warm_latencies[min(len(warm_latencies) - 1, int(0.95 * (len(warm_latencies) - 1)))]

    if args.json:
        print(json.dumps({"results": [asdict(r) for r in results], "release": record}, indent=2))
    else:
        print("=== warm canary ===")
        for result in results:
            status = "ok  " if result.ok else "FAIL"
            print(f"  {status} {result.case_id:<28} {result.latency_ms:7.0f} ms  {result.group_id}")
            for problem in result.problems[:3]:
                print(f"         {problem}")
        if cold and warm is not cold:
            cold_median = statistics.median(r.latency_ms for r in cold)
            warm_median = statistics.median(r.latency_ms for r in warm)
            print(f"\n  cold median {cold_median:.0f} ms -> warm median {warm_median:.0f} ms")
        print(f"  warm p95 {warm_p95:.0f} ms against a {threshold_ms:.0f} ms budget")
        print("\n=== release record (freeze these) ===")
        for key, value in record.items():
            print(f"  {key:<22} {value}")

    if failures:
        print(f"\nFAILED: {len(failures)} canary case(s) did not match.", file=sys.stderr)
        return 1
    if warm_p95 > threshold_ms:
        print(
            f"\nFAILED: warm p95 {warm_p95:.0f} ms exceeds the {threshold_ms:.0f} ms budget.",
            file=sys.stderr,
        )
        return 1

    print("\nCanary passed: credentials, schema, guardrails and semantics all good, latency warm.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
