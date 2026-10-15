"""Shared connector contract and parsing helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Iterable

from evidence_core.models import EvidenceRecord
from evidence_core.canonical import object_hash


def first(value: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        if key in value and value[key] not in (None, ""):
            return value[key]
    return default


def parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc)
    if not value:
        raise ValueError("A source event must include an observed timestamp")
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def stable_id(source: str, item: dict[str, Any], *keys: str) -> str:
    supplied = first(item, *keys, default="")
    return str(supplied) if supplied not in (None, "") else f"{source}-{object_hash(item)[:24]}"


class Connector(ABC):
    source: str

    @abstractmethod
    def normalize(self, item: dict[str, Any]) -> EvidenceRecord:
        """Convert one source object into a canonical evidence record."""

    def normalize_many(self, items: Iterable[dict[str, Any]]) -> list[EvidenceRecord]:
        return [self.normalize(item) for item in items]
