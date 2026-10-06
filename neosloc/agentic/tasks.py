"""The standard integration task suite.

Tasks are deliberately generic: they ask for what any integrator of any
system needs, so success rates are comparable across projects. Each names
the static dimension it probes, so measured and inferred scores can be
compared side by side.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class Task:
    key: str
    dimension: str
    prompt: str


TASKS: List[Task] = [
    Task("auth", "identity",
         "Find out how another program authenticates to this system to call it programmatically. "
         "Give the concrete mechanism: header names, token type, where tokens or keys come from, "
         "and the environment variables or settings involved."),
    Task("list", "interface",
         "Retrieve a list of the system's primary resource (the main kind of entity it manages) "
         "from another program. Give the exact call."),
    Task("create", "interface",
         "Create a new instance of the system's primary resource from another program. Give the "
         "exact call including the required fields."),
    Task("subscribe", "events",
         "Get notified from another program when the system's data changes, without polling if "
         "possible. Give the exact mechanism (webhook registration, stream endpoint, broker topic) "
         "or the best polling call if nothing else exists."),
    Task("export", "portability",
         "Export all of the system's data in bulk, in a machine-readable format. Give the exact "
         "call or command."),
    Task("run", "embeddability",
         "Start the system non-interactively in a fresh environment with a custom configuration "
         "value changed (for example the port, database location or log level). Give the exact "
         "commands and the configuration names."),
    Task("errors", "ergonomics",
         "Determine how the system reports a validation error to a programmatic caller, so the "
         "caller can handle it. Give the call that triggers one and the shape of the error."),
    Task("extend", "extensibility",
         "Add custom behaviour to the system without modifying its source (plugin, hook, "
         "middleware, script). Give the exact extension point and how it is registered."),
]


def select(keys: Optional[List[str]]) -> List[Task]:
    if not keys:
        return list(TASKS)
    by_key = {t.key: t for t in TASKS}
    unknown = [k for k in keys if k not in by_key]
    if unknown:
        raise ValueError("unknown task(s): %s (choose from %s)"
                         % (", ".join(unknown), ", ".join(by_key)))
    return [by_key[k] for k in keys]
