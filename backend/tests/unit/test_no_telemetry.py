"""SAMADCON sends no telemetry, and FastAPI is told so.

FastAPI 0.142 added native OpenTelemetry and depends on opentelemetry-api.
By default it traces, meters and logs every request, and before start-up it
configures OTLP export on its own when an OTEL_EXPORTER_OTLP_*_ENDPOINT
variable is set and the SDK is installed. The image has no SDK, so nothing
would leave it today. This is a console whose requests run with a domain
administrator's ticket: whether its requests are recorded somewhere else is
not left to which packages happen to be installed or which variables happen
to be set.
"""

from __future__ import annotations

from samadcon.main import app


def test_every_part_of_fastapi_telemetry_is_off():
    # Private, because FastAPI exposes the setting only as the constructor
    # argument; the test is what notices if that changes.
    config = app._telemetry
    assert config["auto_configure"] is False
    assert config["tracing"] is False
    assert config["metrics"] is False
    assert config["logs"] is False


def test_so_requests_are_not_wrapped_at_all():
    assert app._native_telemetry.enabled() is False
