"""Loader for the semantic and adversarial corpus.

The ten public cases are semantic *seeds*, not a test set: hidden notes paraphrase the same
directives in wording nobody here has seen. This module turns the corpus packs into a flat list
of cases that can be run through the interpreter and scored.

Three buckets, kept separate on purpose:

* ``semantic`` — paraphrases that must all resolve to one canonical directive. A miss here is a
  real interpretation failure.
* ``adversarial`` — prompt-injection and schema-injection attempts. The note still carries a
  genuine operational instruction, and that instruction is what must come back.
* ``provisional`` — cases the specification leaves open. Scored separately, because a "failure"
  here may just mean the organizers chose the other reading, and it must never be allowed to
  move the headline number.

Each case carries its own battery context, because a percentage reserve resolves against
capacity. The 24-hour profile is synthetic and never reaches the model (D-05); it exists only so
a complete, feasible ``OptimizeRequest`` can be built.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.schemas.request import OptimizeRequest  # noqa: E402

ADVERSARIAL_PACK = REPO_ROOT / "docs" / "GridWise_Adversarial_Edge_Cases.json"

DEFAULT_BATTERY = {
    "capacity_kwh": 200.0,
    "initial_energy_kwh": 100.0,
    "minimum_energy_kwh": 40.0,
    "max_charge_kwh_per_hour": 50.0,
    "max_discharge_kwh_per_hour": 50.0,
}

BUCKET_SEMANTIC = "semantic"
BUCKET_ADVERSARIAL = "adversarial"
BUCKET_PROVISIONAL = "provisional"


@dataclass(frozen=True)
class SemanticCase:
    """One note with the directive it must resolve to."""

    case_id: str
    group_id: str
    bucket: str
    note: str
    expected: dict[str, Any] | None
    battery: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_BATTERY))
    #: Extra notes that belong to the same scenario (used by the overlapping-solar case).
    extra_notes: tuple[str, ...] = ()

    @property
    def notes(self) -> list[str]:
        return [self.note, *self.extra_notes]

    def to_request(self) -> OptimizeRequest:
        """A complete, feasible scenario carrying this case's notes and battery."""
        return OptimizeRequest.model_validate(
            {
                "scenario_id": self.case_id,
                "operator_notes": self.notes,
                "hours": synthetic_hours(),
                "battery": self.battery,
            }
        )


def synthetic_hours() -> list[dict[str, float]]:
    """A plain 24-hour profile: moderate demand, a daytime solar arc, a cheap night tariff.

    Deliberately unremarkable. It never reaches the model, and it is only shaped enough to keep
    the scenario schedulable so a case can also be run end to end.
    """
    solar_by_hour = {
        6: 10.0, 7: 30.0, 8: 60.0, 9: 90.0, 10: 120.0, 11: 140.0,
        12: 150.0, 13: 140.0, 14: 120.0, 15: 90.0, 16: 60.0, 17: 25.0,
    }
    hours = []
    for hour in range(24):
        peak_evening = 18 <= hour <= 21
        hours.append(
            {
                "hour": hour,
                "demand_kwh": 160.0 if peak_evening else 110.0,
                "solar_kwh": solar_by_hour.get(hour, 0.0),
                "tariff_bdt_per_kwh": 14.0 if peak_evening else (6.0 if hour < 6 else 10.0),
            }
        )
    return hours


def _load_pack() -> dict[str, Any]:
    return json.loads(ADVERSARIAL_PACK.read_text(encoding="utf-8"))


def load_semantic_cases(pack: dict[str, Any] | None = None) -> list[SemanticCase]:
    """Every paraphrase, flattened, each carrying its group's canonical interpretation."""
    pack = pack or _load_pack()
    cases: list[SemanticCase] = []

    for group in pack["semantic_variation_groups"]:
        battery = dict(group.get("battery_context") or DEFAULT_BATTERY)
        canonical = group["canonical_interpretation"]
        for index, variation in enumerate(group["variations"]):
            cases.append(
                SemanticCase(
                    case_id=f"{group['group_id']}#{index:02d}",
                    group_id=group["group_id"],
                    bucket=BUCKET_SEMANTIC,
                    note=variation,
                    expected=_with_note_index(canonical),
                    battery=battery,
                )
            )
    return cases


def load_adversarial_cases(pack: dict[str, Any] | None = None) -> list[SemanticCase]:
    """Injection attempts. The genuine instruction inside the note is the expected answer."""
    pack = pack or _load_pack()
    return [
        SemanticCase(
            case_id=item["id"],
            group_id=item.get("threat", "injection"),
            bucket=BUCKET_ADVERSARIAL,
            note=item["note"],
            expected=_with_note_index(item["expected"]),
        )
        for item in pack["adversarial_notes"]
    ]


def load_provisional_cases(pack: dict[str, Any] | None = None) -> list[SemanticCase]:
    """Specification gaps. Scored separately — the organizers may choose the other reading."""
    pack = pack or _load_pack()
    cases: list[SemanticCase] = []

    for item in pack["spec_ambiguity_cases"]:
        provisional = item.get("provisional_interpretation")
        if provisional is None:
            # AMB-03 lists competing readings rather than one provisional answer; it is covered
            # by the compiler's overlap policy tests instead.
            continue
        notes = item.get("notes") or [item["note"]]
        cases.append(
            SemanticCase(
                case_id=item["id"],
                group_id=item.get("status", "provisional"),
                bucket=BUCKET_PROVISIONAL,
                note=notes[0],
                expected=_with_note_index(provisional),
                extra_notes=tuple(notes[1:]),
            )
        )
    return cases


def load_all_cases(pack: dict[str, Any] | None = None) -> list[SemanticCase]:
    pack = pack or _load_pack()
    return [
        *load_semantic_cases(pack),
        *load_adversarial_cases(pack),
        *load_provisional_cases(pack),
    ]


def _with_note_index(interpretation: dict[str, Any]) -> dict[str, Any]:
    """Normalize a canonical interpretation into a full entry for the comparator."""
    entry = dict(interpretation)
    entry.setdefault("note_index", 0)
    entry.setdefault("applies", entry.get("directive_type") != "no_op")
    entry.setdefault("structured_adjustment", None)
    entry.setdefault("explanation", "")
    return entry


__all__ = [
    "BUCKET_ADVERSARIAL",
    "BUCKET_PROVISIONAL",
    "BUCKET_SEMANTIC",
    "DEFAULT_BATTERY",
    "SemanticCase",
    "load_adversarial_cases",
    "load_all_cases",
    "load_provisional_cases",
    "load_semantic_cases",
    "synthetic_hours",
]
