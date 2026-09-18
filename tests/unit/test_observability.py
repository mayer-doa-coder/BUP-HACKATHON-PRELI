"""Logging, metrics, and trace tests.

The highest-value checks here are the leak checks. Observability is the one subsystem whose job
is to *write things down*, so it is the most likely place for an operator note, a prompt, or a
credential to escape into a log aggregator. Those tests come first.

The rest establishes that the telemetry is actually per-request — the earlier ``_last_run``
attribute on the singleton service was shared between concurrent requests, which this phase
replaced with a context-local trace.
"""

from __future__ import annotations

import asyncio
import json
import logging

import pytest

from app.config import Settings
from app.observability import metrics
from app.observability.logging import (
    JsonLogFormatter,
    QuietThirdPartyFilter,
    bind_correlation_id,
    configure_logging,
    correlation_id_var,
    redact_model_output,
    redact_note,
)
from app.observability.metrics import Counter, Gauge, Histogram, MetricsRegistry
from app.observability.trace import clear_trace, current_trace, start_trace


def _record(**extra) -> logging.LogRecord:
    record = logging.LogRecord(
        name="gridwise.test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hello", args=(), exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


# --------------------------------------------------------------------------- no leaks


def test_a_note_is_redacted_by_default(public_cases):
    note = public_cases[0]["input"]["operator_notes"][0]
    settings = Settings(_env_file=None)

    rendered = redact_note(note, settings)

    assert note not in rendered
    assert rendered.startswith("sha256:")
    assert f"len={len(note)}" in rendered


def test_the_same_note_redacts_to_the_same_value(public_cases):
    """A stable hash is what makes repeated inputs correlatable without storing the text."""
    note = public_cases[0]["input"]["operator_notes"][0]
    settings = Settings(_env_file=None)

    assert redact_note(note, settings) == redact_note(note, settings)
    assert redact_note(note, settings) != redact_note(note + "!", settings)


def test_raw_notes_only_appear_when_explicitly_enabled(public_cases, monkeypatch):
    note = public_cases[0]["input"]["operator_notes"][0]

    monkeypatch.setenv("LOG_RAW_OPERATOR_NOTES", "true")
    assert note[:50] in redact_note(note, Settings(_env_file=None))


def test_model_output_is_redacted_by_default():
    settings = Settings(_env_file=None)
    output = '{"directive_interpretation": [{"note_index": 0}]}'

    assert output not in redact_model_output(output, settings)


def test_a_traceback_never_reaches_the_log_line():
    """A traceback can carry request content; the type and message are enough to diagnose."""
    try:
        raise ValueError("boom with sensitive detail")
    except ValueError:
        import sys

        record = _record()
        record.exc_info = sys.exc_info()
        payload = json.loads(JsonLogFormatter().format(record))

    assert payload["error_type"] == "ValueError"
    assert "Traceback" not in json.dumps(payload)
    assert "test_a_traceback_never_reaches" not in json.dumps(payload)


def test_a_request_log_line_carries_no_note_text(public_cases, caplog):
    """The end-to-end guarantee: a completed request logs statuses and counts, never content."""
    from fastapi.testclient import TestClient

    from app.api.routes import get_optimize_service
    from app.main import create_app
    from app.services.optimize_service import OptimizeService

    case = public_cases[0]
    app = create_app()
    app.dependency_overrides[get_optimize_service] = lambda: OptimizeService()
    client = TestClient(app, raise_server_exceptions=False)

    with caplog.at_level(logging.INFO):
        client.post("/optimize-energy", json=case["input"])

    logged = "\n".join(record.getMessage() + json.dumps(record.__dict__, default=str) for record in caplog.records)
    for note in case["input"]["operator_notes"]:
        assert note not in logged
    assert "api_key" not in logged.lower()


# ----------------------------------------------------------------------- json format


def test_every_line_is_json_with_the_expected_envelope():
    payload = json.loads(JsonLogFormatter().format(_record()))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "gridwise.test"
    assert payload["message"] == "hello"
    assert payload["ts"]


def test_extra_fields_are_merged_into_the_line():
    payload = json.loads(JsonLogFormatter().format(_record(http_status=422, endpoint="/x")))

    assert payload["http_status"] == 422
    assert payload["endpoint"] == "/x"


def test_the_correlation_id_comes_from_the_context_when_absent_on_the_record():
    token = correlation_id_var.set("abc123")
    try:
        payload = json.loads(JsonLogFormatter().format(_record()))
    finally:
        correlation_id_var.reset(token)

    assert payload["correlation_id"] == "abc123"


def test_non_serializable_values_do_not_break_a_log_line():
    class Weird:
        def __repr__(self):
            return "<weird>"

    payload = json.loads(JsonLogFormatter().format(_record(thing=Weird())))

    assert payload["thing"] == "<weird>"


def test_third_party_chatter_is_filtered_but_warnings_survive():
    log_filter = QuietThirdPartyFilter()

    noisy = logging.LogRecord("httpx2", logging.INFO, __file__, 1, "GET ...", (), None)
    important = logging.LogRecord("httpx2", logging.WARNING, __file__, 1, "connection lost", (), None)
    ours = logging.LogRecord("gridwise.request", logging.INFO, __file__, 1, "done", (), None)

    assert log_filter.filter(noisy) is False
    assert log_filter.filter(important) is True
    assert log_filter.filter(ours) is True


def test_configure_logging_is_idempotent():
    settings = Settings(_env_file=None)
    configure_logging(settings)
    configure_logging(settings)

    assert len(logging.getLogger().handlers) == 1


# ------------------------------------------------------------------------- metrics


def test_counter_accumulates_per_label():
    registry = MetricsRegistry()
    counter: Counter = registry.counter("thing_total", "help", ("status",))

    counter.inc(labels=("200",))
    counter.inc(2, labels=("200",))
    counter.inc(labels=("500",))

    assert counter.value(("200",)) == 3
    assert counter.value(("500",)) == 1
    assert counter.value(("404",)) == 0


def test_counter_rejects_the_wrong_number_of_labels():
    registry = MetricsRegistry()
    counter = registry.counter("thing_total", "help", ("status",))

    with pytest.raises(ValueError, match="expects 1 label"):
        counter.inc(labels=("a", "b"))


def test_gauge_goes_up_and_down():
    registry = MetricsRegistry()
    gauge: Gauge = registry.gauge("active", "help")

    gauge.inc()
    gauge.inc()
    gauge.dec()

    assert gauge.value() == 1


def test_histogram_buckets_are_cumulative():
    registry = MetricsRegistry()
    histogram: Histogram = registry.histogram("dur", "help", (), (1.0, 5.0))

    histogram.observe(0.5)
    histogram.observe(3.0)
    histogram.observe(20.0)

    rendered = "\n".join(histogram.render())
    assert 'dur_bucket{le="1"} 1' in rendered
    assert 'dur_bucket{le="5"} 2' in rendered
    assert 'dur_bucket{le="+Inf"} 3' in rendered
    assert "dur_count 3" in rendered
    assert histogram.sum() == pytest.approx(23.5)


def test_latency_buckets_straddle_the_scored_thresholds():
    """p95 <= 5 s earns full latency credit, and 4.5 s is the internal target."""
    assert 4.5 in metrics.LATENCY_BUCKETS
    assert 5.0 in metrics.LATENCY_BUCKETS
    assert 30.0 in metrics.LATENCY_BUCKETS


def test_rendered_output_is_prometheus_shaped():
    registry = MetricsRegistry()
    registry.counter("a_total", "some help", ("k",)).inc(labels=("v",))

    rendered = registry.render()

    assert "# HELP a_total some help" in rendered
    assert "# TYPE a_total counter" in rendered
    assert 'a_total{k="v"} 1' in rendered
    assert rendered.endswith("\n")


def test_label_values_are_escaped():
    registry = MetricsRegistry()
    registry.counter("a_total", "help", ("k",)).inc(labels=('has "quotes"',))

    assert '\\"quotes\\"' in registry.render()


# --------------------------------------------------------------------------- trace


def test_a_trace_is_context_local():
    """The bug this replaced: shared per-request state on a singleton service."""

    async def _one(name: str, results: dict) -> None:
        start_trace(correlation_id=name, scenario_id=name)
        await asyncio.sleep(0.01)
        trace = current_trace()
        results[name] = trace.scenario_id if trace else None
        clear_trace()

    async def _both() -> dict:
        results: dict = {}
        await asyncio.gather(_one("first", results), _one("second", results))
        return results

    results = asyncio.run(_both())

    assert results == {"first": "first", "second": "second"}


def test_trace_log_fields_drop_empty_values_but_keep_status():
    trace = start_trace(correlation_id="abc", endpoint="/optimize-energy")
    trace.http_status = 200
    trace.llm_attempts = 2
    try:
        fields = trace.as_log_fields()
    finally:
        clear_trace()

    assert fields["llm_attempts"] == 2
    assert fields["http_status"] == 200
    assert "milp_gap" not in fields, "empty diagnostics should not clutter every line"
    assert "interpretation_run" not in fields, "live objects never go into a log line"


def test_binding_a_correlation_id_is_visible_to_later_logs():
    bind_correlation_id("xyz")
    try:
        payload = json.loads(JsonLogFormatter().format(_record()))
    finally:
        correlation_id_var.set("")

    assert payload["correlation_id"] == "xyz"
