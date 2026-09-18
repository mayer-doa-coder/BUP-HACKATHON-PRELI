"""Score the interpreter against the semantic and adversarial corpus.

This is the measurement that predicts the 25 interpretation points. The public cases say whether
the pipeline works; this says whether the *model* understands paraphrases it has not seen.

    python scripts/paraphrase_eval.py                 # needs LLM_PROVIDER / LLM_MODEL / LLM_API_KEY
    python scripts/paraphrase_eval.py --bucket semantic --verbose
    python scripts/paraphrase_eval.py --json > eval.json

Scored per bucket, and the provisional bucket is reported separately on purpose: a miss there
may only mean the organizers chose the other reading of an undefined case, and letting that move
the headline number would hide a real regression.

Record the result against the prompt version, schema version and exact model snapshot. A change
to any of those invalidates the previous score.
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

from app.config import get_settings  # noqa: E402
from app.guardrails.directive_validator import validate_directives  # noqa: E402
from app.llm.base import InterpreterError  # noqa: E402
from app.llm.interpreter import build_interpreter  # noqa: E402
from app.validation.interpretation_match import compare_interpretations  # noqa: E402
from scripts.semantic_corpus import SemanticCase, load_all_cases  # noqa: E402


@dataclass
class CaseResult:
    case_id: str
    group_id: str
    bucket: str
    note: str
    matched: bool = False
    guardrail_ok: bool = False
    latency_ms: float = 0.0
    problems: list[str] = field(default_factory=list)
    actual: dict | None = None


@dataclass
class BucketScore:
    bucket: str
    total: int = 0
    matched: int = 0
    guardrail_ok: int = 0
    type_matched: int = 0
    no_op_total: int = 0
    no_op_matched: int = 0

    @property
    def accuracy(self) -> float:
        return self.matched / self.total if self.total else 0.0

    @property
    def guardrail_rate(self) -> float:
        return self.guardrail_ok / self.total if self.total else 0.0


async def evaluate(cases: list[SemanticCase], interpreter) -> list[CaseResult]:
    results: list[CaseResult] = []
    settings = get_settings()

    for case in cases:
        result = CaseResult(
            case_id=case.case_id, group_id=case.group_id, bucket=case.bucket, note=case.note
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

        report = validate_directives(outcome.raw_items, request, settings)
        result.guardrail_ok = report.ok
        if not report.ok:
            result.problems.extend(report.messages)
            results.append(result)
            continue

        actual = [item.model_dump(mode="json") for item in report.directives]
        result.actual = actual[0] if actual else None
        # Only the first note carries the directive under test; extra notes exist to set up
        # overlap cases and are not graded here.
        comparison = compare_interpretations(actual[:1], [case.expected])
        result.matched = comparison.matches
        result.problems.extend(comparison.problems)
        results.append(result)

    return results


def summarize(results: list[CaseResult], cases: list[SemanticCase]) -> dict[str, BucketScore]:
    expected_by_id = {case.case_id: case.expected for case in cases}
    scores: dict[str, BucketScore] = {}

    for result in results:
        score = scores.setdefault(result.bucket, BucketScore(bucket=result.bucket))
        score.total += 1
        score.guardrail_ok += int(result.guardrail_ok)
        score.matched += int(result.matched)

        expected = expected_by_id.get(result.case_id) or {}
        if result.actual and result.actual.get("directive_type") == expected.get("directive_type"):
            score.type_matched += 1
        if expected.get("directive_type") == "no_op":
            score.no_op_total += 1
            score.no_op_matched += int(result.matched)

    return scores


def report(results: list[CaseResult], scores: dict[str, BucketScore], *, verbose: bool) -> None:
    settings = get_settings()
    print(f"prompt={settings.prompt_version} schema={settings.schema_version} model={settings.llm_model}")
    print()
    print(f"{'bucket':<14}{'cases':>7}{'exact':>9}{'type':>9}{'guardrail':>11}{'no_op':>9}")
    print("-" * 59)
    for bucket in sorted(scores):
        score = scores[bucket]
        no_op = f"{score.no_op_matched}/{score.no_op_total}" if score.no_op_total else "-"
        print(
            f"{bucket:<14}{score.total:>7}{score.accuracy:>8.1%}"
            f"{score.type_matched / score.total if score.total else 0:>9.1%}"
            f"{score.guardrail_rate:>11.1%}{no_op:>9}"
        )

    latencies = sorted(result.latency_ms for result in results if result.latency_ms > 0)
    if latencies:
        print()
        print(
            f"latency  p50 {statistics.median(latencies):.0f} ms   "
            f"p95 {latencies[min(len(latencies) - 1, int(0.95 * (len(latencies) - 1)))]:.0f} ms   "
            f"max {latencies[-1]:.0f} ms"
        )

    misses = [result for result in results if not result.matched]
    if misses:
        print(f"\n{len(misses)} miss(es):")
        for result in misses if verbose else misses[:10]:
            print(f"  [{result.bucket}] {result.case_id}: {result.note[:70]}")
            for problem in result.problems[:3]:
                print(f"      {problem}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--bucket", default=None, help="semantic | adversarial | provisional")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--threshold",
        type=float,
        default=1.0,
        help="minimum exact-match rate for the non-provisional buckets (default 1.0)",
    )
    args = parser.parse_args(argv)

    interpreter = build_interpreter()
    if interpreter is None:
        print(
            "No LLM provider configured. Set LLM_PROVIDER, LLM_MODEL and LLM_API_KEY.",
            file=sys.stderr,
        )
        return 2

    cases = load_all_cases()
    if args.bucket:
        cases = [case for case in cases if case.bucket == args.bucket]

    results = asyncio.run(evaluate(cases, interpreter))
    scores = summarize(results, cases)

    if args.json:
        payload = {
            "results": [asdict(result) for result in results],
            "scores": {bucket: asdict(score) for bucket, score in scores.items()},
        }
        print(json.dumps(payload, indent=2))
    else:
        report(results, scores, verbose=args.verbose)

    # The provisional bucket is excluded from the gate by design.
    graded = [score for bucket, score in scores.items() if bucket != "provisional"]
    if graded and min(score.accuracy for score in graded) < args.threshold:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
