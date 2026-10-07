"""Diagnostics go to stderr through the `neosloc` logger; reports go to stdout.

Levels: errors (fatal), warnings (degraded results), info (progress of LLM
evaluators), debug (per-detector timings, file and git details).
"""
from __future__ import annotations

import json
import logging
import sys
import time
from typing import Optional, TextIO

logger = logging.getLogger("neosloc")

LEVELS = {"debug": logging.DEBUG, "info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}


class JsonFormatter(logging.Formatter):
    """One JSON object per line: ts, level, logger, message, plus any `extra` fields."""

    RESERVED = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime"}

    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + "Z",
               "level": record.levelname.lower(), "logger": record.name, "message": record.getMessage()}
        for k, v in vars(record).items():
            if k not in self.RESERVED and not k.startswith("_"):
                out[k if k not in out else "extra_" + k] = v  # never overwrite ts/level/logger/message
        if record.exc_info:
            out["exception"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def configure(level: str = "info", fmt: str = "text", stream: Optional[TextIO] = None) -> None:
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter() if fmt == "json" else logging.Formatter("neosloc: %(message)s"))
    logger.handlers[:] = [handler]
    logger.setLevel(LEVELS[level])
    logger.propagate = False
