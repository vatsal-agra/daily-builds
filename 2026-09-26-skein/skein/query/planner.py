"""Turns a MATCH pattern into a cheap starting point: prefer a
(label, property)-indexed equality lookup, then a plain label-index scan,
falling back to a full node scan only when the pattern gives the planner
nothing to work with.
"""
from .ast import NodePattern


def node_matches(graph, node_pat: NodePattern, nid: int) -> bool:
    node = graph.nodes.get(nid)
    if node is None:
        return False
    if node_pat.labels and not set(node_pat.labels).issubset(node.labels):
        return False
    for key, value in node_pat.props.items():
        if node.props.get(key) != value:
            return False
    return True


def rel_matches(graph, rel_pat, eid: int) -> bool:
    edge = graph.edges.get(eid)
    if edge is None:
        return False
    if rel_pat.types and edge.type not in rel_pat.types:
        return False
    for key, value in rel_pat.props.items():
        if edge.props.get(key) != value:
            return False
    return True


def score_node_pattern(graph, node_pat: NodePattern):
    """Lower score = cheaper. Returns (score, method)."""
    if node_pat.labels:
        label = node_pat.labels[0]
        for prop in node_pat.props:
            if (label, prop) in graph.prop_indexes:
                return (0, "prop_index", label, prop)
        if graph.label_index.has_label(label):
            return (1, "label_index", label, None)
        return (1, "label_index", label, None)  # empty label bucket: still cheap, just empty
    return (2, "scan", None, None)


def choose_anchor(graph, elements):
    """Pick the node position (even index) in the pattern with the
    cheapest available starting set. Returns (position, plan_dict).
    """
    best = None
    for pos in range(0, len(elements), 2):
        score, method, label, prop = score_node_pattern(graph, elements[pos])
        if best is None or score < best[0]:
            best = (score, method, label, prop, pos)
    _, method, label, prop, pos = best
    plan = {"anchor_pos": pos, "method": method, "label": label, "prop": prop}
    return pos, plan


def initial_candidates(graph, node_pat: NodePattern, plan=None):
    if node_pat.labels:
        label = node_pat.labels[0]
        for prop, value in node_pat.props.items():
            idx = graph.prop_indexes.get((label, prop))
            if idx is not None:
                return [nid for nid in idx.eq(value) if node_matches(graph, node_pat, nid)]
        return [nid for nid in graph.label_index.get(label) if node_matches(graph, node_pat, nid)]
    return [nid for nid in graph.nodes.keys() if node_matches(graph, node_pat, nid)]
