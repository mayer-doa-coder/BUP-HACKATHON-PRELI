"""Bounded repair and retry policy.

The point of this phase is that failures are *not* interchangeable, so the tests check the
routing, not merely that "a retry happened":

* a transport blip is retried with the same payload;
* a schema violation is retried with structural feedback attached;
* a semantic violation is retried with the broken rules named and the original notes re-read;
* an exhausted budget stops the loop rather than burning the deadline;
* the retry count is capped no matter how the first attempt failed.

A test that only asserted "two calls were made" would pass even if the wrong feedback were sent,
so each case inspects what the second call actually carried.
"""

from __future__ import annotations

import asyncio
import copy

import pytest

from app.config import Settings
from app.llm.base import (
    MalformedModelOutput,
    ModelRefusal,
    ModelTruncated,
    ProviderRateLimited,
    ProviderResponse,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.llm.interpreter import LlmDirectiveInterpreter
from app.llm.repair import (
    MINIMUM_ATTEMPT_SECONDS,
    InterpretationRunner,
    RepairReason,
)
from app.schemas.request import OptimizeRequest
from app.services.deadline import Deadline


class ScriptedProvider:
    """Replays a scripted sequence of outcomes and records every call it received."""

    def __init__(self, script):
        self.name = "scripted"
        self.model = "scripted-1"
        self.script = list(script)
        self.calls: list[dict] = []

    async def complete(self, *, system_prompt, user_payload, json_schema, timeout_s):
        self.calls.append({"user_payload": user_payload, "timeout_s": timeout_s})
        step = self.script.pop(0) if self.script else self.script_default()
        if isinstance(step, Exception):
            raise step
        import json as _json

        return ProviderResponse(content=_json.dumps(step), model_version=self.model, finish_reason="stop")

    def script_default(self):
        raise AssertionError("provider called more times than the script allows")

    async def aclose(self):
        return None


def _runner(script, settings: Settings | None = None, backup=None) -> tuple[InterpretationRunner, ScriptedProvider]:
    settings = settings or Settings(_env_file=None)
    provider = ScriptedProvider(script)
    backup_interpreter = LlmDirectiveInterpreter(backup, settings) if backup is not None else None
    runner = InterpretationRunner(
        LlmDirectiveInterpreter(provider, settings), settings, backup_interpreter
    )
    return runner, provider


def _good(case):
    return {"directive_interpretation": case["expected_output"]["directive_interpretation"]}


def _bad_semantics(case):
    """Schema-shaped but rule-breaking: duplicate hours."""
    payload = copy.deepcopy(_good(case))
    for entry in payload["directive_interpretation"]:
        if entry["structured_adjustment"] and "hours" in entry["structured_adjustment"]:
            hours = entry["structured_adjustment"]["hours"]
            entry["structured_adjustment"]["hours"] = [hours[0], hours[0], *hours[1:]]
            break
    return payload


def _request(case) -> OptimizeRequest:
    return OptimizeRequest.model_validate(case["input"])


def _deadline(seconds: float = 30.0) -> Deadline:
    return Deadline.start(seconds)


# ------------------------------------------------------------------------- happy path


def test_a_clean_first_attempt_makes_exactly_one_call(public_cases):
    case = public_cases[0]
    runner, provider = _runner([_good(case)])

    run = asyncio.run(runner.run(_request(case), _deadline()))

    assert run.ok
    assert run.attempts == 1
    assert run.repairs == []
    assert len(provider.calls) == 1
    assert run.model_version == "scripted-1"


# ------------------------------------------------------------------ semantic repair


def test_a_guardrail_failure_triggers_one_focused_semantic_repair(public_cases):
    case = public_cases[0]
    runner, provider = _runner([_bad_semantics(case), _good(case)])

    run = asyncio.run(runner.run(_request(case), _deadline()))

    assert run.ok
    assert run.attempts == 2
    assert run.repairs == [RepairReason.SEMANTIC]

    repair_payload = provider.calls[1]["user_payload"]
    assert "BROKE ONE OR MORE HARD RULES" in repair_payload
    assert "duplicate_hours" in repair_payload
    # The original notes are re-read, not replaced by the feedback.
    for note in case["input"]["operator_notes"]:
        assert note in repair_payload


def test_the_repair_never_supplies_the_expected_answer(public_cases):
    """Feedback names the broken rule; handing over the answer would fake understanding."""
    case = public_cases[0]
    runner, provider = _runner([_bad_semantics(case), _good(case)])

    asyncio.run(runner.run(_request(case), _deadline()))
    repair_payload = provider.calls[1]["user_payload"]

    assert "Do not invent a value" in repair_payload
    expected_factor = case["expected_output"]["directive_interpretation"][0]["structured_adjustment"]["factor"]
    assert f"factor should be {expected_factor}" not in repair_payload


def test_a_second_guardrail_failure_ends_the_attempt_budget(public_cases):
    case = public_cases[0]
    runner, provider = _runner([_bad_semantics(case), _bad_semantics(case)])

    run = asyncio.run(runner.run(_request(case), _deadline()))

    assert not run.ok
    assert run.attempts == 2
    assert len(provider.calls) == 2
    assert "duplicate_hours" in run.failure_codes


# -------------------------------------------------------------------- schema repair


def test_malformed_output_triggers_a_structural_repair(public_cases):
    case = public_cases[0]
    error = MalformedModelOutput("bad json", problems=["directive_interpretation: missing"])
    runner, provider = _runner([error, _good(case)])

    run = asyncio.run(runner.run(_request(case), _deadline()))

    assert run.ok
    assert run.repairs == [RepairReason.SCHEMA]
    repair_payload = provider.calls[1]["user_payload"]
    assert "STRUCTURALLY INVALID" in repair_payload
    assert "directive_interpretation: missing" in repair_payload
    assert "only fix the structure itself" in repair_payload.replace("\n", " ")


# ------------------------------------------------------------- transport and quota


@pytest.mark.parametrize(
    ("error", "expected_reason"),
    [
        (ProviderUnavailable("503"), RepairReason.TRANSPORT),
        (ProviderTimeout("slow"), RepairReason.TRANSPORT),
        (ModelRefusal("declined"), RepairReason.REFUSAL),
        (ModelTruncated("cut off"), RepairReason.TRUNCATION),
    ],
)
def test_provider_failures_route_to_their_own_reason(public_cases, error, expected_reason):
    case = public_cases[0]
    runner, provider = _runner([error, _good(case)])

    run = asyncio.run(runner.run(_request(case), _deadline()))

    assert run.ok
    assert run.repairs == [expected_reason]
    assert len(provider.calls) == 2
    # A transport retry repeats the same request; it carries no corrective feedback.
    if expected_reason is RepairReason.TRANSPORT:
        assert "STRUCTURALLY INVALID" not in provider.calls[1]["user_payload"]
        assert "BROKE ONE OR MORE" not in provider.calls[1]["user_payload"]


def test_rate_limit_is_retried_when_the_hint_fits_the_budget(public_cases):
    case = public_cases[0]
    runner, provider = _runner([ProviderRateLimited("429", retry_after=0.01), _good(case)])

    run = asyncio.run(runner.run(_request(case), _deadline(30.0)))

    assert run.ok
    assert run.repairs == [RepairReason.RATE_LIMIT]
    assert len(provider.calls) == 2


def test_rate_limit_falls_back_when_the_hint_does_not_fit(public_cases):
    """Waiting out a 20 s hint inside a 3 s budget would fail the request anyway."""
    case = public_cases[0]
    backup = ScriptedProvider([_good(case)])
    runner, primary = _runner([ProviderRateLimited("429", retry_after=20.0)], backup=backup)

    run = asyncio.run(runner.run(_request(case), _deadline(3.0)))

    assert run.ok
    assert run.used_backup
    assert len(primary.calls) == 1
    assert len(backup.calls) == 1


def test_rate_limit_without_a_backup_gives_up_rather_than_overrunning(public_cases):
    case = public_cases[0]
    runner, provider = _runner([ProviderRateLimited("429", retry_after=20.0)])

    run = asyncio.run(runner.run(_request(case), _deadline(3.0)))

    assert not run.ok
    assert len(provider.calls) == 1
    assert run.last_error == "ProviderRateLimited"


# ------------------------------------------------------------------- attempt budget


def test_attempts_are_capped_by_configuration(public_cases, monkeypatch):
    monkeypatch.setenv("LLM_MAX_ATTEMPTS", "1")
    case = public_cases[0]
    runner, provider = _runner([_bad_semantics(case), _good(case)], Settings(_env_file=None))

    run = asyncio.run(runner.run(_request(case), _deadline()))

    assert not run.ok
    assert run.attempts == 1
    assert len(provider.calls) == 1, "no retry is allowed when the budget is one attempt"


def test_an_exhausted_deadline_prevents_any_call(public_cases):
    case = public_cases[0]
    runner, provider = _runner([_good(case)])

    run = asyncio.run(runner.run(_request(case), _deadline(0.0)))

    assert not run.ok
    assert provider.calls == []
    assert run.last_error == "request budget exhausted"


def test_the_attempt_timeout_never_exceeds_the_remaining_budget(public_cases):
    case = public_cases[0]
    runner, provider = _runner([_good(case)])
    tight = _deadline(1.0)

    asyncio.run(runner.run(_request(case), tight))

    assert provider.calls[0]["timeout_s"] <= 1.0


def test_a_retry_is_skipped_when_too_little_time_remains(public_cases):
    """A retry that cannot land wastes the provider quota and the request either way."""
    case = public_cases[0]
    runner, provider = _runner([_bad_semantics(case), _good(case)])

    run = asyncio.run(runner.run(_request(case), _deadline(MINIMUM_ATTEMPT_SECONDS * 0.5)))

    assert not run.ok
    assert provider.calls == []


# --------------------------------------------------- feasibility reinterpretation


def test_feasibility_repair_re_reads_the_notes_without_relaxing_anything(public_cases):
    case = public_cases[0]
    runner, provider = _runner([_good(case)])

    run = asyncio.run(runner.reinterpret_for_feasibility(_request(case), _deadline()))

    assert run.ok
    assert run.repairs == [RepairReason.FEASIBILITY]
    payload = provider.calls[0]["user_payload"]
    assert "IMPOSSIBLE SCHEDULE" in payload
    assert "Do NOT weaken, drop, or soften a directive" in payload
    assert "reduced BY vs reduced TO" in payload
    for note in case["input"]["operator_notes"]:
        assert note in payload


def test_feasibility_repair_reports_failure_rather_than_raising(public_cases):
    case = public_cases[0]
    runner, _provider = _runner([ProviderUnavailable("503")])

    run = asyncio.run(runner.reinterpret_for_feasibility(_request(case), _deadline()))

    assert not run.ok
    assert run.last_error == "ProviderUnavailable"


def test_feasibility_repair_respects_the_deadline(public_cases):
    case = public_cases[0]
    runner, provider = _runner([_good(case)])

    run = asyncio.run(runner.reinterpret_for_feasibility(_request(case), _deadline(0.0)))

    assert not run.ok
    assert provider.calls == []


# ------------------------------------------------------------------------ deadline


def test_deadline_tracks_remaining_time():
    deadline = Deadline.start(10.0)

    assert deadline.remaining() <= 10.0
    assert not deadline.expired()
    assert deadline.allows(1.0)
    assert deadline.timeout_for(3.0) == pytest.approx(3.0, abs=0.1)
    assert deadline.timeout_for(100.0) <= 10.0


def test_expired_deadline_allows_nothing():
    deadline = Deadline.start(0.0)

    assert deadline.expired()
    assert not deadline.allows(0.1)
    assert deadline.timeout_for(5.0) == 0.0
