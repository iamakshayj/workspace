"""Append-only impact metric ledger with a tamper-evident hash chain."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from .canonical import canonical_json, isoformat, object_hash, utc_now


class ImpactLedger:
    GENESIS = "0" * 64

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def append(self, metric: str, value: int | float, source: str, evidence_url: str = "", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        existing = self.entries()
        previous_hash = existing[-1]["entry_hash"] if existing else self.GENESIS
        entry = {
            "entry_id": str(uuid4()),
            "recorded_at": isoformat(utc_now()),
            "metric": metric,
            "value": value,
            "source": source,
            "evidence_url": evidence_url,
            "metadata": metadata or {},
            "previous_hash": previous_hash,
        }
        entry["entry_hash"] = object_hash(entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("ab") as handle:
            handle.write(canonical_json(entry) + b"\n")
        return entry

    def verify(self) -> tuple[bool, str | None]:
        previous_hash = self.GENESIS
        for index, entry in enumerate(self.entries(), start=1):
            claimed = entry.get("entry_hash")
            unsigned = {key: value for key, value in entry.items() if key != "entry_hash"}
            if entry.get("previous_hash") != previous_hash or object_hash(unsigned) != claimed:
                return False, f"Hash-chain failure at entry {index}"
            previous_hash = claimed
        return True, None

    def totals(self, metrics: Iterable[str] | None = None) -> dict[str, float]:
        allowed = set(metrics or ())
        totals: dict[str, float] = {}
        for entry in self.entries():
            if allowed and entry["metric"] not in allowed:
                continue
            totals[entry["metric"]] = totals.get(entry["metric"], 0) + float(entry["value"])
        return totals
