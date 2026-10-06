"""Detectors, one per integrability dimension. See base.py for the protocol.

Import order defines report order and context dependencies: `interface` runs
first because it publishes specs and route information into the context.
"""
from .base import DIMENSIONS, planned
from . import interface  # noqa: F401
from . import stability  # noqa: F401

planned("events", "Events (webhooks, streams, CDC)")
planned("identity", "Identity (OAuth/OIDC, scoped tokens, SCIM)")
planned("portability", "Data portability")
planned("ergonomics", "Agent ergonomics (errors, idempotency, pagination)")
from . import embeddability  # noqa: E402,F401
planned("extensibility", "Extensibility (plugins, hooks, scripting)")
planned("observability", "Observability")
from . import legibility  # noqa: E402,F401

__all__ = ["DIMENSIONS"]
