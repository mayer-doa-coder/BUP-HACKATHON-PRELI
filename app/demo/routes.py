"""Demo routes, mounted only when the demo profile is enabled.

These exist to make the LLM -> guardrail -> optimizer -> replay boundary visible to a reviewer.
They are **not** part of the judged contract: they live on their own router, under their own
prefix, and are only mounted when configuration asks for them (see ``demo_enabled``).

Everything returned here is derived from a real run of the production pipeline. Nothing on this
router can change ``/optimize-energy``'s behaviour, schema, or latency.
"""

from __future__ import annotations

import copy
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

from app.api.routes import get_optimize_service
from app.config import Settings, get_settings
from app.demo.models import (
    AnalysisResponse,
    ParaphraseResponse,
    PolicySummary,
    WhatIfResponse,
)
from app.demo.page import DEMO_PAGE
from app.demo.service import build_analysis, paraphrase_variant, solve_for_demo
from app.policies.spec_gaps import policy_summary
from app.schemas.request import OptimizeRequest
from app.services.optimize_service import OptimizeService

router = APIRouter(prefix="/demo", tags=["demo"], include_in_schema=False)

ServiceDependency = Annotated[OptimizeService, Depends(get_optimize_service)]


def demo_enabled(settings: Settings | None = None) -> bool:
    """Whether the demo profile is on.

    Requires ``DEMO_MODE`` **and** the absence of ``JUDGE_MODE``. Two flags rather than one is
    deliberate: ``JUDGE_MODE`` is the locked-down production profile, so a deployment that
    accidentally ships with ``DEMO_MODE=true`` still exposes nothing extra to the judge.
    """
    settings = settings or get_settings()
    return settings.demo_mode and not settings.judge_mode


async def _interpret(
    service: OptimizeService, request: OptimizeRequest
) -> tuple[list, str]:
    """Interpret notes for the demo, reporting *why* if the model is unavailable."""
    from app.api.errors import InterpretationUnavailable

    try:
        return list(await service.interpret(request)), "llm"
    except InterpretationUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "The demo needs a working interpreter. Configure LLM_PROVIDER, LLM_MODEL and "
                f"LLM_API_KEY. ({'; '.join(exc.details) if exc.details else exc.message})"
            ),
        ) from exc


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    """A single self-contained page — no CDN, no build step, works offline."""
    return HTMLResponse(content=DEMO_PAGE)


@router.get("/config", response_model=PolicySummary)
async def configuration() -> PolicySummary:
    """Versions and provisional policies. Never secrets — only whether a key is present."""
    settings = get_settings()
    return PolicySummary(
        prompt_version=settings.prompt_version,
        schema_version=settings.schema_version,
        optimizer_version=settings.optimizer_version,
        app_commit_sha=settings.app_commit_sha,
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        llm_configured=bool(settings.llm_model and settings.llm_api_key.get_secret_value()),
        provisional_policies=policy_summary(settings),
        judge_tolerance=settings.judge_tolerance,
        internal_tolerance=settings.internal_tolerance,
    )


@router.post("/analyze", response_model=AnalysisResponse)
async def analyze(payload: OptimizeRequest, service: ServiceDependency) -> AnalysisResponse:
    """The full pipeline trace: note -> directive -> constraint -> plan -> replay proof."""
    started = time.perf_counter()
    service.validate(payload)
    service.screen_feasibility(payload)
    directives, source = await _interpret(service, payload)
    response, outcome, _ = solve_for_demo(payload, directives, service)

    return build_analysis(
        payload,
        directives,
        response,
        outcome,
        elapsed_ms=(time.perf_counter() - started) * 1000.0,
        interpretation_source=source,
    )


@router.post("/what-if", response_model=WhatIfResponse)
async def what_if(
    payload: dict[str, Any],
    service: ServiceDependency,
) -> WhatIfResponse:
    """Re-run a scenario under changed conditions and show what moved.

    Body: ``{"scenario": <request>, "changes": {"battery": {...}, "tariff_multiplier": 1.2,
    "solar_multiplier": 0.5}}``. The interpretation is reused, so the comparison isolates the
    *scenario* change rather than mixing in a fresh model call.
    """
    scenario = payload.get("scenario")
    if not isinstance(scenario, dict):
        raise HTTPException(status_code=400, detail="body must contain a 'scenario' object")
    changes = payload.get("changes") or {}

    baseline_request = OptimizeRequest.model_validate(scenario)
    service.validate(baseline_request)
    service.screen_feasibility(baseline_request)
    directives, source = await _interpret(service, baseline_request)

    baseline_response, _, _ = solve_for_demo(baseline_request, directives, service)

    modified_body = _apply_changes(scenario, changes)
    modified_request = OptimizeRequest.model_validate(modified_body)
    service.validate(modified_request)
    service.screen_feasibility(modified_request)
    modified_response, modified_outcome, _ = solve_for_demo(modified_request, directives, service)

    baseline_by_hour = {entry.hour: entry.grid_kwh for entry in baseline_response.hourly_plan}
    changed_hours = [
        entry.hour
        for entry in modified_response.hourly_plan
        if abs(entry.grid_kwh - baseline_by_hour.get(entry.hour, 0.0)) > 1e-6
    ]

    return WhatIfResponse(
        baseline_cost_bdt=baseline_response.total_cost_bdt,
        modified_cost_bdt=modified_response.total_cost_bdt,
        cost_delta_bdt=modified_response.total_cost_bdt - baseline_response.total_cost_bdt,
        changed_hours=changed_hours,
        modified=build_analysis(
            modified_request,
            directives,
            modified_response,
            modified_outcome,
            interpretation_source=source,
        ),
    )


def _apply_changes(scenario: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    body = copy.deepcopy(scenario)
    battery_changes = changes.get("battery") or {}
    if battery_changes:
        body["battery"].update(battery_changes)

    tariff_multiplier = float(changes.get("tariff_multiplier", 1.0))
    solar_multiplier = float(changes.get("solar_multiplier", 1.0))
    demand_multiplier = float(changes.get("demand_multiplier", 1.0))
    for entry in body["hours"]:
        entry["tariff_bdt_per_kwh"] *= tariff_multiplier
        entry["solar_kwh"] *= solar_multiplier
        entry["demand_kwh"] *= demand_multiplier
    return body


@router.post("/paraphrase", response_model=ParaphraseResponse)
async def paraphrase(payload: dict[str, Any], service: ServiceDependency) -> ParaphraseResponse:
    """Do different phrasings of one instruction normalize to the same directive?

    Body: ``{"scenario": <request>, "reference": "...", "variants": ["...", "..."]}``. This is
    the robustness question hidden tests actually ask, shown directly.
    """
    scenario = payload.get("scenario")
    reference_note = payload.get("reference")
    variants = payload.get("variants") or []
    if not isinstance(scenario, dict) or not isinstance(reference_note, str):
        raise HTTPException(status_code=400, detail="body needs 'scenario' and 'reference'")

    async def _one(note: str):
        body = copy.deepcopy(scenario)
        body["operator_notes"] = [note]
        request = OptimizeRequest.model_validate(body)
        directives, _ = await _interpret(service, request)
        return paraphrase_variant(directives, note)

    reference = await _one(reference_note)
    rendered = []
    for note in variants[:8]:
        variant = await _one(note)
        variant.matches_reference = (
            variant.directive_type == reference.directive_type
            and variant.hours == reference.hours
            and _close(variant.numeric_value, reference.numeric_value)
        )
        rendered.append(variant)

    return ParaphraseResponse(
        reference=reference,
        variants=rendered,
        all_agree=all(item.matches_reference for item in rendered) if rendered else True,
    )


def _close(left: float | None, right: float | None) -> bool:
    if left is None and right is None:
        return True
    if left is None or right is None:
        return False
    return abs(left - right) <= 0.01


@router.get("/sample-scenario")
async def sample_scenario() -> dict[str, Any]:
    """A ready-to-run scenario for the page, taken from the public pack."""
    from scripts.run_public_cases import DEFAULT_CASE_FILE, load_cases

    return load_cases(DEFAULT_CASE_FILE)[0]["input"]


@router.get("/public-cases")
async def public_cases() -> dict[str, Any]:
    """Run the public regression through the deterministic path and report the table."""
    from scripts.run_public_cases import DEFAULT_CASE_FILE, load_cases, run_cases

    results = run_cases(load_cases(DEFAULT_CASE_FILE))
    return {
        "passed": sum(1 for result in results if result.passed),
        "total": len(results),
        "cases": [
            {
                "case_id": result.case_id,
                "validity": result.validity,
                "cost_gap": result.cost_gap,
                "latency_ms": round(result.latency_ms, 1),
                "problems": result.problems,
            }
            for result in results
        ],
    }


__all__ = ["demo_enabled", "router"]
