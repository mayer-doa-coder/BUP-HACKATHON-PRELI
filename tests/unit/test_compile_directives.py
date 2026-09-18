"""Directive compiler tests.

The headline test is :func:`test_compiler_agrees_with_the_independent_replay_envelope`. The
compiler and ``replay.derive_envelope`` are two separately written implementations of the same
composition rules; agreement across every published reference case is meaningful evidence that
both are right, and any future divergence is a real defect rather than noise.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from app.api.errors import DirectiveCompilationFailure
from app.config import Settings
from app.optimizer.compile_directives import compile_directives
from app.policies.spec_gaps import OVERLAPPING_SOLAR_FACTOR_FLAG
from app.schemas.directive import (
    MaxGridWindowDirective,
    MinimumBatteryReserveDirective,
    NoChargeWindowDirective,
    NoDischargeWindowDirective,
    NoOpDirective,
    SolarReductionDirective,
)
from app.schemas.request import OptimizeRequest
from app.schemas.response import OptimizeResponse
from app.validation.replay import derive_envelope


def _request(case) -> OptimizeRequest:
    return OptimizeRequest.model_validate(case["input"])


# ------------------------------------------------- cross-check against the replay envelope


def test_compiler_agrees_with_the_independent_replay_envelope(public_cases, extended_cases):
    """Two independent implementations, 44 reference cases, every directive type."""
    mismatches = []
    for case in [*public_cases, *extended_cases]:
        request = _request(case)
        directives = OptimizeResponse.model_validate(case["expected_output"]).directive_interpretation

        compiled = compile_directives(request, directives)
        envelope = derive_envelope(request, directives)

        checks = (
            ("effective_solar", compiled.effective_solar.tolist(), list(envelope.effective_solar)),
            ("min_energy", compiled.min_energy.tolist(), list(envelope.min_energy)),
            ("charge_allowed", compiled.charge_allowed.tolist(), list(envelope.charge_allowed)),
            ("discharge_allowed", compiled.discharge_allowed.tolist(), list(envelope.discharge_allowed)),
            ("grid_upper", compiled.grid_upper.tolist(), list(envelope.grid_upper)),
        )
        for field, from_compiler, from_replay in checks:
            if from_compiler != pytest.approx(from_replay, nan_ok=False):
                mismatches.append(f"{case['id']} {field}: {from_compiler} != {from_replay}")

    assert not mismatches, "\n".join(mismatches)


# ------------------------------------------------------------------- baseline behaviour


def test_no_directives_leaves_the_scenario_untouched(public_cases):
    request = _request(public_cases[0])
    compiled = compile_directives(request, [])

    assert compiled.effective_solar.tolist() == [entry.solar_kwh for entry in request.canonical_hours()]
    assert (compiled.min_energy == request.battery.minimum_energy_kwh).all()
    assert compiled.charge_allowed.all()
    assert compiled.discharge_allowed.all()
    assert np.isinf(compiled.grid_upper).all()
    assert compiled.ambiguity_flags == ()
    assert compiled.trace == ()
    assert compiled.has_grid_cap is False


def test_no_op_is_not_a_constraint(public_cases):
    request = _request(public_cases[0])
    baseline = compile_directives(request, [])
    with_no_op = compile_directives(request, [NoOpDirective(note_index=0)])

    assert with_no_op.effective_solar.tolist() == baseline.effective_solar.tolist()
    assert with_no_op.trace == ()


# --------------------------------------------------------------------- composition rules


def test_reserves_compose_with_pointwise_max(public_cases):
    request = _request(public_cases[0])
    base = request.battery.minimum_energy_kwh
    compiled = compile_directives(
        request,
        [
            MinimumBatteryReserveDirective(
                note_index=0, structured_adjustment={"hours": [18, 19], "minimum_energy_kwh": base + 50}
            ),
            MinimumBatteryReserveDirective(
                note_index=1, structured_adjustment={"hours": [19, 20], "minimum_energy_kwh": base + 20}
            ),
        ],
    )

    assert compiled.min_energy[18] == pytest.approx(base + 50)
    assert compiled.min_energy[19] == pytest.approx(base + 50), "the stricter floor must win"
    assert compiled.min_energy[20] == pytest.approx(base + 20)
    assert compiled.min_energy[0] == pytest.approx(base)


def test_grid_caps_compose_with_pointwise_min(public_cases):
    request = _request(public_cases[0])
    compiled = compile_directives(
        request,
        [
            MaxGridWindowDirective(note_index=0, structured_adjustment={"hours": [19, 20], "max_grid_kwh": 180.0}),
            MaxGridWindowDirective(note_index=1, structured_adjustment={"hours": [20, 21], "max_grid_kwh": 120.0}),
        ],
    )

    assert compiled.grid_upper[19] == pytest.approx(180.0)
    assert compiled.grid_upper[20] == pytest.approx(120.0), "the tighter ceiling must win"
    assert compiled.grid_upper[21] == pytest.approx(120.0)
    assert math.isinf(compiled.grid_upper[0])


def test_a_reserve_below_the_base_minimum_never_weakens_it(public_cases):
    """A directive may only raise the floor; it can never lower the battery's own minimum."""
    request = _request(public_cases[0])
    base = request.battery.minimum_energy_kwh
    compiled = compile_directives(
        request,
        [
            MinimumBatteryReserveDirective(
                note_index=0, structured_adjustment={"hours": [5, 6], "minimum_energy_kwh": max(base - 10, 0)}
            )
        ],
    )

    assert compiled.min_energy[5] == pytest.approx(base)
    assert compiled.trace == ()


def test_charge_and_discharge_bans_on_one_hour_force_idle(public_cases):
    request = _request(public_cases[0])
    compiled = compile_directives(
        request,
        [
            NoChargeWindowDirective(note_index=0, structured_adjustment={"hours": [14, 15]}),
            NoDischargeWindowDirective(note_index=1, structured_adjustment={"hours": [15, 16]}),
        ],
    )

    assert compiled.charge_allowed[14] is np.False_
    assert compiled.discharge_allowed[16] is np.False_
    assert compiled.forced_idle_hours == (15,)


def test_solar_factor_scales_the_forecast(public_cases):
    request = _request(public_cases[0])
    solar = [entry.solar_kwh for entry in request.canonical_hours()]
    compiled = compile_directives(
        request,
        [SolarReductionDirective(note_index=0, structured_adjustment={"hours": [10, 11], "factor": 0.25})],
    )

    assert compiled.effective_solar[10] == pytest.approx(solar[10] * 0.25)
    assert compiled.effective_solar[11] == pytest.approx(solar[11] * 0.25)
    assert compiled.effective_solar[12] == pytest.approx(solar[12])
    assert compiled.solar_factor[10] == pytest.approx(0.25)
    assert compiled.solar_factor[12] == pytest.approx(1.0)


# ------------------------------------------------------------------ zero-valued directives


def test_zero_factor_and_zero_cap_survive(public_cases):
    """``factor=0.0`` and ``max_grid_kwh=0.0`` are real constraints, not absent ones."""
    request = _request(public_cases[0])
    compiled = compile_directives(
        request,
        [
            SolarReductionDirective(note_index=0, structured_adjustment={"hours": [10, 11], "factor": 0.0}),
            MaxGridWindowDirective(note_index=1, structured_adjustment={"hours": [14], "max_grid_kwh": 0.0}),
        ],
    )

    assert compiled.effective_solar[10] == 0.0
    assert compiled.effective_solar[11] == 0.0
    assert compiled.grid_upper[14] == 0.0
    assert compiled.has_grid_cap is True
    # A zero cap must be recorded as a real change, not skipped as falsy.
    assert any(item.field == "grid_upper" and item.hour == 14 for item in compiled.trace)


# ----------------------------------------------------- overlapping solar factors (spec gap)


def test_differing_solar_factors_take_the_minimum_and_raise_a_flag(public_cases):
    request = _request(public_cases[0])
    solar = [entry.solar_kwh for entry in request.canonical_hours()]
    compiled = compile_directives(
        request,
        [
            SolarReductionDirective(note_index=0, structured_adjustment={"hours": [11, 12], "factor": 0.8}),
            SolarReductionDirective(note_index=1, structured_adjustment={"hours": [12, 13], "factor": 0.5}),
        ],
    )

    assert compiled.effective_solar[11] == pytest.approx(solar[11] * 0.8)
    assert compiled.effective_solar[12] == pytest.approx(solar[12] * 0.5), "most restrictive wins"
    assert compiled.effective_solar[13] == pytest.approx(solar[13] * 0.5)
    assert OVERLAPPING_SOLAR_FACTOR_FLAG in compiled.ambiguity_flags


def test_identical_overlapping_factors_are_not_ambiguous(public_cases):
    request = _request(public_cases[0])
    compiled = compile_directives(
        request,
        [
            SolarReductionDirective(note_index=0, structured_adjustment={"hours": [11, 12], "factor": 0.5}),
            SolarReductionDirective(note_index=1, structured_adjustment={"hours": [12, 13], "factor": 0.5}),
        ],
    )

    assert compiled.ambiguity_flags == ()


def test_overlap_policy_is_configurable(public_cases, monkeypatch):
    """The provisional policy is a config value, so a clarification is a one-line change."""
    request = _request(public_cases[0])
    solar = [entry.solar_kwh for entry in request.canonical_hours()]
    directives = [
        SolarReductionDirective(note_index=0, structured_adjustment={"hours": [12], "factor": 0.8}),
        SolarReductionDirective(note_index=1, structured_adjustment={"hours": [12], "factor": 0.5}),
    ]

    monkeypatch.setenv("SOLAR_OVERLAP_POLICY", "multiply")
    multiplied = compile_directives(request, directives, Settings(_env_file=None))
    assert multiplied.effective_solar[12] == pytest.approx(solar[12] * 0.8 * 0.5)

    monkeypatch.setenv("SOLAR_OVERLAP_POLICY", "last_wins")
    last_wins = compile_directives(request, directives, Settings(_env_file=None))
    assert last_wins.effective_solar[12] == pytest.approx(solar[12] * 0.5)


def test_compilation_is_independent_of_directive_order(public_cases):
    """Directives are sorted by note_index, so a shuffled list compiles identically."""
    request = _request(public_cases[0])
    directives = [
        SolarReductionDirective(note_index=0, structured_adjustment={"hours": [12], "factor": 0.8}),
        MinimumBatteryReserveDirective(
            note_index=1, structured_adjustment={"hours": [18], "minimum_energy_kwh": 90.0}
        ),
        MaxGridWindowDirective(note_index=2, structured_adjustment={"hours": [19], "max_grid_kwh": 150.0}),
    ]

    forward = compile_directives(request, directives)
    reversed_order = compile_directives(request, list(reversed(directives)))

    assert forward.effective_solar.tolist() == reversed_order.effective_solar.tolist()
    assert forward.min_energy.tolist() == reversed_order.min_energy.tolist()
    assert forward.grid_upper.tolist() == reversed_order.grid_upper.tolist()
    assert [item.source_note_index for item in forward.trace] == [
        item.source_note_index for item in reversed_order.trace
    ]


# ------------------------------------------------------------------------- provenance


def test_trace_records_the_note_behind_each_bound(public_cases):
    request = _request(public_cases[0])
    compiled = compile_directives(
        request,
        [
            MinimumBatteryReserveDirective(
                note_index=0, structured_adjustment={"hours": [18], "minimum_energy_kwh": 90.0}
            ),
            NoChargeWindowDirective(note_index=1, structured_adjustment={"hours": [2]}),
        ],
    )

    reserve_entry = next(item for item in compiled.trace if item.field == "min_energy")
    assert reserve_entry.hour == 18
    assert reserve_entry.source_note_index == 0
    assert reserve_entry.original_value == pytest.approx(request.battery.minimum_energy_kwh)
    assert reserve_entry.effective_value == pytest.approx(90.0)

    ban_entry = next(item for item in compiled.trace if item.field == "charge_allowed")
    assert (ban_entry.hour, ban_entry.source_note_index, ban_entry.effective_value) == (2, 1, False)


# ------------------------------------------------------------------- invariant failures


def test_reserve_above_capacity_fails_closed(public_cases):
    """A guardrail should have caught this first; the compiler still refuses to clip it."""
    request = _request(public_cases[0])
    over_capacity = request.battery.capacity_kwh + 100

    with pytest.raises(DirectiveCompilationFailure) as excinfo:
        compile_directives(
            request,
            [
                MinimumBatteryReserveDirective(
                    note_index=0,
                    structured_adjustment={"hours": [18], "minimum_energy_kwh": over_capacity},
                )
            ],
        )

    assert any("capacity" in detail for detail in excinfo.value.details)
    assert excinfo.value.http_status == 500


# ------------------------------------------------------------------------ independence


def test_compiler_does_not_import_the_replay_validator():
    """D-09 in the other direction: the two implementations must stay separate."""
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path("app/optimizer/compile_directives.py").read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    assert not [name for name in imported if name.startswith("app.validation")]


def test_compiler_and_replay_agree_under_an_order_sensitive_policy(public_cases, monkeypatch):
    """Regression for R1-1.

    Under ``last_wins`` the two implementations must agree on what "last" means. Before the fix
    the compiler sorted by ``note_index`` while the replay envelope trusted list order, so the
    same directives supplied in a different order resolved to different effective solar — which
    would have let a valid plan be rejected by its own validator.
    """
    monkeypatch.setenv("SOLAR_OVERLAP_POLICY", "last_wins")
    settings = Settings(_env_file=None)

    request = _request(public_cases[0])
    first = SolarReductionDirective(note_index=0, structured_adjustment={"hours": [10], "factor": 0.8})
    second = SolarReductionDirective(note_index=1, structured_adjustment={"hours": [10], "factor": 0.3})

    for ordering in ([first, second], [second, first]):
        compiled = compile_directives(request, ordering, settings)
        envelope = derive_envelope(request, ordering, settings)

        assert compiled.effective_solar.tolist() == pytest.approx(list(envelope.effective_solar))
        # "Last" means the highest note_index in both, so list order cannot change the answer.
        assert compiled.solar_factor[10] == pytest.approx(0.3)
