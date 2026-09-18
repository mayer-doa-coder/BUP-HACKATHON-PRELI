"""Typed application configuration.

Every knob the service has lives here, loaded from the environment (or a local ``.env``).
Secrets are held as ``SecretStr`` so they cannot be printed or logged by accident.

Keys mirror ``.env.example``. The provisional spec-gap policies (cross-midnight, ``through``
wording, overlapping solar factors) are configuration, not canonical rules — if the organizers
clarify one, only the value here and the policy module change.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class CrossMidnightPolicy(StrEnum):
    """How to expand a window whose end hour is not after its start hour."""

    MODULO_24 = "modulo_24_provisional"
    REJECT = "reject"


class ThroughRangePolicy(StrEnum):
    """How to read the word "through" in a time range."""

    END_EXCLUSIVE = "end_exclusive_provisional"
    END_INCLUSIVE = "end_inclusive"


class SolarOverlapPolicy(StrEnum):
    """How two differing solar factors on the same hour compose."""

    MIN_FACTOR = "min_factor_provisional"
    MULTIPLY = "multiply"
    LAST_WINS = "last_wins"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------ service
    app_env: str = "production"
    host: str = "0.0.0.0"  # noqa: S104 - the judge must reach this service from outside the container
    port: int = 8000

    # ---------------------------------------------------------------------- llm
    llm_provider: str = "openai"
    llm_model: str = ""
    llm_api_key: SecretStr = SecretStr("")
    # Blank means "use the provider adapter's own default host"; set it for a gateway or proxy.
    llm_base_url: str = ""
    llm_attempt_timeout_seconds: float = 3.2
    llm_max_attempts: int = 2
    llm_max_output_tokens: int = 2048
    # None omits the parameter entirely, for models that reject an explicit temperature.
    llm_temperature: float | None = 0.0
    prompt_version: str = "gridwise-parser-v1"
    schema_version: str = "gridwise-directives-v1"

    backup_llm_provider: str = ""
    backup_llm_model: str = ""
    backup_llm_api_key: SecretStr = SecretStr("")
    backup_llm_base_url: str = ""

    # ----------------------------------------------------------------- budgets
    # Soft budget is the full-credit performance target; the hard deadline only exists so
    # exceptional fallbacks terminate before the organizer's 30 s timeout.
    soft_response_budget_seconds: float = 4.5
    hard_request_deadline_seconds: float = 28.0

    # ------------------------------------------------------------------- cache
    request_cache_size: int = 512
    request_cache_ttl_seconds: int = 1800

    # -------------------------------------------------- resource protection
    max_request_body_bytes: int = 131_072
    max_note_chars: int = 16_384
    max_concurrent_requests: int = 32
    max_concurrent_llm_calls: int = 16
    # O-05: oversized bodies/notes get a controlled 413 by default; 400 is the documented alternative.
    oversized_request_status: int = 413

    # --------------------------------------------------------------- optimizer
    optimizer_mode: str = "lp_milp_hybrid"
    lp_solver_method: str = "highs"
    milp_solver: str = "highs"
    milp_time_limit_seconds: float = 3.0
    # HiGHS defaults to a 1e-4 relative MIP gap, which stops at a *provably near-optimal*
    # solution and still reports success. Optimization credit is min(1, optimal/team_cost), so
    # a needless 0.01% gap is a needless score loss — and it would make "proven optimal" false.
    # Solve to exact optimality; the model is small enough that this costs nothing.
    milp_relative_gap: float = 0.0
    internal_tolerance: float = 1e-7
    judge_tolerance: float = 0.01
    optimizer_version: str = "lp-milp-v1"
    # Guide §14/§37: serialize with enough precision that the replayed response still balances.
    response_decimal_places: int = 6
    # Magnitude below which a solver value is treated as a floating-point artifact, not a real amount.
    solver_epsilon: float = 1e-9

    # ------------------------------------------- provisional spec-gap policies
    cross_midnight_policy: CrossMidnightPolicy = CrossMidnightPolicy.MODULO_24
    through_range_policy: ThroughRangePolicy = ThroughRangePolicy.END_EXCLUSIVE
    solar_overlap_policy: SolarOverlapPolicy = SolarOverlapPolicy.MIN_FACTOR
    # O-06: negative demand/solar is treated as semantically invalid. Tariff is deliberately
    # unrestricted — the canonical request schema never forbids a negative tariff.
    reject_negative_energy_inputs: bool = True

    # ------------------------------------------------------------ diagnostics
    app_commit_sha: str = ""
    # Operational metrics on /metrics. Separate router, never part of the judged contract.
    metrics_enabled: bool = True
    judge_mode: bool = True
    demo_mode: bool = False
    log_level: str = "INFO"
    log_raw_operator_notes: bool = False
    log_llm_raw_output: bool = False

    @field_validator("llm_temperature", mode="before")
    @classmethod
    def _optional_temperature(cls, value: object) -> object:
        """Treat a blank value as "omit the parameter".

        ``.env`` files have no way to express ``None``; an unset key is an empty string. Without
        this, the documented way to disable an explicit temperature — leaving it blank — would
        fail validation and the service would refuse to start. That matters because several
        current models reject any explicit temperature and accept only their default, so blanking
        this is the fix for a real provider 400.
        """
        if isinstance(value, str) and value.strip().lower() in ("", "none", "null", "default"):
            return None
        return value

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        if level not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}")
        return level

    @property
    def parser_cache_version(self) -> str:
        """Version fragment that must take part in every parser cache key."""
        return f"{self.prompt_version}|{self.schema_version}|{self.llm_provider}|{self.llm_model}"

    @property
    def response_cache_version(self) -> str:
        """Version fragment that must take part in every full-response cache key."""
        return f"{self.parser_cache_version}|{self.optimizer_version}|{self.app_commit_sha}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton.

    Cached so that configuration is read once at startup rather than per request.
    Tests that need different values should call ``get_settings.cache_clear()``.
    """
    return Settings()


__all__ = [
    "CrossMidnightPolicy",
    "Settings",
    "SolarOverlapPolicy",
    "ThroughRangePolicy",
    "get_settings",
]
