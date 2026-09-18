"""Provisional policies for specification gaps.

Four things the canonical documents do not define. Each is an **engineering fallback, not an
organizer rule**, and every one is isolated here behind a configuration flag so that an
organizer clarification is a one-value change plus a test update (D-12, PRD §20.2):

1. cross-midnight windows (``11 PM to 2 AM``)
2. the word ``through`` in a range
3. single-hour phrasing (``during the 4 PM hour``)
4. two differing ``solar_reduction`` factors on the same hour

Consumers: :func:`compose_solar_factors` is used by the directive compiler;
:func:`expand_window` is the single deterministic statement of the window convention, used to
generate the interpreter's prompt rules (P8) and by the demo's paraphrase lab (P18).
``expand_window`` never replaces the LLM — it operates on endpoints that have *already* been
understood, and says nothing about how "one until three" became ``(13, 15)``.
"""

from __future__ import annotations

import math

from app.config import CrossMidnightPolicy, Settings, SolarOverlapPolicy, ThroughRangePolicy, get_settings
from app.schemas.request import HOURS_IN_DAY

# Two factors within this distance are treated as the same value rather than as an overlap.
FACTOR_EQUALITY_TOLERANCE = 1e-12

OVERLAPPING_SOLAR_FACTOR_FLAG = "overlapping_solar_factor"


def compose_solar_factors(
    existing: float | None,
    incoming: float,
    settings: Settings | None = None,
) -> tuple[float, bool]:
    """Combine two solar factors that land on the same hour.

    Returns ``(factor, was_ambiguous)``. Ambiguity means two *different* factors overlapped,
    which is the undefined case; identical factors overlapping is not ambiguous.

    The default policy keeps the smaller remaining fraction, because assuming more solar than
    one of the directives allows could produce a plan that the judge replays as invalid.
    Validity outranks cost.
    """
    settings = settings or get_settings()

    if existing is None:
        return incoming, False
    if math.isclose(existing, incoming, rel_tol=0.0, abs_tol=FACTOR_EQUALITY_TOLERANCE):
        return existing, False

    policy = settings.solar_overlap_policy
    if policy is SolarOverlapPolicy.MULTIPLY:
        return existing * incoming, True
    if policy is SolarOverlapPolicy.LAST_WINS:
        return incoming, True
    return min(existing, incoming), True


def expand_window(
    start_hour: int,
    end_hour: int,
    *,
    inclusive_end: bool = False,
    settings: Settings | None = None,
) -> list[int]:
    """Expand an already-understood ``[start, end)`` window into canonical hours.

    Start-inclusive and end-exclusive per Problem Statement §05.1, so ``(13, 15)`` is
    ``[13, 14]``. ``end_hour`` of 24 means "to the end of the day". When the end does not come
    after the start the window is read as crossing midnight, under the configured provisional
    policy, and is still serialized in ascending order: ``(23, 2)`` becomes ``[0, 1, 23]``.

    ``inclusive_end=True`` is only for wording the ``through`` policy marks as inclusive; it is
    never the default.
    """
    settings = settings or get_settings()

    if not 0 <= start_hour <= HOURS_IN_DAY - 1:
        raise ValueError(f"start_hour {start_hour} is outside 0..23")
    if not 0 <= end_hour <= HOURS_IN_DAY:
        raise ValueError(f"end_hour {end_hour} is outside 0..24")

    if inclusive_end:
        end_hour = min(end_hour + 1, HOURS_IN_DAY)

    # "To the end of the day" (end_hour == 24) needs no branch of its own: start_hour is at most
    # 23, so it is always covered by the ordinary forward case above.
    if end_hour > start_hour:
        return list(range(start_hour, end_hour))
    if end_hour == start_hour:
        # A degenerate window: no hour lies strictly inside it.
        return []
    if settings.cross_midnight_policy is CrossMidnightPolicy.REJECT:
        raise ValueError(f"cross-midnight window {start_hour}->{end_hour} is rejected by policy")
    return sorted(set(range(start_hour, HOURS_IN_DAY)) | set(range(0, end_hour)))


def through_is_end_exclusive(settings: Settings | None = None) -> bool:
    """Whether ``through`` excludes its stated end hour under the current policy."""
    settings = settings or get_settings()
    return settings.through_range_policy is ThroughRangePolicy.END_EXCLUSIVE


def single_hour_window(hour: int) -> list[int]:
    """``during the 4 PM hour`` -> ``[16]``.

    An hour label names one whole interval. Provisional: reasonable, but not stated by the
    canonical documents.
    """
    if not 0 <= hour <= HOURS_IN_DAY - 1:
        raise ValueError(f"hour {hour} is outside 0..23")
    return [hour]


def policy_summary(settings: Settings | None = None) -> dict[str, str]:
    """The active provisional policies, for the README, diagnostics, and the demo layer.

    Never part of the judge response — these are engineering choices and must be presented as
    provisional rather than canonical.
    """
    settings = settings or get_settings()
    return {
        "cross_midnight": settings.cross_midnight_policy.value,
        "through_range": settings.through_range_policy.value,
        "solar_overlap": settings.solar_overlap_policy.value,
        "single_hour_phrase": "one_whole_interval_provisional",
    }


__all__ = [
    "FACTOR_EQUALITY_TOLERANCE",
    "OVERLAPPING_SOLAR_FACTOR_FLAG",
    "compose_solar_factors",
    "expand_window",
    "policy_summary",
    "single_hour_window",
    "through_is_end_exclusive",
]
