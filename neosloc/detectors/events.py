# neosloc: ignore (detection vocabulary, not usage)
"""Dimension 3 - Events.

Can other systems react to what happens here without polling? Signals:
webhooks (ideally signed and self-service), streaming endpoints, message
brokers, change-data-capture, and an AsyncAPI/CloudEvents contract.
"""
from __future__ import annotations

from ..model import DimensionResult
from .base import Context, register
from .signals import Signal, level_from, score_signals

SIGNALS = [
    # Outbound: this system tells others. Receiving other platforms' webhooks
    # is consuming events, worth much less here.
    Signal("webhooks", "code",
           r"(send|deliver|dispatch|fire|trigger|emit|post|notify)_?\w*webhook|webhook\w*(subscription|endpoint|delivery|deliveries|sender|dispatcher)"
           r"|Webhook(Endpoint|Subscription|Delivery)|class\s+\w*Webhook\w*\(.*Model", 1.0,
           "Offer outbound webhooks so consumers are told about changes."),
    Signal("inbound-webhooks", "code", r"webhook", 0.25),
    Signal("signed-webhooks", "code",
           r"X-Hub-Signature|X-Signature|Webhook-Signature|hmac\.new\(|createHmac\(|hmac\.New\(", 0.5),
    Signal("webhook-registration-api", "routes", r"""['"`][^'"`]*webhook""", 0.5,
           "Let integrators register webhooks via the API, not only via the UI."),
    Signal("sse", "code", r"text/event-stream|EventSourceResponse|EventSource\(|ServerSentEvent", 0.75,
           group="stream"),
    Signal("websocket", "code", r"websocket|socket\.io|\bwss?://|@WebSocketGateway|channels\.generic",
           0.75, group="stream"),
    Signal("message-broker", "code+deps",
           r"\b(kafka|kafkajs|confluent[-_]kafka|aiokafka|pika|amqp|amqplib|rabbitmq|nats|"
           r"paho[-_]mqtt|mqtt|google-cloud-pubsub|@google-cloud/pubsub|aws-sdk.*sns|boto3|redis.*pubsub|"
           r"\.publish\(|celery|bullmq|sidekiq|resque)\b", 0.75,
           "Publish domain events to a broker so consumers can subscribe."),
    Signal("cdc-outbox", "code+deps", r"debezium|outbox|pg_notify|LISTEN\s+\w+|change_stream|\.watch\(\s*\[|wal2json",
           0.5),
    Signal("asyncapi", "path", r"(^|/)asyncapi[\w.-]*\.(ya?ml|json)$", 1.0,
           "Describe events with AsyncAPI (or CloudEvents) so they are a contract."),
    Signal("cloudevents", "code+deps", r"cloudevents|ce-specversion|\"specversion\"", 0.5),
]
WHY = {
    0: "No way to be notified of changes; consumers must poll or scrape.",
    1: "Some event mechanism exists, but it is internal or ad hoc.",
    2: "Events are available (webhooks or streams) without a contract.",
    3: "Events are delivered through more than one mechanism or are signed and self-service.",
    4: "Events are a documented contract (AsyncAPI/CloudEvents) with robust delivery.",
}


@register("events", "Events")
def detect(repo, ctx: Context) -> DimensionResult:
    score, ev, found, gaps = score_signals(repo, ctx, SIGNALS)
    if "webhooks" not in found:
        # Signatures and registration only count for webhooks this system sends.
        score -= sum(s.points for s in SIGNALS
                     if s.name in ("signed-webhooks", "webhook-registration-api") and s.name in found)
    level = level_from(score, (0.5, 1.0, 2.0, 3.0))
    if "asyncapi" not in found and "cloudevents" not in found:
        level = min(level, 3)
    return DimensionResult("events", "Events", level, WHY[level], ev,
                           metrics={"score": round(score, 2), "signals": sorted(found)},
                           gaps=gaps if level < 4 else [])
