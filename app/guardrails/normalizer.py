"""The only normalizations a guardrail is allowed to perform.

Deliberately narrow (Guide §9). Each one below either preserves the meaning of the model's
output exactly or touches a field with no semantic content at all:

* **sorting entries by note_index** — the mapping is carried by ``note_index``, not by list
  position, so reordering cannot change which note an entry describes;
* **sorting an already-unique hour set** — a window is a *set* of hours, so ordering carries no
  information; the canonical form simply has to be ascending;
* **normalizing -0.0** — a float artifact, identical in value to 0.0;
* **explanation text** — free text the judge explicitly does not match byte for byte.

What is *not* here matters more: no deduplicating hours, no clipping a factor into range, no
coercing an unknown directive type, no inventing a missing value. Those are semantic repairs
and belong to the model, not to deterministic code.
"""

from __future__ import annotations

from typing import Any

MAX_EXPLANATION_CHARS = 500


def sort_entries_by_note_index(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    """Order entries by ``note_index``, but only when every index is a unique integer.

    With a duplicate or non-integer index, sorting would silently paper over a mapping failure
    that the validator needs to see, so the list is returned untouched.
    """
    indices = [item.get("note_index") for item in items]
    if not all(isinstance(index, int) and not isinstance(index, bool) for index in indices):
        return items, False
    if len(set(indices)) != len(indices):
        return items, False

    ordered = sorted(items, key=lambda item: item["note_index"])
    return ordered, ordered != items


def sort_hours(hours: list[int]) -> tuple[list[int], bool]:
    """Sort an hour set that is already unique. Duplicates are left for the validator to reject."""
    if len(set(hours)) != len(hours):
        return hours, False
    ordered = sorted(hours)
    return ordered, ordered != hours


def normalize_negative_zero(value: float) -> float:
    """Turn ``-0.0`` into ``0.0``. Same number, canonical spelling."""
    return 0.0 if value == 0 else value


def normalize_explanation(value: Any) -> tuple[str, bool]:
    """Trim the explanation, and tolerate a missing or non-string one.

    A documented, deliberate extension of the four safe normalizations. ``explanation`` is free
    text that the rubric states is *not* matched byte for byte, so it carries no score. Failing
    an entire case — and spending a repair round trip — because a model emitted a number here
    would trade real points for nothing.
    """
    if value is None:
        return "", True
    if isinstance(value, str):
        trimmed = value.strip()[:MAX_EXPLANATION_CHARS]
        return trimmed, trimmed != value
    return str(value).strip()[:MAX_EXPLANATION_CHARS], True


__all__ = [
    "MAX_EXPLANATION_CHARS",
    "normalize_explanation",
    "normalize_negative_zero",
    "sort_entries_by_note_index",
    "sort_hours",
]
