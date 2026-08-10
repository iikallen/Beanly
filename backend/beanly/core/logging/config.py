import json
import logging
import logging.config
import re
from datetime import UTC, datetime
from typing import Any

from beanly.core.config.settings import get_settings
from beanly.core.logging.context import (
    organization_id_var,
    request_id_var,
    user_id_var,
)

_SECRET_PATTERN = re.compile(
    r"(?i)(authorization|password|token|secret|credentials|signature)"
    r"([\s\"'=:\\]+)([^\s,;}]+)"
)
_BEARER_PATTERN = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+")
_SAFE_EXTRA_FIELDS = {
    "action",
    "connection_id",
    "duration_ms",
    "error_type",
    "event_id",
    "event_name",
    "inbox_id",
    "job_id",
    "order_id",
    "provider_code",
    "status",
    "worker_id",
}


def _redact(value: str) -> str:
    value = _BEARER_PATTERN.sub("Bearer [REDACTED]", value)
    return _SECRET_PATTERN.sub(r"\1\2[REDACTED]", value)


class JsonFormatter(logging.Formatter):
    def __init__(self, service_name: str) -> None:
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "service": self.service_name,
            "logger": record.name,
            "request_id": request_id_var.get(),
            "organization_id": organization_id_var.get(),
            "user_id": user_id_var.get(),
            "message": _redact(record.getMessage()),
        }
        for name in _SAFE_EXTRA_FIELDS:
            value = getattr(record, name, None)
            if value is not None:
                payload[name] = value
        if record.exc_info:
            payload["exception"] = _redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging(service_name: str | None = None) -> None:
    settings = get_settings()
    formatter: dict[str, Any]
    if settings.environment in {"staging", "production"}:
        formatter = {
            "()": "beanly.core.logging.config.JsonFormatter",
            "service_name": service_name or settings.service_name,
        }
    else:
        formatter = {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": formatter,
            },
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                }
            },
            "root": {"handlers": ["default"], "level": "INFO"},
        }
    )
