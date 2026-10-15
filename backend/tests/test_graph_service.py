from backend.app.graph_service import validate_and_layout
from backend.app.schemas import FlowEdge, FlowGraph, FlowNode, NodeType


def test_layout_and_decision_warning():
    graph = FlowGraph(
        title="Approval",
        nodes=[
            FlowNode(id="start", label="Start", type=NodeType.START),
            FlowNode(id="approved", label="Approved?", type=NodeType.DECISION),
            FlowNode(id="done", label="Done", type=NodeType.END),
        ],
        edges=[
            FlowEdge(source="start", target="approved"),
            FlowEdge(source="approved", target="done"),
        ],
    )

    nodes, edges, warnings = validate_and_layout(graph)

    assert len(nodes) == 3
    assert len(edges) == 2
    assert any(warning.code == "incomplete_decision" for warning in warnings)
    assert nodes[0].y < nodes[-1].y


def test_invalid_edges_are_removed():
    graph = FlowGraph(
        title="Broken",
        nodes=[FlowNode(id="only", label="Only")],
        edges=[FlowEdge(source="only", target="missing")],
    )

    _, edges, warnings = validate_and_layout(graph)

    assert edges == []
    assert warnings[0].code == "invalid_edge_removed"
