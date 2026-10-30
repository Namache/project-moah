from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, field_serializer


def clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class UtcModel(BaseModel):
    """Serializes every datetime field as an ISO 8601 UTC string ending in Z."""

    @field_serializer("*", when_used="json")
    def _serialize_datetimes(self, value: Any) -> Any:
        return utc_iso(value) if isinstance(value, datetime) else value
