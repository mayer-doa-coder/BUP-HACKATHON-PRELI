"""Semantic corpus: well-formedness, policy agreement, and the scoring harness itself.

Measuring the real model's paraphrase accuracy needs credentials, so that run lives behind the
``live`` marker and in ``scripts/paraphrase_eval.py``. What *can* be established offline is
everything the measurement depends on, which is worth more than it sounds:

* every canonical answer in the corpus is one this service can actually produce — it passes the
  guardrails and compiles into constraints;
* the provisional answers agree with the policies this service implements, so a documented
  spec-gap choice cannot silently drift away from the prompt that teaches it;
* the scorer distinguishes a correct interpretation from a wrong one, verified with stubs that
  answer perfectly and imperfectly.

A scorer that cannot fail would make the live number meaningless.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.guardrails.directive_validator import validate_directives
from app.llm.base import ProviderResponse
from app.llm.interpreter import LlmDirectiveInterpreter
from app.optimizer.compile_directives import compile_directives
from app.policies.spec_gaps import expand_window, single_hour_window
from scripts.paraphrase_eval import evaluate, summarize
from scripts.semantic_corpus import (
    BUCKET_ADVERSARIAL,
    BUCKET_PROVISIONAL,
    BUCKET_SEMANTIC,
    load_adversarial_cases,
    load_all_cases,
    load_provisional_cases,
    load_semantic_cases,
)


class CannedProvider:
    """Answers with whatever the caller decides, keyed by the note text it receives."""

    name = "canned"
    model = "canned-1"

    def __init__(self, answer_for):
        self.answer_for = answer_for
        self.seen: list[str] = []

    async def complete(self, *, system_prompt, user_payload, json_schema, timeout_s):
        payload = json.loads(user_payload[user_payload.index("{") : user_payload.rindex("}") + 1])
        note = payload["operator_notes"][0]["text"]
        self.seen.append(note)
        return ProviderResponse(
            content=json.dumps({"directive_interpretation": self.answer_for(note, payload)}),
            model_version=self.model,
        )

    async def aclose(self):
        return None


# ------------------------------------------------------------------- corpus integrity


def test_corpus_has_the_expected_breadth():
    semantic = load_semantic_cases()
    adversarial = load_adversarial_cases()
    provisional = load_provisional_cases()

    assert len(semantic) == 58, "the pack advertises 58 semantic variations"
    assert len({case.group_id for case in semantic}) == 7
    assert len(adversarial) == 5
    assert provisional, "spec-gap cases must be tracked, not dropped"
    assert {case.bucket for case in load_all_cases()} == {
        BUCKET_SEMANTIC,
        BUCKET_ADVERSARIAL,
        BUCKET_PROVISIONAL,
    }


def test_every_group_covers_a_distinct_directive_concern():
    groups = {case.group_id for case in load_semantic_cases()}

    assert "SV-SOLAR-20PCT-REMAINS" in groups
    assert "SV-SOLAR-BY20" in groups, "the by/to contrast must be exercised separately"
    assert "SV-NOOP-DISTRACTORS" in groups


def test_every_canonical_answer_passes_our_own_guardrails():
    """If the corpus's expected answer were unrepresentable here, the target would be wrong."""
    failures = []
    for case in load_all_cases():
        request = case.to_request()
        report = validate_directives([case.expected], request)
        if not report.ok:
            failures.append(f"{case.case_id}: {report.messages}")
    assert not failures, "\n".join(failures)


def test_every_canonical_answer_compiles_into_constraints():
    failures = []
    for case in load_all_cases():
        request = case.to_request()
        report = validate_directives([case.expected], request)
        try:
            compile_directives(request, report.directives)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{case.case_id}: {type(exc).__name__}: {exc}")
    assert not failures, "\n".join(failures)


def test_synthetic_scenarios_are_schedulable():
    """The corpus scenarios must be usable end to end, not just for interpretation."""
    from app.optimizer.hybrid_solve import screen_baseline_feasibility

    for case in load_semantic_cases()[:5]:
        assert screen_baseline_feasibility(case.to_request()).feasible, case.case_id


def test_notes_are_not_public_sample_wording(public_cases):
    """Overfitting guard: the corpus must paraphrase, not echo the published notes."""
    published = {note for case in public_cases for note in case["input"]["operator_notes"]}
    corpus_notes = {case.note for case in load_semantic_cases()}

    assert not (published & corpus_notes)


# ------------------------------------------- provisional answers match our own policies


def test_cross_midnight_expectation_matches_the_configured_policy():
    """AMB-01: ``11 PM to 2 AM`` -> {23, 0, 1}, serialized ascending."""
    case = next(case for case in load_provisional_cases() if case.case_id == "AMB-01")

    assert case.expected["structured_adjustment"]["hours"] == expand_window(23, 2)
    assert case.expected["structured_adjustment"]["hours"] == [0, 1, 23]


def test_single_hour_expectation_matches_the_configured_policy():
    """AMB-04: ``during the 4 PM hour`` -> [16]."""
    case = next(case for case in load_provisional_cases() if case.case_id == "AMB-04")

    assert case.expected["structured_adjustment"]["hours"] == single_hour_window(16)


def test_overlapping_solar_policy_matches_the_pack(adversarial_pack):
    """AMB-03 documents the most-restrictive rule; the compiler must implement that rule."""
    from app.schemas.directive import SolarReductionDirective
    from scripts.semantic_corpus import SemanticCase

    ambiguity = next(c for c in adversarial_pack["spec_ambiguity_cases"] if c["id"] == "AMB-03")
    assert "most restrictive" in ambiguity["provisional_policy"].lower()

    request = SemanticCase(
        case_id="AMB-03", group_id="x", bucket=BUCKET_PROVISIONAL, note="n", expected=None
    ).to_request()
    compiled = compile_directives(
        request,
        [
            SolarReductionDirective(note_index=0, structured_adjustment={"hours": [13, 14], "factor": 0.8}),
            SolarReductionDirective(note_index=1, structured_adjustment={"hours": [14, 15], "factor": 0.5}),
        ],
    )

    assert compiled.solar_factor[14] == pytest.approx(0.5), "most restrictive factor wins"
    assert compiled.ambiguity_flags


# ------------------------------------------------------------------ the scorer works


def _perfect_answer(expected_by_note):
    def answer(note, _payload):
        return [expected_by_note[note]]

    return answer


def test_scorer_reports_full_marks_for_a_perfect_interpreter():
    cases = load_semantic_cases()
    expected_by_note = {case.note: case.expected for case in cases}
    interpreter = LlmDirectiveInterpreter(CannedProvider(_perfect_answer(expected_by_note)))

    results = asyncio.run(evaluate(cases, interpreter))
    scores = summarize(results, cases)

    assert scores[BUCKET_SEMANTIC].total == len(cases)
    assert scores[BUCKET_SEMANTIC].accuracy == 1.0
    assert scores[BUCKET_SEMANTIC].guardrail_rate == 1.0


def test_scorer_detects_an_inverted_factor():
    """The by/to inversion is the single most costly semantic error; the scorer must catch it."""
    cases = [case for case in load_semantic_cases() if case.group_id == "SV-SOLAR-20PCT-REMAINS"]
    expected_by_note = {case.note: case.expected for case in cases}

    def inverted(note, _payload):
        entry = json.loads(json.dumps(expected_by_note[note]))
        entry["structured_adjustment"]["factor"] = 1.0 - entry["structured_adjustment"]["factor"]
        return [entry]

    interpreter = LlmDirectiveInterpreter(CannedProvider(inverted))
    results = asyncio.run(evaluate(cases, interpreter))

    assert all(not result.matched for result in results)
    assert all(any("factor" in problem for problem in result.problems) for result in results)


def test_scorer_detects_an_off_by_one_window():
    cases = [case for case in load_semantic_cases() if case.group_id == "SV-NO-CHARGE"]
    expected_by_note = {case.note: case.expected for case in cases}

    def shifted(note, _payload):
        entry = json.loads(json.dumps(expected_by_note[note]))
        hours = entry["structured_adjustment"]["hours"]
        entry["structured_adjustment"]["hours"] = [*hours, hours[-1] + 1]
        return [entry]

    interpreter = LlmDirectiveInterpreter(CannedProvider(shifted))
    results = asyncio.run(evaluate(cases, interpreter))

    assert all(not result.matched for result in results)


def test_scorer_counts_a_guardrail_rejection_as_a_miss():
    """A rejected interpretation is not a pass, however plausible it looked."""
    cases = load_semantic_cases()[:3]

    def invalid(_note, _payload):
        return [
            {
                "note_index": 0,
                "applies": True,
                "directive_type": "solar_reduction",
                "structured_adjustment": {"hours": [13, 13], "factor": 0.2},
                "explanation": "duplicate hours",
            }
        ]

    interpreter = LlmDirectiveInterpreter(CannedProvider(invalid))
    results = asyncio.run(evaluate(cases, interpreter))
    scores = summarize(results, cases)

    assert scores[BUCKET_SEMANTIC].accuracy == 0.0
    assert scores[BUCKET_SEMANTIC].guardrail_rate == 0.0


def test_scorer_tracks_no_op_relevance_separately():
    cases = [case for case in load_semantic_cases() if case.group_id == "SV-NOOP-DISTRACTORS"]
    expected_by_note = {case.note: case.expected for case in cases}
    interpreter = LlmDirectiveInterpreter(CannedProvider(_perfect_answer(expected_by_note)))

    results = asyncio.run(evaluate(cases, interpreter))
    scores = summarize(results, cases)

    assert scores[BUCKET_SEMANTIC].no_op_total == len(cases)
    assert scores[BUCKET_SEMANTIC].no_op_matched == len(cases)


def test_scorer_survives_a_provider_failure():
    """One dead case must not abort the whole evaluation run."""
    from app.llm.base import ProviderUnavailable

    class _Failing:
        name = "failing"
        model = "failing-1"

        async def complete(self, **_kwargs):
            raise ProviderUnavailable("503")

        async def aclose(self):
            return None

    cases = load_semantic_cases()[:3]
    results = asyncio.run(evaluate(cases, LlmDirectiveInterpreter(_Failing())))

    assert len(results) == 3
    assert all(not result.matched for result in results)
    assert all("ProviderUnavailable" in problem for result in results for problem in result.problems)
