"""Turn validated directives into the per-hour numbers the optimizer consumes.

This is the boundary where language stops and mathematics begins. Everything upstream is
about *what the operator meant*; everything downstream is arrays of bounds. Composition lives
here rather than in the LLM: the model interprets each note on its own and never merges two
notes, because merging is a deterministic operation with exact rules (Problem Statement §5.3).

The compiled output is deliberately a second, independent implementation of the same rules
that ``app.validation.replay.derive_envelope`` implements (D-09). Neither calls the other. A
cross-check test asserts they agree on every published reference case; if they ever diverge,
that is a real bug surfacing rather than duplication to tidy away.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from app.api.errors import DirectiveCompilationFailure
from app.config import Settings, get_settings
from app.policies.spec_gaps import OVERLAPPING_SOLAR_FACTOR_FLAG, compose_solar_factors
from app.schemas.directive import DirectiveInterpretation
from app.schemas.request import HOURS_IN_DAY, OptimizeRequest


@dataclass(frozen=True)
class ConstraintTrace:
    """Why one hour ended up with the bound it has.

    Internal only — it feeds debugging, the demo pipeline view, and failure explanations, and
    never appears in the canonical response.
    """

    hour: int
    field: str
    source_note_index: int
    directive_type: str
    original_value: float | bool
    effective_value: float | bool


@dataclass(frozen=True)
class CompiledConstraints:
    """Per-hour parameters for the LP and MILP stages. All arrays have length 24."""

    effective_solar: np.ndarray
    min_energy: np.ndarray
    charge_allowed: np.ndarray
    discharge_allowed: np.ndarray
    grid_upper: np.ndarray
    # Kept for the demo layer and diagnostics: the untouched forecast and the resolved factor.
    original_solar: np.ndarray
    solar_factor: np.ndarray
    ambiguity_flags: tuple[str, ...] = ()
    trace: tuple[ConstraintTrace, ...] = ()

    @property
    def has_grid_cap(self) -> bool:
        return bool(np.isfinite(self.grid_upper).any())

    @property
    def forced_idle_hours(self) -> tuple[int, ...]:
        """Hours where charging and discharging are both banned, so the battery must idle."""
        both_banned = ~self.charge_allowed & ~self.discharge_allowed
        return tuple(int(hour) for hour in np.flatnonzero(both_banned))


def compile_directives(
    request: OptimizeRequest,
    directives: Sequence[DirectiveInterpretation],
    settings: Settings | None = None,
) -> CompiledConstraints:
    """Compile guardrail-validated directives into per-hour bounds.

    Composition rules (Problem Statement §5.3):

    * ``minimum_battery_reserve`` overlaps take the pointwise **max** — the strictest floor wins.
    * ``max_grid_window`` overlaps take the pointwise **min** — the tightest ceiling wins.
    * ``no_charge_window`` / ``no_discharge_window`` are hard booleans; both on one hour forces idle.
    * ``solar_reduction`` scales the forecast. Two *differing* factors on one hour is a
      specification gap, resolved by the configured provisional policy and flagged.

    Directives are processed in ``note_index`` order so that compilation is deterministic even
    under an order-sensitive overlap policy.
    """
    settings = settings or get_settings()
    hours = request.canonical_hours()
    battery = request.battery

    original_solar = np.array([entry.solar_kwh for entry in hours], dtype=float)
    min_energy = np.full(HOURS_IN_DAY, float(battery.minimum_energy_kwh), dtype=float)
    charge_allowed = np.ones(HOURS_IN_DAY, dtype=bool)
    discharge_allowed = np.ones(HOURS_IN_DAY, dtype=bool)
    grid_upper = np.full(HOURS_IN_DAY, np.inf, dtype=float)

    # None marks "no solar directive touched this hour", which is not the same as a factor of
    # 1.0 arriving from a note. Keeping them distinct is what makes overlap detection possible.
    resolved_factor: list[float | None] = [None] * HOURS_IN_DAY

    trace: list[ConstraintTrace] = []
    ambiguity_flags: set[str] = set()

    for directive in sorted(directives, key=lambda item: item.note_index):
        if not directive.applies or directive.structured_adjustment is None:
            continue

        adjustment = directive.structured_adjustment
        note_index = directive.note_index
        kind = directive.directive_type

        for hour in adjustment.hours:
            if kind == "solar_reduction":
                previous = resolved_factor[hour]
                combined, ambiguous = compose_solar_factors(previous, adjustment.factor, settings)
                if ambiguous:
                    ambiguity_flags.add(OVERLAPPING_SOLAR_FACTOR_FLAG)
                if previous != combined:
                    resolved_factor[hour] = combined
                    trace.append(
                        ConstraintTrace(
                            hour=hour,
                            field="solar_factor",
                            source_note_index=note_index,
                            directive_type=kind,
                            original_value=1.0 if previous is None else previous,
                            effective_value=combined,
                        )
                    )

            elif kind == "minimum_battery_reserve":
                previous = float(min_energy[hour])
                updated = max(previous, adjustment.minimum_energy_kwh)
                if updated != previous:
                    min_energy[hour] = updated
                    trace.append(
                        ConstraintTrace(
                            hour=hour,
                            field="min_energy",
                            source_note_index=note_index,
                            directive_type=kind,
                            original_value=previous,
                            effective_value=updated,
                        )
                    )

            elif kind == "no_charge_window":
                if charge_allowed[hour]:
                    charge_allowed[hour] = False
                    trace.append(
                        ConstraintTrace(
                            hour=hour,
                            field="charge_allowed",
                            source_note_index=note_index,
                            directive_type=kind,
                            original_value=True,
                            effective_value=False,
                        )
                    )

            elif kind == "no_discharge_window":
                if discharge_allowed[hour]:
                    discharge_allowed[hour] = False
                    trace.append(
                        ConstraintTrace(
                            hour=hour,
                            field="discharge_allowed",
                            source_note_index=note_index,
                            directive_type=kind,
                            original_value=True,
                            effective_value=False,
                        )
                    )

            elif kind == "max_grid_window":
                previous = float(grid_upper[hour])
                updated = min(previous, adjustment.max_grid_kwh)
                if updated != previous:
                    grid_upper[hour] = updated
                    trace.append(
                        ConstraintTrace(
                            hour=hour,
                            field="grid_upper",
                            source_note_index=note_index,
                            directive_type=kind,
                            original_value=previous,
                            effective_value=updated,
                        )
                    )

    solar_factor = np.array(
        [1.0 if factor is None else factor for factor in resolved_factor], dtype=float
    )
    effective_solar = original_solar * solar_factor

    compiled = CompiledConstraints(
        effective_solar=effective_solar,
        min_energy=min_energy,
        charge_allowed=charge_allowed,
        discharge_allowed=discharge_allowed,
        grid_upper=grid_upper,
        original_solar=original_solar,
        solar_factor=solar_factor,
        ambiguity_flags=tuple(sorted(ambiguity_flags)),
        trace=tuple(trace),
    )
    _assert_compiled_invariants(compiled, request)
    return compiled


def _assert_compiled_invariants(compiled: CompiledConstraints, request: OptimizeRequest) -> None:
    """Post-compilation sanity, per Guide §10.

    Reaching any of these means a guardrail let something through that it should have rejected
    or repaired. It is an internal invariant failure, not a caller error, so it fails closed
    rather than being clipped into range.
    """
    capacity = request.battery.capacity_kwh
    problems: list[str] = []

    for name, array in (
        ("effective_solar", compiled.effective_solar),
        ("min_energy", compiled.min_energy),
        ("charge_allowed", compiled.charge_allowed),
        ("discharge_allowed", compiled.discharge_allowed),
        ("grid_upper", compiled.grid_upper),
    ):
        if array.shape != (HOURS_IN_DAY,):
            problems.append(f"{name} has shape {array.shape}, expected ({HOURS_IN_DAY},)")

    if not np.isfinite(compiled.effective_solar).all():
        problems.append("effective_solar contains a non-finite value")
    if (compiled.effective_solar < 0).any():
        problems.append("effective_solar contains a negative value")
    if not np.isfinite(compiled.min_energy).all():
        problems.append("min_energy contains a non-finite value")
    if (compiled.min_energy < 0).any():
        problems.append("min_energy contains a negative value")
    if (compiled.min_energy > capacity).any():
        offenders = np.flatnonzero(compiled.min_energy > capacity).tolist()
        problems.append(f"min_energy exceeds battery capacity {capacity} at hours {offenders}")
    # +inf is the intended "uncapped" marker, so only NaN and negatives are wrong here.
    if np.isnan(compiled.grid_upper).any():
        problems.append("grid_upper contains NaN")
    if (compiled.grid_upper < 0).any():
        problems.append("grid_upper contains a negative value")
    if compiled.charge_allowed.dtype != np.bool_ or compiled.discharge_allowed.dtype != np.bool_:
        problems.append("charge/discharge permissions must be boolean arrays")

    if problems:
        raise DirectiveCompilationFailure(
            "Directive compilation produced an impossible constraint set.",
            details=problems,
        )


__all__ = ["CompiledConstraints", "ConstraintTrace", "compile_directives"]
