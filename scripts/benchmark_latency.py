"""External latency benchmark.

Latency is scored in bands, so the number that matters is **p95 measured from outside**, the way
the judge will measure it:

    p95 <= 5 s   -> 3/3 latency points
    5-15 s       -> 2/3
    15-30 s      -> 1/3
    > 30 s       -> 0, and the request counts as a failure

This drives real requests at a running service and reports the distribution against those bands.
Run it against the **deployed** URL, not localhost: the network hop and the platform's cold-start
behaviour are part of what is being measured.

    python scripts/benchmark_latency.py --endpoint https://your-app
    python scripts/benchmark_latency.py --endpoint https://your-app --rounds 3 --concurrency 4
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.config import get_settings  # noqa: E402

DEFAULT_CASES = REPO_ROOT / "public_cases" / "sample_cases.json"

FULL_CREDIT_SECONDS = 5.0
HARD_TIMEOUT_SECONDS = 30.0


@dataclass
class Sample:
    case_id: str
    status: int
    latency_s: float
    ok: bool


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def one_request(endpoint: str, case: dict, timeout: float) -> Sample:
    import httpx

    started = time.perf_counter()
    try:
        response = httpx.post(
            endpoint.rstrip("/") + "/optimize-energy", json=case["input"], timeout=timeout
        )
        elapsed = time.perf_counter() - started
        return Sample(case["id"], response.status_code, elapsed, response.status_code == 200)
    except Exception:  # noqa: BLE001 - a timeout or transport error is a failed sample, not a crash
        return Sample(case["id"], 0, time.perf_counter() - started, False)


def warm_up(endpoint: str, case: dict) -> None:
    """One discarded request, so a cold start is not counted as steady-state latency."""
    one_request(endpoint, case, HARD_TIMEOUT_SECONDS)


def run(endpoint: str, cases: list[dict], rounds: int, concurrency: int) -> list[Sample]:
    work = [case for _ in range(rounds) for case in cases]
    if concurrency <= 1:
        return [one_request(endpoint, case, HARD_TIMEOUT_SECONDS) for case in work]

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        return list(pool.map(lambda case: one_request(endpoint, case, HARD_TIMEOUT_SECONDS), work))


def band_for(p95: float) -> str:
    if p95 <= FULL_CREDIT_SECONDS:
        return "3/3 (full latency credit)"
    if p95 <= 15.0:
        return "2/3"
    if p95 <= HARD_TIMEOUT_SECONDS:
        return "1/3"
    return "0/3 — requests are timing out"


def report(samples: list[Sample], target_s: float) -> bool:
    successes = [sample for sample in samples if sample.ok]
    latencies = [sample.latency_s for sample in successes]
    failures = [sample for sample in samples if not sample.ok]

    print(f"{'requests':<14}{len(samples)}")
    print(f"{'successful':<14}{len(successes)} ({len(successes) / max(1, len(samples)):.1%})")
    if failures:
        print(f"{'failed':<14}{len(failures)}")
        for sample in failures[:5]:
            status = sample.status or "no response"
            print(f"    {sample.case_id}: HTTP {status} after {sample.latency_s:.1f}s")

    if not latencies:
        print("\nNo successful responses: latency cannot be assessed.")
        return False

    p50, p95, p99 = (percentile(latencies, f) for f in (0.5, 0.95, 0.99))
    print()
    print(f"{'p50':<14}{p50:.3f} s")
    print(f"{'p95':<14}{p95:.3f} s   <- the scored figure")
    print(f"{'p99':<14}{p99:.3f} s")
    print(f"{'max':<14}{max(latencies):.3f} s")
    print(f"{'mean':<14}{statistics.mean(latencies):.3f} s")
    print()
    print(f"rubric band   {band_for(p95)}")
    print(f"internal target p95 <= {target_s:.1f} s: {'met' if p95 <= target_s else 'MISSED'}")

    slowest = max(samples, key=lambda sample: sample.latency_s)
    print(f"slowest case  {slowest.case_id} at {slowest.latency_s:.3f} s")

    return bool(failures) is False and p95 <= target_s


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--endpoint", required=True, help="base URL of a running service")
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument(
        "--target",
        type=float,
        default=settings.soft_response_budget_seconds,
        help="internal p95 target in seconds (default: SOFT_RESPONSE_BUDGET_SECONDS)",
    )
    parser.add_argument("--no-warmup", action="store_true")
    args = parser.parse_args(argv)

    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    if not cases:
        print("no cases to run", file=sys.stderr)
        return 2

    print(f"endpoint      {args.endpoint}")
    print(f"plan          {len(cases)} case(s) x {args.rounds} round(s), concurrency {args.concurrency}")
    print()

    if not args.no_warmup:
        warm_up(args.endpoint, cases[0])

    samples = run(args.endpoint, cases, max(1, args.rounds), max(1, args.concurrency))
    ok = report(samples, args.target)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
