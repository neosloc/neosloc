"""Detectors, one per integrability dimension. See base.py for the protocol.

Import order defines report order and context dependencies: `interface` runs
first because it publishes specs, route files and `has_surface` into the context.
"""
from .base import DIMENSIONS
from . import interface  # noqa: F401
from . import stability  # noqa: F401
from . import events  # noqa: F401
from . import identity  # noqa: F401
from . import portability  # noqa: F401
from . import ergonomics  # noqa: F401
from . import embeddability  # noqa: F401
from . import extensibility  # noqa: F401
from . import observability  # noqa: F401
from . import legibility  # noqa: F401

__all__ = ["DIMENSIONS"]
