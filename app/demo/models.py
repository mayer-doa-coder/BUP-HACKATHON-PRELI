"""Demo-only response models.

Kept entirely separate from ``app.schemas.response``. The canonical response has exactly seven
fields and must never grow a debug, confidence, or solver field, so the demo's richer view lives
in its own types on its own routes (PRD §13).

Everything here is sanitized: statuses, numbers, and directive types. No prompts, no provider
payloads, no credentials.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.schemas.directive import DirectiveInterpretation
from app.schemas.response import HourPlan


class DemoModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoteInterpretationView(DemoModel):
    """One row of the pipeline trace: what the operator wrote, and what it became."""

    note_index: int
    note: str
    directive_type: str
    applies: bool
    hours: list[int] = []
    numeric_value: float | None = None
    numeric_label: str = ""
    explanation: str = ""
    guardrail_status: str = "passed"


class HourDetail(DemoModel):
    """Everything about one hour, for the energy chart and the constraint bands."""

    hour: int
    demand_kwh: float
    original_solar_kwh: float
    effective_solar_kwh: float
    solar_used_kwh: float
    grid_kwh: float
    battery_action: str
    battery_kwh: float
    battery_energy_after_kwh: float
    tariff_bdt_per_kwh: float
    cost_bdt: float

    # Constraint bands
    min_energy_kwh: float
    grid_cap_kwh: float | None = None
    charge_allowed: bool = True
    discharge_allowed: bool = True

    #: Which limits are actually binding this hour — the "why this hour" view.
    binding: list[str] = []


class ValidationProof(DemoModel):
    """The replay evidence, shown as numbers rather than a claim."""

    passed: bool
    max_energy_balance_error: float
    max_battery_transition_error: float
    final_state_of_charge_error: float
    recalculated_total_grid_kwh: float
    recalculated_total_cost_bdt: float
    recalculated_peak_grid_kwh: float
    violations: list[str] = []


class CostComparison(DemoModel):
    """Optimized plan against a no-storage baseline, which may legitimately be impossible."""

    optimized_cost_bdt: float
    baseline_cost_bdt: float | None = None
    baseline_feasible: bool = True
    baseline_note: str = ""
    savings_bdt: float | None = None
    savings_percent: float | None = None


class SolverDiagnostics(DemoModel):
    lp_status: str = ""
    lp_objective: float | None = None
    milp_status: str = ""
    milp_objective: float | None = None
    milp_gap: float | None = None
    proven_optimal: bool = False
    lp_duration_ms: float = 0.0
    milp_duration_ms: float = 0.0
    #: LP <= MILP within tolerance. A violation would mean the two stages solved different models.
    lower_bound_respected: bool = True


class ConstraintOrigin(DemoModel):
    """Provenance: which note produced which per-hour bound."""

    hour: int
    field: str
    source_note_index: int
    directive_type: str
    original_value: float | bool
    effective_value: float | bool


class AnalysisResponse(DemoModel):
    """The whole pipeline, made visible."""

    scenario_id: str
    interpretation: list[NoteInterpretationView]
    directives: list[DirectiveInterpretation]
    hours: list[HourDetail]
    plan: list[HourPlan]
    totals_grid_kwh: float
    totals_cost_bdt: float
    peak_grid_kwh: float
    plan_summary: str
    solver: SolverDiagnostics
    validation: ValidationProof
    cost_comparison: CostComparison
    constraint_origins: list[ConstraintOrigin] = []
    ambiguity_flags: list[str] = []
    interpretation_source: str = "llm"
    pipeline_ms: float = 0.0


class ParaphraseVariant(DemoModel):
    note: str
    directive_type: str = ""
    hours: list[int] = []
    numeric_value: float | None = None
    matches_reference: bool = False
    error: str = ""


class ParaphraseResponse(DemoModel):
    """Do different phrasings of the same instruction normalize to the same directive?"""

    reference: ParaphraseVariant
    variants: list[ParaphraseVariant]
    all_agree: bool


class WhatIfResponse(DemoModel):
    """A re-run under changed conditions, with the difference called out."""

    baseline_cost_bdt: float
    modified_cost_bdt: float
    cost_delta_bdt: float
    changed_hours: list[int]
    modified: AnalysisResponse


class PolicySummary(DemoModel):
    """Sanitized configuration: versions and policies, never secrets."""

    prompt_version: str
    schema_version: str
    optimizer_version: str
    app_commit_sha: str
    llm_provider: str
    llm_model: str
    llm_configured: bool
    provisional_policies: dict[str, str]
    judge_tolerance: float
    internal_tolerance: float


__all__ = [
    "AnalysisResponse",
    "ConstraintOrigin",
    "CostComparison",
    "DemoModel",
    "HourDetail",
    "NoteInterpretationView",
    "ParaphraseResponse",
    "ParaphraseVariant",
    "PolicySummary",
    "SolverDiagnostics",
    "ValidationProof",
    "WhatIfResponse",
]
