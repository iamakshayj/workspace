"""Directed evidence and document lineage graph."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class LineageEdge:
    parent_id: str
    child_id: str
    relationship: str = "derived_from"


class LineageGraph:
    def __init__(self, edges: Iterable[LineageEdge] = ()) -> None:
        self._children: dict[str, set[str]] = defaultdict(set)
        self._parents: dict[str, set[str]] = defaultdict(set)
        self._relationships: dict[tuple[str, str], str] = {}
        for edge in edges:
            self.add(edge.parent_id, edge.child_id, edge.relationship)

    def add(self, parent_id: str, child_id: str, relationship: str = "derived_from") -> None:
        if not parent_id or not child_id or parent_id == child_id:
            raise ValueError("Lineage edges require two distinct identifiers")
        if parent_id in self.descendants(child_id):
            raise ValueError(f"Lineage cycle: {parent_id} -> {child_id}")
        self._children[parent_id].add(child_id)
        self._parents[child_id].add(parent_id)
        self._relationships[(parent_id, child_id)] = relationship

    def _walk(self, start: str, adjacency: dict[str, set[str]], max_depth: int | None) -> set[str]:
        found: set[str] = set()
        queue = deque((item, 1) for item in adjacency.get(start, ()))
        while queue:
            node, depth = queue.popleft()
            if node in found:
                continue
            found.add(node)
            if max_depth is None or depth < max_depth:
                queue.extend((item, depth + 1) for item in adjacency.get(node, ()))
        return found

    def ancestors(self, node_id: str, max_depth: int | None = None) -> set[str]:
        return self._walk(node_id, self._parents, max_depth)

    def descendants(self, node_id: str, max_depth: int | None = None) -> set[str]:
        return self._walk(node_id, self._children, max_depth)

    def edges(self) -> list[LineageEdge]:
        return [LineageEdge(parent, child, relationship) for (parent, child), relationship in sorted(self._relationships.items())]
