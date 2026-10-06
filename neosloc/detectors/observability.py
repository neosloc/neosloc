"""Dimension 9 - Observability.

Can an operator or orchestrating agent tell whether it is working, and why
not? Health/readiness probes, metrics, tracing, structured logs, error tracking.
"""
from __future__ import annotations

from ..model import DimensionResult
from .base import Context, register
from .signals import Signal, level_from, score_signals

SIGNALS = [
    Signal("health-endpoint", "code", r"""['"`]/(health|healthz|healthcheck|ready|readyz|livez|ping|status)\b""", 1.0,
           "Expose /health and /ready endpoints for orchestrators.", group="health"),
    Signal("docker-healthcheck", "config", r"^HEALTHCHECK\b|healthcheck:|livenessProbe|readinessProbe", 0.5,
           group="health"),
    Signal("metrics", "code+deps",
           r"prometheus|/metrics\b|statsd|micrometer|opentelemetry.*metric|metrics\.NewCounter|prom-client|"
           r"django-prometheus|starlette_exporter", 1.0,
           "Export metrics (Prometheus/OpenTelemetry)."),
    Signal("tracing", "code+deps", r"opentelemetry|@opentelemetry/|go\.opentelemetry\.io|jaeger|zipkin|ddtrace|newrelic|elastic-apm",
           1.0, "Instrument with OpenTelemetry tracing so cross-system calls can be followed."),
    Signal("structured-logs", "code+deps",
           r"structlog|python-json-logger|jsonlogger|loguru|\bpino\b|winston|go\.uber\.org/zap|zerolog|"
           r"logrus|slog\.New(JSON)?Handler|logstash|json_log", 0.5,
           "Log as structured JSON so logs can be queried by machines."),
    Signal("error-tracking", "code+deps", r"sentry|rollbar|bugsnag|honeybadger|airbrake", 0.5),
]
WHY = {
    0: "A black box: no health signal, metrics or traces.",
    1: "Something can tell whether it is up.",
    2: "Health plus one of metrics, tracing or structured logs.",
    3: "Health, metrics and structured diagnostics.",
    4: "Health, metrics, distributed tracing and structured logs.",
}


@register("observability", "Observability")
def detect(repo, ctx: Context) -> DimensionResult:
    score, ev, found, gaps = score_signals(repo, ctx, SIGNALS)
    level = level_from(score, (0.5, 1.5, 2.5, 3.5))
    return DimensionResult("observability", "Observability", level, WHY[level], ev,
                           metrics={"score": round(score, 2), "signals": sorted(found)},
                           gaps=gaps if level < 4 else [])
