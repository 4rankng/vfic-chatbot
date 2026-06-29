"""Structured (JSON) logging + per-request correlation id.

Emits one JSON object per record to stdout. The ``request_id`` field is populated
from the ``request_id_ctx`` context var, which ``RequestIdMiddleware`` (main.py)
sets on every request so a single user-visible failure traces cleanly across the
web process, RQ workers, and outbound Zalo calls. Dependency-free (stdlib only).
"""
import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

# Set by RequestIdMiddleware; defaults to "-" for non-request contexts (workers,
# startup) so logs always carry the field.
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


# Standard LogRecord attributes — anything else came from extra={}.
_STD_LOG_ATTRS = frozenset(logging.LogRecord("", "", "", "", 0, "", "", "").__dict__)


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_ctx.get(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Forward extra={} fields (e.g. llm_latency_ms, queue_depth).
        for key, value in record.__dict__.items():
            if key not in _STD_LOG_ATTRS and key not in payload:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # uvicorn.access is verbose and redundant with our request logging.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
