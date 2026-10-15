from collections import defaultdict, deque

from .schemas import FlowEdge, FlowGraph, GraphWarning, NodeType, PositionedNode


HORIZONTAL_GAP = 280
VERTICAL_GAP = 150


def validate_and_layout(graph: FlowGraph) -> tuple[list[PositionedNode], list[FlowEdge], list[GraphWarning]]:
    warnings: list[GraphWarning] = []
    node_by_id = {node.id: node for node in graph.nodes}

    valid_edges: list[FlowEdge] = []
    seen_edges: set[tuple[str, str, str]] = set()
    for edge in graph.edges:
        if edge.source not in node_by_id or edge.target not in node_by_id:
            warnings.append(
                GraphWarning(
                    code="invalid_edge_removed",
                    message=f"Removed edge {edge.source} → {edge.target} because a node was missing.",
                    node_ids=[edge.source, edge.target],
                )
            )
            continue
        key = (edge.source, edge.target, edge.label)
        if key not in seen_edges:
            valid_edges.append(edge)
            seen_edges.add(key)

    incoming: dict[str, list[str]] = defaultdict(list)
    outgoing: dict[str, list[FlowEdge]] = defaultdict(list)
    for edge in valid_edges:
        incoming[edge.target].append(edge.source)
        outgoing[edge.source].append(edge)

    starts = [node.id for node in graph.nodes if node.type == NodeType.START]
    if not starts:
        starts = [node.id for node in graph.nodes if not incoming[node.id]]
    if not starts:
        starts = [graph.nodes[0].id]
        warnings.append(
            GraphWarning(
                code="implicit_start",
                message="No start node was identifiable; the first node is used as the layout root.",
                node_ids=starts,
            )
        )

    for node in graph.nodes:
        if node.type == NodeType.DECISION:
            branches = outgoing[node.id]
            if len(branches) < 2 or any(not edge.label.strip() for edge in branches):
                warnings.append(
                    GraphWarning(
                        code="incomplete_decision",
                        message=f'"{node.label}" needs at least two labeled branches.',
                        node_ids=[node.id],
                    )
                )

    reachable: set[str] = set()
    queue = deque(starts)
    while queue:
        node_id = queue.popleft()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        queue.extend(edge.target for edge in outgoing[node_id] if not edge.is_loop)

    disconnected = [node.id for node in graph.nodes if node.id not in reachable]
    if disconnected:
        warnings.append(
            GraphWarning(
                code="disconnected_nodes",
                message=f"{len(disconnected)} node(s) are disconnected from the main process.",
                node_ids=disconnected,
            )
        )

    levels = _assign_levels([node.id for node in graph.nodes], starts, outgoing)
    by_level: dict[int, list[str]] = defaultdict(list)
    for node in graph.nodes:
        by_level[levels.get(node.id, max(levels.values(), default=0) + 1)].append(node.id)

    positions: dict[str, tuple[float, float]] = {}
    for level, node_ids in sorted(by_level.items()):
        width = (len(node_ids) - 1) * HORIZONTAL_GAP
        for index, node_id in enumerate(node_ids):
            positions[node_id] = (index * HORIZONTAL_GAP - width / 2, level * VERTICAL_GAP)

    positioned = [
        PositionedNode(**node.model_dump(), x=positions[node.id][0], y=positions[node.id][1])
        for node in graph.nodes
    ]
    return positioned, valid_edges, warnings


def _assign_levels(
    node_ids: list[str], starts: list[str], outgoing: dict[str, list[FlowEdge]]
) -> dict[str, int]:
    levels = {start: 0 for start in starts}
    queue = deque(starts)
    iterations = 0
    max_iterations = max(1, len(node_ids) * 4)

    while queue and iterations < max_iterations:
        current = queue.popleft()
        iterations += 1
        for edge in outgoing[current]:
            if edge.is_loop:
                continue
            proposed = levels[current] + 1
            if edge.target not in levels or proposed > levels[edge.target]:
                levels[edge.target] = proposed
                queue.append(edge.target)

    next_level = max(levels.values(), default=-1) + 1
    for node_id in node_ids:
        if node_id not in levels:
            levels[node_id] = next_level
            next_level += 1
    return levels
