"""Dimension 8 - Extensibility.

Can behaviour be added without forking? Plugin discovery, hook/event APIs,
middleware, scripting, and documentation of the extension points.
"""
from __future__ import annotations

from ..model import DimensionResult
from .base import Context, register
from .signals import Signal, level_from, score_signals

SIGNALS = [
    Signal("plugin-discovery", "code",
           r"entry_points\(\s*(group\s*=|\))|iter_entry_points|pluggy\.PluginManager|stevedore|ServiceLoader\.load|"
           r"registerPlugin|addPlugin|plugin\.Open\(|PluginManager\(|register_plugin|load_plugins?\(", 1.5,
           "Add a plugin mechanism (entry points, registry) so features can ship outside the core.",
           group="plugins"),
    Signal("plugin-entry-points", "deps", r"\[project\.entry-points\.|\[tool\.poetry\.plugins|\bpluggy\b|\bstevedore\b",
           1.5, group="plugins"),
    Signal("hooks", "code",
           r"\bhookimpl\b|\bhookspec\b|add_action\(|add_filter\(|apply_filters\(|Signal\(\)|\.connect\(|"
           r"\bon\(['\"]|EventEmitter|register_hook|addHook|\bhooks?\s*[=:]\s*[\[{]", 1.0,
           "Expose hooks/events at key lifecycle points."),
    Signal("plugins-dir", "path", r"(^|/)(plugins?|extensions?|addons?|contrib)/", 0.5),
    Signal("dynamic-loading", "code", r"importlib\.import_module|__import__\(|require\(\s*[a-zA-Z_]|import\(\s*[a-zA-Z_`]",
           0.25),
    Signal("middleware", "code", r"middleware", 0.25),
    Signal("scripting", "code+deps", r"\b(lupa|lua|starlark|jsonlogic|json-logic|expr-eval|cel-go|celpy|rhai|wasmtime|extism)\b",
           0.5),
    Signal("extension-docs", "docs", r"\b(write|writing|create|creating|build|building)\s+(a\s+)?(plugin|extension|hook)", 0.5,
           "Document how to write an extension."),
]
WHY = {
    0: "Changing behaviour means changing (forking) the code.",
    1: "Some internal seams exist but are not meant for third parties.",
    2: "Hooks or a plugin mechanism exist.",
    3: "A plugin mechanism plus hooks; extensions can ship separately.",
    4: "A documented extension model: discovery, hooks and scripting.",
}


@register("extensibility", "Extensibility")
def detect(repo, ctx: Context) -> DimensionResult:
    score, ev, found, gaps = score_signals(repo, ctx, SIGNALS)
    level = level_from(score, (0.5, 1.25, 2.5, 3.5))
    return DimensionResult("extensibility", "Extensibility", level, WHY[level], ev,
                           metrics={"score": round(score, 2), "signals": sorted(found)},
                           gaps=gaps if level < 4 else [])
