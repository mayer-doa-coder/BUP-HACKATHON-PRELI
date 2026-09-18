"""Public-case regression runner.

Two modes, both reporting the same table:

* **local** (default) — feeds each case's *ground-truth* directives straight into the
  compiler and solvers, bypassing the LLM. This isolates the deterministic half of the
  pipeline: if a case fails here, the optimizer is wrong, not the interpreter.
* **endpoint** (``--endpoint URL``) — POSTs each case to a running service and evaluates the
  response it actually returns, which exercises the LLM path end to end.

Usage::

    python scripts/run_public_cases.py public_cases/sample_cases.json
    python scripts/run_public_cases.py public_cases/sample_cases.json --extended
    python scripts/run_public_cases.py public_cases/sample_cases.json --endpoint http://localhost:8000

Exits non-zero if any case fails, so it works as a CI gate.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
# Allow `python scripts/run_public_cases.py` from a clean checkout without installing the
# package first — the README quickstart depends on that working.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.schemas.request import OptimizeRequest  # noqa: E402
from app.schemas.response import OptimizeResponse  # noqa: E402
from app.services.optimize_service import OptimizeService  # noqa: E402
from app.validation.interpretation_match import compare_interpretations  # noqa: E402
from app.validation.replay import replay  # noqa: E402

DEFAULT_CASE_FILE = REPO_ROOT / "public_cases" / "sample_cases.json"
EXTENDED_CASE_FILE = REPO_ROOT / "docs" / "GridWise_Extended_HiddenLike_Cases.json"

COST_TOLERANCE = 0.01


@dataclass
class CaseResult:
    case_id: str
    interpretation: str = "SKIP"
    validity: str = "SKIP"
    cost_gap: float | None = None
    latency_ms: float = 0.0
    problems: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.problems

    def row(self) -> str:
        gap = "-" if self.cost_gap is None else f"{self.cost_gap:+.2f}"
        return (
            f"{self.case_id:<12} {self.interpretation:<10} {self.validity:<7} "
            f"{gap:>9} {self.latency_ms:>9.1f}"
        )


def load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload["cases"]


def run_cases(
    cases: list[dict[str, Any]],
    *,
    endpoint: str | None = None,
) -> list[CaseResult]:
    return [run_case(case, endpoint=endpoint) for case in cases]


def run_case(case: dict[str, Any], *, endpoint: str | None = None) -> CaseResult:
    result = CaseResult(case_id=case.get("id", "?"))
    request = OptimizeRequest.model_validate(case["input"])
    expected = case["expected_output"]

    started = time.perf_counter()
    try:
        response = (
            _solve_locally(case, request) if endpoint is None else _call_endpoint(case, endpoint)
        )
    except Exception as exc:  # noqa: BLE001 - a failing case is reported, never raised
        result.latency_ms = (time.perf_counter() - started) * 1000.0
        result.validity = "ERROR"
        result.problems.append(f"{type(exc).__name__}: {exc}")
        return result
    result.latency_ms = (time.perf_counter() - started) * 1000.0

    # --- interpretation (only meaningful when the service produced it itself) ----------
    if endpoint is None:
        result.interpretation = "SKIP"
    else:
        comparison = compare_interpretations(
            response.directive_interpretation, expected["directive_interpretation"]
        )
        result.interpretation = "PASS" if comparison.matches else "FAIL"
        result.problems.extend(comparison.problems)

    # --- validity: independent replay of the returned plan ------------------------------
    report = replay(request, response.directive_interpretation, response)
    result.validity = "PASS" if report.ok else "FAIL"
    result.problems.extend(report.messages)

    # --- cost against the published optimum ---------------------------------------------
    reference_cost = expected.get("total_cost_bdt")
    if reference_cost is not None:
        result.cost_gap = response.total_cost_bdt - reference_cost
        if result.cost_gap > COST_TOLERANCE:
            result.problems.append(
                f"cost {response.total_cost_bdt} exceeds the published optimum {reference_cost}"
            )
        elif result.cost_gap < -COST_TOLERANCE:
            # Cheaper than the published optimum means a constraint was missed somewhere.
            result.problems.append(
                f"cost {response.total_cost_bdt} is below the published optimum {reference_cost}"
            )

    return result


def _solve_locally(case: dict[str, Any], request: OptimizeRequest) -> OptimizeResponse:
    """Ground-truth directives in, schedule out — the LLM is deliberately not involved."""
    directives = list(
        OptimizeResponse.model_validate(case["expected_output"]).directive_interpretation
    )
    service = OptimizeService()
    service.validate(request)
    service.screen_feasibility(request)
    return service.solve_and_build(request, directives)


def _call_endpoint(case: dict[str, Any], endpoint: str) -> OptimizeResponse:
    import httpx

    url = endpoint.rstrip("/") + "/optimize-energy"
    http_response = httpx.post(url, json=case["input"], timeout=35.0)
    http_response.raise_for_status()
    return OptimizeResponse.model_validate(http_response.json())


def report(results: list[CaseResult], *, verbose: bool = True) -> bool:
    if verbose:
        print(f"{'Case':<12} {'Interpret':<10} {'Valid':<7} {'Cost gap':>9} {'Latency ms':>9}")
        print("-" * 52)
        for result in results:
            print(result.row())
            for problem in result.problems:
                print(f"    ! {problem}")

    passed = sum(1 for result in results if result.passed)
    if verbose:
        print("-" * 52)
        print(f"{passed}/{len(results)} cases passed")
        if results:
            latencies = sorted(result.latency_ms for result in results)
            p95 = latencies[min(len(latencies) - 1, int(round(0.95 * (len(latencies) - 1))))]
            print(f"latency: max {latencies[-1]:.1f} ms, p95 {p95:.1f} ms")
    return passed == len(results)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "case_file",
        nargs="?",
        default=str(DEFAULT_CASE_FILE),
        help="path to a case pack JSON file",
    )
    parser.add_argument(
        "--extended",
        action="store_true",
        help="also run the extended hidden-like pack (unofficial synthetic corpus)",
    )
    parser.add_argument(
        "--endpoint",
        default=None,
        help="base URL of a running service; exercises the full LLM path instead of the local optimizer",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable results")
    args = parser.parse_args(argv)

    cases = load_cases(Path(args.case_file))
    if args.extended and EXTENDED_CASE_FILE.exists():
        cases += load_cases(EXTENDED_CASE_FILE)

    results = run_cases(cases, endpoint=args.endpoint)
    ok = report(results, verbose=not args.json)

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "case_id": result.case_id,
                        "interpretation": result.interpretation,
                        "validity": result.validity,
                        "cost_gap": result.cost_gap,
                        "latency_ms": round(result.latency_ms, 2),
                        "problems": result.problems,
                    }
                    for result in results
                ],
                indent=2,
            )
        )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
