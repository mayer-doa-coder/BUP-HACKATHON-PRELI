"""GridWise — LLM-assisted smart campus energy optimizer.

The LLM only translates operator notes into a closed set of typed directives.
Deterministic guardrails validate them, the LP-assisted MILP optimizer produces every
kWh number, and an independent replay validator proves the schedule before it is returned.
"""

__version__ = "0.1.0"
