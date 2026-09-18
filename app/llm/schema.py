"""The JSON Schema the model's output is constrained to.

A tagged union of the six directive variants, so impossible combinations — a ``no_op`` carrying
an adjustment, a ``solar_reduction`` with ``applies=false`` — cannot be produced in the first
place. The array length is pinned to the note count, which removes the most common structural
failure (one interpretation for two notes) before it ever reaches the guardrails.

Constraints are expressed with ``type`` + ``enum`` rather than ``const`` because that subset is
accepted by every structured-output implementation this service targets.

**This schema solves shape, not truth.** A schema-valid ``factor: 0.8`` is still wrong when the
note said "80% reduction", which is why deterministic semantic validation follows regardless of
how strictly the provider enforced the schema.
"""

from __future__ import annotations

from typing import Any

from app.schemas.directive import DirectiveType
from app.schemas.request import HOURS_IN_DAY

SCHEMA_NAME = "gridwise_directive_interpretation"


def _hours_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "description": "Affected hours: unique integers 0-23 in ascending order.",
        "items": {"type": "integer", "minimum": 0, "maximum": HOURS_IN_DAY - 1},
        "minItems": 1,
        "maxItems": HOURS_IN_DAY,
    }


def _variant(
    directive_type: DirectiveType,
    *,
    note_count: int,
    adjustment: dict[str, Any],
    applies: bool,
) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["note_index", "applies", "directive_type", "structured_adjustment", "explanation"],
        "properties": {
            "note_index": {
                "type": "integer",
                "minimum": 0,
                "maximum": max(note_count - 1, 0),
                "description": "Zero-based index of the operator note this entry interprets.",
            },
            "applies": {"type": "boolean", "enum": [applies]},
            "directive_type": {"type": "string", "enum": [directive_type.value]},
            "structured_adjustment": adjustment,
            "explanation": {
                "type": "string",
                "description": "One short factual sentence. Never a justification for inventing a value.",
            },
        },
    }


def build_interpretation_schema(note_count: int) -> dict[str, Any]:
    """Schema for exactly ``note_count`` interpretation entries."""
    variants = [
        _variant(
            DirectiveType.SOLAR_REDUCTION,
            note_count=note_count,
            applies=True,
            adjustment={
                "type": "object",
                "additionalProperties": False,
                "required": ["hours", "factor"],
                "properties": {
                    "hours": _hours_schema(),
                    "factor": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "description": "Usable fraction of solar that REMAINS. An 80% reduction is 0.2.",
                    },
                },
            },
        ),
        _variant(
            DirectiveType.MINIMUM_BATTERY_RESERVE,
            note_count=note_count,
            applies=True,
            adjustment={
                "type": "object",
                "additionalProperties": False,
                "required": ["hours", "minimum_energy_kwh"],
                "properties": {
                    "hours": _hours_schema(),
                    "minimum_energy_kwh": {
                        "type": "number",
                        "minimum": 0,
                        "description": "Absolute kWh floor. Convert a percentage using battery capacity.",
                    },
                },
            },
        ),
        _variant(
            DirectiveType.NO_CHARGE_WINDOW,
            note_count=note_count,
            applies=True,
            adjustment={
                "type": "object",
                "additionalProperties": False,
                "required": ["hours"],
                "properties": {"hours": _hours_schema()},
            },
        ),
        _variant(
            DirectiveType.NO_DISCHARGE_WINDOW,
            note_count=note_count,
            applies=True,
            adjustment={
                "type": "object",
                "additionalProperties": False,
                "required": ["hours"],
                "properties": {"hours": _hours_schema()},
            },
        ),
        _variant(
            DirectiveType.MAX_GRID_WINDOW,
            note_count=note_count,
            applies=True,
            adjustment={
                "type": "object",
                "additionalProperties": False,
                "required": ["hours", "max_grid_kwh"],
                "properties": {
                    "hours": _hours_schema(),
                    "max_grid_kwh": {
                        "type": "number",
                        "minimum": 0,
                        "description": "Per-hour grid import ceiling in kWh. Zero is a valid ceiling.",
                    },
                },
            },
        ),
        _variant(
            DirectiveType.NO_OP,
            note_count=note_count,
            applies=False,
            adjustment={"type": "null"},
        ),
    ]

    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["directive_interpretation"],
        "properties": {
            "directive_interpretation": {
                "type": "array",
                "description": "Exactly one entry per operator note, in note_index order 0..N-1.",
                "minItems": note_count,
                "maxItems": note_count,
                "items": {"anyOf": variants},
            }
        },
    }


__all__ = ["SCHEMA_NAME", "build_interpretation_schema"]
