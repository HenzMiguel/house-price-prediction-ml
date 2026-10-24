"""Structured JSON logging with safe correlation fields."""

import contextlib
import contextvars
import logging
from collections.abc import Iterator
from typing import Any

from pythonjsonlogger.json import JsonFormatter

CORRELATION_FIELDS = (
    "training_run_id",
    "mlflow_run_id",
    "model_version",
    "environment_version",
    "stage",
    "candidate_family",
    "trial_number",
    "request_id",
)

_context: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "log_context", default=None
)


class CorrelationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context = _context.get() or {}
        for field in CORRELATION_FIELDS:
            if not hasattr(record, field):
                setattr(record, field, context.get(field))
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.addFilter(CorrelationFilter())
    handler.setFormatter(
        JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s "
            + " ".join(f"%({field})s" for field in CORRELATION_FIELDS),
            rename_fields={"asctime": "timestamp", "levelname": "level"},
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())


@contextlib.contextmanager
def log_context(**values: Any) -> Iterator[None]:
    safe = {key: value for key, value in values.items() if key in CORRELATION_FIELDS}
    token = _context.set({**(_context.get() or {}), **safe})
    try:
        yield
    finally:
        _context.reset(token)
