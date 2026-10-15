"""Time-aware compliance control versioning."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from .canonical import isoformat, object_hash


@dataclass(frozen=True, slots=True)
class ControlVersion:
    control_id: str
    framework: str
    version: str
    title: str
    requirements: tuple[str, ...]
    effective_from: datetime
    effective_until: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.effective_from.tzinfo is None:
            raise ValueError("effective_from must be timezone-aware")
        if self.effective_until and self.effective_until <= self.effective_from:
            raise ValueError("effective_until must be later than effective_from")

    def applies_at(self, moment: datetime) -> bool:
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return self.effective_from <= moment and (self.effective_until is None or moment < self.effective_until)

    def as_dict(self) -> dict[str, Any]:
        return {
            "control_id": self.control_id,
            "framework": self.framework,
            "version": self.version,
            "title": self.title,
            "requirements": list(self.requirements),
            "effective_from": isoformat(self.effective_from),
            "effective_until": isoformat(self.effective_until) if self.effective_until else None,
            "metadata": self.metadata,
        }

    @property
    def snapshot_hash(self) -> str:
        return object_hash(self.as_dict())


class ControlRegistry:
    def __init__(self, controls: Iterable[ControlVersion] = ()) -> None:
        self._versions: dict[str, list[ControlVersion]] = {}
        for control in controls:
            self.register(control)

    def register(self, control: ControlVersion) -> None:
        versions = self._versions.setdefault(control.control_id, [])
        if any(item.version == control.version for item in versions):
            raise ValueError(f"Duplicate control version {control.control_id}@{control.version}")
        if any(
            item.effective_from < (control.effective_until or datetime.max.replace(tzinfo=timezone.utc))
            and control.effective_from < (item.effective_until or datetime.max.replace(tzinfo=timezone.utc))
            for item in versions
        ):
            raise ValueError(f"Overlapping effective range for {control.control_id}")
        versions.append(control)
        versions.sort(key=lambda item: item.effective_from)

    def resolve(self, control_id: str, moment: datetime) -> ControlVersion:
        matches = [item for item in self._versions.get(control_id, ()) if item.applies_at(moment)]
        if len(matches) != 1:
            raise KeyError(f"No unambiguous version for {control_id} at {isoformat(moment)}")
        return matches[0]

    def snapshot(self, control_ids: Iterable[str], moment: datetime) -> list[ControlVersion]:
        return [self.resolve(control_id, moment) for control_id in sorted(set(control_ids))]

    def all(self) -> list[ControlVersion]:
        return [item for versions in self._versions.values() for item in versions]
