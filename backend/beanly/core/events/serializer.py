from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID


class EventSerializationError(ValueError):
    pass


def serialize_event_payload(event: object) -> dict[str, object]:
    if isinstance(event, type) or not is_dataclass(event):
        raise EventSerializationError("Domain event must be a dataclass instance")
    return {field.name: _serialize(getattr(event, field.name)) for field in fields(event)}


def _serialize(value: object) -> object:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise EventSerializationError("Decimal event values must be finite")
        return str(value)
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise EventSerializationError("Datetime event values must include a timezone")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise EventSerializationError("Event payload object keys must be strings")
        return {key: _serialize(item) for key, item in value.items()}
    raise EventSerializationError(
        f"Unsupported event payload value: {type(value).__name__}"
    )
