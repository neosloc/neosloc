"""Errors with a stable code and exit status.

Every failure neosloc reports on purpose is a NeoslocError. With --json the CLI
prints it as {"schema_version": 1, "error": {...}} on stdout; otherwise as one
line on stderr. Codes are part of the JSON contract (see `neosloc --schema`).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

EXIT_OK = 0
EXIT_INTERNAL = 1      # a bug: unexpected exception
EXIT_USAGE = 2         # bad command line (argparse convention)
EXIT_PATH = 3          # one or more paths could not be assessed
EXIT_EVALUATOR = 4     # LLM evaluator setup: credentials, provider, model, SDK
EXIT_INTERRUPTED = 130


class NeoslocError(Exception):
    exit_status = EXIT_INTERNAL

    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "message": self.message, "exit_status": self.exit_status,
                "details": self.details}


class UsageError(NeoslocError):
    exit_status = EXIT_USAGE


class PathError(NeoslocError):
    exit_status = EXIT_PATH


class EvaluatorError(NeoslocError):
    exit_status = EXIT_EVALUATOR


class InternalError(NeoslocError):
    exit_status = EXIT_INTERNAL
