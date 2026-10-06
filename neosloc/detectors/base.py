"""Detector protocol and registry, kept apart from detectors/__init__ so the
detector modules don't import the package that imports them."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple

from ..model import DimensionResult
from ..repo import Repo

Context = Dict[str, Any]
Detector = Callable[[Repo, Context], DimensionResult]

# (key, title, detector or None while not implemented). Order is report order.
DIMENSIONS: List[Tuple[str, str, Any]] = []


def register(key: str, title: str):
    def deco(fn: Detector) -> Detector:
        DIMENSIONS.append((key, title, fn))
        return fn
    return deco


def planned(key: str, title: str) -> None:
    DIMENSIONS.append((key, title, None))
