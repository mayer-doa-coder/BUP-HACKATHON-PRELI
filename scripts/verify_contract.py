"""Audit a *running* service against the judge-visible API contract.

``run_public_cases.py`` answers "are the answers right?". This script answers the different
question the Participant Guide's deployment section asks: **"is this one service, exposing both
endpoints, speaking exactly the documented contract?"**

It is deliberately a black-box client - it imports nothing from ``app``, so a bug shared with the
implementation cannot hide from it, and it can be pointed at the deployed URL from any machine.

    python scripts/verify_contract.py                             # default 127.0.0.1:8000
    python scripts/verify_contract.py --base-url https://<host>   # the deployed service
    python scripts/verify_contract.py --base-url https://<host> --fresh --cases 0

Exit code is 0 only when every REQUIRED check passes. Checks marked ADVISORY report but never
fail the run: they cover behaviour the Problem Statement leaves optional, such as whether a
semantically invalid body is rejected with 422 rather than 400.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
CASE_FILE = REPO_ROOT / "docs" / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"

# Section 10.1 - the complete top-level response. Extra fields are a contract violation, not a
# bonus: debug/solver/confidence fields are explicitly excluded from the judged surface.
TOP_LEVEL_FIELDS = {
    "scenario_id",
    "directive_interpretation",
    "hourly_plan",
    "total_grid_kwh",
    "total_cost_bdt",
    "peak_grid_kwh",
    "plan_summary",
}
INTERPRETATION_FIELDS = {  # Section 10.2
    "note_index",
    "applies",
    "directive_type",
    "structured_adjustment",
    "explanation",
}
HOUR_FIELDS = {  # Section 10.3
    "hour",
    "grid_kwh",
    "solar_used_kwh",
    "battery_action",
    "battery_kwh",
    "battery_energy_after_kwh",
}
DIRECTIVE_TYPES = {  # Section 04 - closed taxonomy
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
}
BATTERY_ACTIONS = {"charge", "discharge", "idle"}

TOL = 0.01  # the judge's stated tolerance

# Strings that must never appear in an error body, however the service fails.
LEAK_MARKERS = ("sk-", "Bearer ", "Traceback", "api_key", "API_KEY", "Authorization")


class Audit:
    """Collects pass/fail results so one bad check does not hide the rest."""

    def __init__(self) -> None:
        self.results: list[dict[str, Any]] = []

    def check(
        self,
        section: str,
        name: str,
        ok: bool,
        detail: str = "",
        advisory: bool = False,
    ) -> bool:
        self.results.append(
            {
                "section": section,
                "name": name,
                "ok": bool(ok),
                "detail": detail,
                "advisory": advisory,
            }
        )
        return bool(ok)

    @property
    def failures(self) -> list[dict[str, Any]]:
        return [r for r in self.results if not r["ok"] and not r["advisory"]]

    @property
    def advisories(self) -> list[dict[str, Any]]:
        return [r for r in self.results if not r["ok"] and r["advisory"]]


def load_cases() -> list[dict[str, Any]]:
    raw = json.loads(CASE_FILE.read_text(encoding="utf-8"))
    cases = raw["cases"] if isinstance(raw, dict) and "cases" in raw else raw
    return [c.get("input", c) for c in cases]


def close(a: float, b: float, tol: float = TOL) -> bool:
    return abs(float(a) - float(b)) <= tol


def _check_no_leak(audit: Audit, section: str, name: str, response: httpx.Response) -> None:
    leaked = [marker for marker in LEAK_MARKERS if marker in response.text]
    audit.check(section, f"no secret/stack-trace leak ({name})", not leaked, f"found {leaked}")


# ------------------------------------------------------------------------ /health


def audit_health(client: httpx.Client, audit: Audit) -> None:
    section = "GET /health"
    started = time.perf_counter()
    try:
        response = client.get("/health")
    except Exception as exc:  # noqa: BLE001 - any transport failure is a contract failure
        audit.check(section, "reachable", False, f"{type(exc).__name__}: {exc}")
        return
    elapsed_ms = (time.perf_counter() - started) * 1000

    audit.check(section, "returns 200", response.status_code == 200, f"got {response.status_code}")
    content_type = response.headers.get("content-type", "<missing>")
    audit.check(section, "content-type is JSON", content_type.startswith("application/json"), content_type)

    try:
        body = response.json()
    except Exception:  # noqa: BLE001
        audit.check(section, "body is JSON", False, response.text[:120])
        return

    audit.check(
        section,
        'body is exactly {"status": "ok"}',
        body == {"status": "ok"},
        f"got {json.dumps(body)[:160]}",
    )
    # Readiness only. A slow /health is what makes a judging harness declare the service down.
    audit.check(
        section,
        "fast enough to be a readiness probe (<1000 ms)",
        elapsed_ms < 1000,
        f"{elapsed_ms:.0f} ms",
    )


# --------------------------------------------------------------- /optimize-energy


def _audit_interpretation(audit: Audit, section: str, interp: list[dict], note_count: int) -> None:
    audit.check(
        section,
        "one interpretation entry per note",
        len(interp) == note_count,
        f"{len(interp)} entries for {note_count} notes",
    )

    bad_fields, bad_index, bad_type, bad_applies = [], [], [], []
    for position, entry in enumerate(interp):
        if set(entry) != INTERPRETATION_FIELDS:
            bad_fields.append(f"#{position}: {sorted(set(entry) ^ INTERPRETATION_FIELDS)}")
        if entry.get("note_index") != position:
            bad_index.append(f"#{position}: note_index={entry.get('note_index')}")

        directive_type = entry.get("directive_type")
        if directive_type not in DIRECTIVE_TYPES:
            bad_type.append(f"#{position}: {directive_type!r}")

        # applies=false is permitted only for no_op with a null adjustment, and no_op must never
        # carry an adjustment. Both directions matter.
        is_noop = directive_type == "no_op"
        applies = entry.get("applies")
        adjustment = entry.get("structured_adjustment")
        if applies is False and not (is_noop and adjustment is None):
            bad_applies.append(f"#{position}: applies=false on {directive_type!r}")
        if applies is True and is_noop:
            bad_applies.append(f"#{position}: no_op with applies=true")
        if is_noop and adjustment is not None:
            bad_applies.append(f"#{position}: no_op has a non-null adjustment")
        if not is_noop and directive_type in DIRECTIVE_TYPES and adjustment is None:
            bad_applies.append(f"#{position}: {directive_type!r} has a null adjustment")

    audit.check(section, "entries have exactly the documented fields", not bad_fields, "; ".join(bad_fields))
    audit.check(section, "note_index is 0..N-1 in order", not bad_index, "; ".join(bad_index))
    audit.check(section, "directive_type is in the closed taxonomy", not bad_type, "; ".join(bad_type))
    audit.check(section, "applies/no_op/adjustment agree", not bad_applies, "; ".join(bad_applies))


def _audit_plan_shape(audit: Audit, section: str, plan: list[dict]) -> bool:
    if not audit.check(section, "hourly_plan has exactly 24 entries", len(plan) == 24, f"got {len(plan)}"):
        return False

    audit.check(
        section,
        "covers hours 0..23 in ascending order",
        [e.get("hour") for e in plan] == list(range(24)),
        f"got {[e.get('hour') for e in plan]}",
    )
    bad = [f"h{e.get('hour')}: {sorted(set(e) ^ HOUR_FIELDS)}" for e in plan if set(e) != HOUR_FIELDS]
    audit.check(section, "plan entries have exactly the documented fields", not bad, "; ".join(bad[:4]))

    bad_action = [
        f"h{e['hour']}: {e.get('battery_action')!r}"
        for e in plan
        if e.get("battery_action") not in BATTERY_ACTIONS
    ]
    audit.check(section, "battery_action is charge|discharge|idle", not bad_action, "; ".join(bad_action[:4]))

    bad_idle = [
        f"h{e['hour']}"
        for e in plan
        if e.get("battery_action") == "idle" and not close(e.get("battery_kwh", 0), 0)
    ]
    audit.check(section, "battery_kwh is 0 when idle", not bad_idle, ", ".join(bad_idle[:6]))

    bad_sign = [
        f"h{e['hour']}"
        for e in plan
        if float(e.get("grid_kwh", 0)) < -TOL
        or float(e.get("solar_used_kwh", 0)) < -TOL
        or float(e.get("battery_kwh", 0)) < -TOL
    ]
    audit.check(section, "magnitudes are non-negative", not bad_sign, ", ".join(bad_sign[:6]))
    return True


def _audit_physics(audit: Audit, section: str, body: dict, payload: dict) -> None:
    plan = body["hourly_plan"]
    hours = {h["hour"]: h for h in payload["hours"]}
    battery = payload["battery"]

    # Curtailment is allowed and a solar_reduction factor is at most 1, so used solar can never
    # exceed the solar the request declared for that hour.
    bad_solar = [
        f"h{e['hour']}: {e['solar_used_kwh']} > {hours[e['hour']]['solar_kwh']}"
        for e in plan
        if float(e["solar_used_kwh"]) > float(hours[e["hour"]]["solar_kwh"]) + TOL
    ]
    audit.check(
        section, "solar_used_kwh never exceeds available solar", not bad_solar, "; ".join(bad_solar[:4])
    )

    bad_balance = []
    for entry in plan:
        hour = entry["hour"]
        charge = float(entry["battery_kwh"]) if entry["battery_action"] == "charge" else 0.0
        discharge = float(entry["battery_kwh"]) if entry["battery_action"] == "discharge" else 0.0
        lhs = float(entry["grid_kwh"]) + float(entry["solar_used_kwh"]) + discharge
        rhs = float(hours[hour]["demand_kwh"]) + charge
        if not close(lhs, rhs):
            bad_balance.append(f"h{hour}: {lhs:.4f} != {rhs:.4f}")
    audit.check(section, "hourly energy balance holds", not bad_balance, "; ".join(bad_balance[:4]))

    bad_continuity = []
    level = float(battery["initial_energy_kwh"])
    for entry in plan:
        charge = float(entry["battery_kwh"]) if entry["battery_action"] == "charge" else 0.0
        discharge = float(entry["battery_kwh"]) if entry["battery_action"] == "discharge" else 0.0
        level = level + charge - discharge
        if not close(level, float(entry["battery_energy_after_kwh"])):
            bad_continuity.append(f"h{entry['hour']}: {level:.4f} != {entry['battery_energy_after_kwh']}")
    audit.check(
        section, "battery level follows from the actions", not bad_continuity, "; ".join(bad_continuity[:4])
    )

    audit.check(
        section,
        "battery returns to its initial level at hour 23",
        close(float(plan[-1]["battery_energy_after_kwh"]), float(battery["initial_energy_kwh"])),
        f"{plan[-1]['battery_energy_after_kwh']} vs {battery['initial_energy_kwh']}",
    )

    bad_bounds = [
        f"h{e['hour']}: {e['battery_energy_after_kwh']}"
        for e in plan
        if float(e["battery_energy_after_kwh"]) < float(battery["minimum_energy_kwh"]) - TOL
        or float(e["battery_energy_after_kwh"]) > float(battery["capacity_kwh"]) + TOL
    ]
    audit.check(
        section, "battery stays within [minimum, capacity]", not bad_bounds, "; ".join(bad_bounds[:4])
    )

    max_charge = float(battery["max_charge_kwh_per_hour"])
    max_discharge = float(battery["max_discharge_kwh_per_hour"])
    bad_rate = [
        f"h{e['hour']}: {e['battery_kwh']}"
        for e in plan
        if (e["battery_action"] == "charge" and float(e["battery_kwh"]) > max_charge + TOL)
        or (e["battery_action"] == "discharge" and float(e["battery_kwh"]) > max_discharge + TOL)
    ]
    audit.check(section, "charge/discharge respect the rate limits", not bad_rate, "; ".join(bad_rate[:4]))

    # Totals must be recomputable from the returned plan - exactly what the judge does.
    grid_total = sum(float(e["grid_kwh"]) for e in plan)
    cost_total = sum(float(e["grid_kwh"]) * float(hours[e["hour"]]["tariff_bdt_per_kwh"]) for e in plan)
    peak = max(float(e["grid_kwh"]) for e in plan)
    audit.check(
        section,
        "total_grid_kwh matches the plan",
        close(float(body["total_grid_kwh"]), grid_total),
        f"{body['total_grid_kwh']} vs {grid_total:.4f}",
    )
    audit.check(
        section,
        "total_cost_bdt matches the plan",
        close(float(body["total_cost_bdt"]), cost_total),
        f"{body['total_cost_bdt']} vs {cost_total:.4f}",
    )
    audit.check(
        section,
        "peak_grid_kwh matches the plan",
        close(float(body["peak_grid_kwh"]), peak),
        f"{body['peak_grid_kwh']} vs {peak:.4f}",
    )


def audit_optimize_case(
    client: httpx.Client,
    audit: Audit,
    payload: dict[str, Any],
    latencies: list[float],
) -> None:
    section = f"POST /optimize-energy [{payload.get('scenario_id', '<none>')}]"

    started = time.perf_counter()
    try:
        response = client.post("/optimize-energy", json=payload)
    except Exception as exc:  # noqa: BLE001
        audit.check(section, "reachable", False, f"{type(exc).__name__}: {exc}")
        return
    latencies.append(time.perf_counter() - started)

    ok = audit.check(
        section,
        "returns 200",
        response.status_code == 200,
        f"got {response.status_code}: {response.text[:160]}",
    )
    if not ok:
        return

    try:
        body = response.json()
    except Exception:  # noqa: BLE001
        audit.check(section, "body is JSON", False, response.text[:160])
        return

    keys = set(body)
    missing, extra = TOP_LEVEL_FIELDS - keys, keys - TOP_LEVEL_FIELDS
    audit.check(section, "no missing top-level fields", not missing, f"missing {sorted(missing)}")
    audit.check(section, "no undocumented top-level fields", not extra, f"extra {sorted(extra)}")
    if missing:
        return

    audit.check(
        section,
        "scenario_id echoes the request",
        body["scenario_id"] == payload["scenario_id"],
        f"got {body['scenario_id']!r}",
    )
    summary = body["plan_summary"]
    audit.check(
        section,
        "plan_summary is a non-empty string",
        isinstance(summary, str) and summary.strip() != "",
        f"got {summary!r}"[:80],
    )

    _audit_interpretation(audit, section, body["directive_interpretation"], len(payload["operator_notes"]))
    if _audit_plan_shape(audit, section, body["hourly_plan"]):
        _audit_physics(audit, section, body, payload)


# -------------------------------------------------------------- error contract


def audit_errors(client: httpx.Client, audit: Audit, valid: dict[str, Any]) -> None:
    section = "Error contract"

    def mutate(**changes: Any) -> dict[str, Any]:
        body = json.loads(json.dumps(valid))
        body.update(changes)
        return body

    hours = valid["hours"]
    battery = valid["battery"]
    capacity = float(battery["capacity_kwh"])

    # Structurally invalid bodies must be 400 - FastAPI's default 422 for these is wrong here.
    required: list[tuple[str, Any]] = [
        ("malformed JSON -> 400", "{not json"),
        ("missing required field -> 400", {k: v for k, v in valid.items() if k != "battery"}),
        ("wrong type for hours -> 400", mutate(hours="twenty-four")),
        ("23 hours -> 400", mutate(hours=hours[:23])),
        ("duplicate hour -> 400", mutate(hours=hours[:23] + [hours[0]])),
        ("hour out of range -> 400", mutate(hours=hours[:23] + [{**hours[23], "hour": 24}])),
        ("zero operator notes -> 400", mutate(operator_notes=[])),
        ("four operator notes -> 400", mutate(operator_notes=["a", "b", "c", "d"])),
        ("empty note string -> 400", mutate(operator_notes=["   "])),
    ]
    # Section 6.1 marks 422 "optional", so answering 400 here is still conformant.
    advisory: list[tuple[str, Any]] = [
        (
            "initial energy above capacity -> 422 (400 ok)",
            mutate(battery={**battery, "initial_energy_kwh": capacity * 10}),
        ),
        (
            "minimum reserve above capacity -> 422 (400 ok)",
            mutate(battery={**battery, "minimum_energy_kwh": capacity * 10}),
        ),
    ]

    for name, body in required:
        if isinstance(body, str):
            response = client.post(
                "/optimize-energy", content=body, headers={"Content-Type": "application/json"}
            )
        else:
            response = client.post("/optimize-energy", json=body)
        audit.check(section, name, response.status_code == 400, f"got {response.status_code}")
        _check_no_leak(audit, section, name, response)

    for name, body in advisory:
        response = client.post("/optimize-energy", json=body)
        audit.check(
            section, name, response.status_code in {400, 422}, f"got {response.status_code}", advisory=True
        )
        _check_no_leak(audit, section, name, response)

    response = client.get("/optimize-energy")
    audit.check(
        section,
        "GET on /optimize-energy is a controlled 404/405",
        response.status_code in {404, 405},
        f"got {response.status_code}",
    )
    _check_no_leak(audit, section, "GET on /optimize-energy", response)


# ------------------------------------------------------------------------ main


def _report(audit: Audit, latencies: list[float], fresh: bool) -> None:
    current = None
    for result in audit.results:
        if result["section"] != current:
            current = result["section"]
            print(f"\n{current}")
        mark = "PASS" if result["ok"] else ("WARN" if result["advisory"] else "FAIL")
        detail = f"  ({result['detail']})" if result["detail"] and not result["ok"] else ""
        print(f"  [{mark}] {result['name']}{detail}")

    if latencies:
        ordered = sorted(latencies)
        index = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
        print(
            f"\nLatency over {len(ordered)} optimize call(s): "
            f"p50 {statistics.median(ordered):.2f} s, p95 {ordered[index]:.2f} s, "
            f"max {ordered[-1]:.2f} s"
        )
        print("  rubric: p95 <= 5 s for full latency credit; hard limit 30 s")
        # Anything this fast did not call the model, so it says nothing about judged latency.
        if ordered[-1] < 0.20:
            if fresh:
                # --fresh nonces scenario_id, which the response cache keys on, but the
                # interpreter cache keys on the notes - so a known note set still skips the
                # model call entirely.
                print("  NOTE: no model call happened - the interpreter cache served these notes.")
                print("        This number is not judged latency; use benchmark_latency.py.")
            else:
                print("  NOTE: these are response-cache hits, not real solves. Re-run with --fresh,")
                print("        and use benchmark_latency.py for the authoritative p95.")
        elif not fresh:
            print("  NOTE: repeats may be served from the response cache; --fresh avoids that.")
        else:
            print("  NOTE: benchmark_latency.py remains the authoritative p95 measurement.")

    passed = sum(1 for r in audit.results if r["ok"])
    print(
        f"\n{passed}/{len(audit.results)} checks passed, "
        f"{len(audit.failures)} required failure(s), {len(audit.advisories)} advisory warning(s)."
    )
    if audit.failures:
        print("\nRequired failures:")
        for result in audit.failures:
            print(f"  - [{result['section']}] {result['name']}: {result['detail']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a running service against the judge contract.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="base URL of the service")
    parser.add_argument("--cases", type=int, default=3, help="public cases to exercise (0 = all)")
    parser.add_argument("--fresh", action="store_true", help="nonce the scenario_id to skip the cache")
    parser.add_argument("--timeout", type=float, default=35.0, help="per-request timeout in seconds")
    parser.add_argument("--json", action="store_true", help="emit machine-readable results")
    args = parser.parse_args()

    payloads = load_cases()
    if args.cases:
        payloads = payloads[: args.cases]
    if args.fresh:
        nonce = uuid.uuid4().hex[:8]
        payloads = [{**p, "scenario_id": f"{p['scenario_id']}-{nonce}"} for p in payloads]

    audit = Audit()
    latencies: list[float] = []
    base = args.base_url.rstrip("/")

    with httpx.Client(base_url=base, timeout=args.timeout, follow_redirects=True) as client:
        audit_health(client, audit)
        for payload in payloads:
            audit_optimize_case(client, audit, payload, latencies)
        audit_errors(client, audit, payloads[0])

        # "One service, not separate deployments": both endpoints answered on this one origin.
        health_ok = any(
            r["section"] == "GET /health" and r["name"] == "returns 200" and r["ok"]
            for r in audit.results
        )
        optimize_ok = any(
            r["section"].startswith("POST /optimize-energy") and r["name"] == "returns 200" and r["ok"]
            for r in audit.results
        )
        audit.check("Deployment", f"both endpoints on one origin ({base})", health_ok and optimize_ok)

    if args.json:
        print(json.dumps({"base_url": base, "results": audit.results, "latencies_s": latencies}, indent=2))
    else:
        _report(audit, latencies, args.fresh)

    return 1 if audit.failures else 0


if __name__ == "__main__":
    sys.exit(main())
