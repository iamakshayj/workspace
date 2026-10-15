"""Canonical evidence domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from .canonical import isoformat, object_hash, utc_now


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    source: str
    kind: str
    observed_at: datetime
    payload: dict[str, Any]
    evidence_id: str = field(default_factory=lambda: str(uuid4()))
    collected_at: datetime = field(default_factory=utc_now)
    control_ids: tuple[str, ...] = ()
    parent_ids: tuple[str, ...] = ()
    document_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.evidence_id or not self.source or not self.kind:
            raise ValueError("evidence_id, source, and kind are required")
        if self.observed_at.tzinfo is None or self.collected_at.tzinfo is None:
            raise ValueError("Evidence timestamps must be timezone-aware")

    def as_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source": self.source,
            "kind": self.kind,
            "observed_at": isoformat(self.observed_at),
            "collected_at": isoformat(self.collected_at),
            "control_ids": sorted(set(self.control_ids)),
            "parent_ids": sorted(set(self.parent_ids)),
            "document_ref": self.document_ref,
            "payload": self.payload,
            "metadata": self.metadata,
        }

    @property
    def content_hash(self) -> str:
        return object_hash(self.as_dict())
