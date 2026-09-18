"""Per-request time budget.

Retries are only worth attempting while there is time to use the result. The organizer's hard
limit is 30 s, so the internal deadline sits below it: a fallback that finishes at 31 s has
produced a failed request, not a slow one.

Uses a monotonic clock, so a system clock adjustment mid-request cannot make the budget jump.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Deadline:
    """Remaining time for one request."""

    limit_seconds: float
    started_at: float = field(default_factory=time.monotonic)

    @classmethod
    def start(cls, limit_seconds: float) -> Deadline:
        return cls(limit_seconds=limit_seconds)

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    def remaining(self) -> float:
        return max(0.0, self.limit_seconds - self.elapsed)

    def expired(self) -> bool:
        return self.remaining() <= 0.0

    def allows(self, needed_seconds: float) -> bool:
        """Whether an operation expected to take ``needed_seconds`` still fits."""
        return self.remaining() > needed_seconds

    def timeout_for(self, preferred_seconds: float) -> float:
        """The attempt timeout to use: the preferred one, capped by what is left."""
        return max(0.0, min(preferred_seconds, self.remaining()))


__all__ = ["Deadline"]
