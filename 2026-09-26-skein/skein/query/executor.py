"""Executes a parsed SkeinQL Statement against a Graph: pattern matching
(via the planner's chosen anchor), WHERE filtering, CREATE/SET/DELETE
mutations, and RETURN/ORDER BY/LIMIT projection.
"""
from ..storage import SkeinError
from .ast import (
    NodePattern, RelPattern, Literal, VarRef, PropAccess, UnaryOp, BinOp,
    FuncCall, Statement,
)
from .planner import choose_anchor, initial_candidates, node_matches, rel_matches


def _pos_key(element, pos):
    """Internal binding key for a pattern element: its variable name if
    the query bound one, else a synthetic per-position key so anonymous
    elements can still be threaded through chain matching.
    """
    return element.var if element.var else f"__pos{pos}"


def compute_var_kinds(stmt: Statement):
    kinds = {}
    patterns = ([stmt.match] if stmt.match is not None else []) + (stmt.create or [])
    for pattern in patterns:
        for pos, el in enumerate(pattern.elements):
            if el.var:
                kind = "node" if pos % 2 == 0 else "edge"
                existing = kinds.get(el.var)
                if existing is not None and existing != kind:
                    raise SkeinError(f"variable '{el.var}' is used as both a node and a relationship")
                kinds[el.var] = kind
    return kinds


def _step(graph, cur_nid, rel_pat: RelPattern, moving_right: bool):
    """Neighbors of cur_nid reachable across rel_pat, expanding the chain
    one hop further right (toward higher pattern positions) or left.
    """
    forward = (rel_pat.direction == "->") if moving_right else (rel_pat.direction == "<-")
    edge_ids = graph.out_edges.get(cur_nid, []) if forward else graph.in_edges.get(cur_nid, [])
    result = []
    for eid in edge_ids:
        edge = graph.edges[eid]
        other = edge.dst if forward else edge.src
        result.append((eid, other))
    return result


def _extend_direction(graph, elements, anchor_pos, bindings, moving_right):
    frontier = [dict(bindings)]
    pos = anchor_pos
    step_by = 2 if moving_right else -2
    while (pos + step_by >= 0) and (pos + step_by < len(elements)):
        rel_pos = pos + (1 if moving_right else -1)
        node_pos = pos + step_by
        rel_pat = elements[rel_pos]
        node_pat = elements[node_pos]
        cur_key = _pos_key(elements[pos], pos)
        next_key = _pos_key(node_pat, node_pos)
        new_frontier = []
        for binding in frontier:
            cur_nid = binding[cur_key]
            for eid, other in _step(graph, cur_nid, rel_pat, moving_right):
                if not rel_matches(graph, rel_pat, eid):
                    continue
                if not node_matches(graph, node_pat, other):
                    continue
                if rel_pat.var and rel_pat.var in binding and binding[rel_pat.var] != eid:
                    continue
                if next_key in binding and binding[next_key] != other:
                    continue
                nb = dict(binding)
                if rel_pat.var:
                    nb[rel_pat.var] = eid
                nb[next_key] = other
                new_frontier.append(nb)
        frontier = new_frontier
        pos = node_pos
    return frontier


def match_pattern(graph, pattern):
    """Returns (bindings_list, plan_dict). Each binding maps every pattern
    variable (plus synthetic keys for anonymous elements) to a node/edge id.
    """
    elements = pattern.elements
    anchor_pos, plan = choose_anchor(graph, elements)
    anchor_pat = elements[anchor_pos]
    anchor_key = _pos_key(anchor_pat, anchor_pos)

    results = []
    for nid in initial_candidates(graph, anchor_pat, plan):
        base = {anchor_key: nid}
        right = _extend_direction(graph, elements, anchor_pos, base, moving_right=True)
        left = _extend_direction(graph, elements, anchor_pos, base, moving_right=False)
        for rb in right:
            for lb in left:
                merged = dict(lb)
                conflict = False
                for k, v in rb.items():
                    if k in merged and merged[k] != v:
                        conflict = True
                        break
                    merged[k] = v
                if not conflict:
                    results.append(merged)
    return results, plan


# --------------------------------------------------------------- eval ----

def _truthy(value) -> bool:
    return bool(value)


_BINOPS = {
    "=": lambda a, b: a == b,
    "<>": lambda a, b: a != b,
    "<": lambda a, b: a is not None and b is not None and a < b,
    "<=": lambda a, b: a is not None and b is not None and a <= b,
    ">": lambda a, b: a is not None and b is not None and a > b,
    ">=": lambda a, b: a is not None and b is not None and a >= b,
    "+": lambda a, b: a + b,
    "-": lambda a, b: a - b,
    "*": lambda a, b: a * b,
    "/": lambda a, b: a / b,
}


def _safe_binop(op, a, b):
    try:
        return _BINOPS[op](a, b)
    except TypeError:
        raise SkeinError(f"cannot apply '{op}' to {a!r} and {b!r} (missing property or mismatched types?)")
    except ZeroDivisionError:
        raise SkeinError(f"division by zero evaluating {a!r} {op} {b!r}")


def _resolve_element(graph, var, binding, var_kinds):
    if var not in binding:
        raise SkeinError(f"unbound variable '{var}'")
    vid = binding[var]
    kind = var_kinds.get(var, "node")
    elem = graph.nodes.get(vid) if kind == "node" else graph.edges.get(vid)
    if elem is None:
        raise SkeinError(f"'{var}' no longer refers to an existing {kind}")
    return kind, elem


def eval_expr(graph, expr, binding, var_kinds):
    if isinstance(expr, Literal):
        return expr.value
    if isinstance(expr, VarRef):
        return binding.get(expr.var)
    if isinstance(expr, PropAccess):
        _kind, elem = _resolve_element(graph, expr.var, binding, var_kinds)
        return elem.props.get(expr.prop)
    if isinstance(expr, UnaryOp):
        if expr.op == "NOT":
            return not _truthy(eval_expr(graph, expr.operand, binding, var_kinds))
        if expr.op == "-":
            value = eval_expr(graph, expr.operand, binding, var_kinds)
            try:
                return -value
            except TypeError:
                raise SkeinError(f"cannot negate {value!r}")
        raise SkeinError(f"unknown unary operator {expr.op}")
    if isinstance(expr, BinOp):
        if expr.op == "AND":
            return _truthy(eval_expr(graph, expr.left, binding, var_kinds)) and _truthy(eval_expr(graph, expr.right, binding, var_kinds))
        if expr.op == "OR":
            return _truthy(eval_expr(graph, expr.left, binding, var_kinds)) or _truthy(eval_expr(graph, expr.right, binding, var_kinds))
        left = eval_expr(graph, expr.left, binding, var_kinds)
        right = eval_expr(graph, expr.right, binding, var_kinds)
        return _safe_binop(expr.op, left, right)
    if isinstance(expr, FuncCall):
        return _call_func(graph, expr, binding, var_kinds)
    raise SkeinError(f"cannot evaluate expression {expr!r}")


def _is_count_star(expr) -> bool:
    return isinstance(expr, FuncCall) and expr.name.lower() == "count" and len(expr.args) == 1 and isinstance(expr.args[0], VarRef) and expr.args[0].var == "*"


def _single_var_arg(expr: FuncCall) -> str:
    if len(expr.args) != 1 or not isinstance(expr.args[0], VarRef):
        raise SkeinError(f"{expr.name}() expects a single variable argument, e.g. {expr.name}(a)")
    return expr.args[0].var


def _call_func(graph, expr: FuncCall, binding, var_kinds):
    name = expr.name.lower()
    if name == "id":
        var = _single_var_arg(expr)
        if var not in binding:
            raise SkeinError(f"unbound variable '{var}'")
        return binding[var]
    if name == "labels":
        var = _single_var_arg(expr)
        kind, elem = _resolve_element(graph, var, binding, var_kinds)
        if kind != "node":
            raise SkeinError(f"labels() expects a node variable, but '{var}' is a relationship")
        return sorted(elem.labels)
    if name == "type":
        var = _single_var_arg(expr)
        kind, elem = _resolve_element(graph, var, binding, var_kinds)
        if kind != "edge":
            raise SkeinError(f"type() expects a relationship variable, but '{var}' is a node")
        return elem.type
    if name == "count":
        # Only meaningful as the sole top-level RETURN item, handled as a
        # special case by execute() before any per-row projection runs.
        # Reaching this branch means count() was used somewhere else (e.g.
        # mixed with other RETURN items) -- returning a placeholder there
        # would silently look like a real per-row count. Refuse instead.
        raise SkeinError("count(*) is only supported as the sole RETURN expression, e.g. RETURN count(*)")
    raise SkeinError(f"unknown function {expr.name}()")


def expr_display_name(expr) -> str:
    if isinstance(expr, VarRef):
        return expr.var
    if isinstance(expr, PropAccess):
        return f"{expr.var}.{expr.prop}"
    if isinstance(expr, FuncCall):
        args = ", ".join(expr_display_name(a) for a in expr.args)
        return f"{expr.name}({args})"
    if isinstance(expr, Literal):
        return repr(expr.value)
    return "expr"


def describe_element(graph, var, binding, var_kinds):
    kind, elem = _resolve_element(graph, var, binding, var_kinds)
    if kind == "node":
        return {"id": elem.id, "labels": sorted(elem.labels), "props": dict(elem.props)}
    return {"id": elem.id, "type": elem.type, "src": elem.src, "dst": elem.dst, "props": dict(elem.props)}


def project_row(graph, items, binding, var_kinds):
    row = {}
    for item in items:
        name = item.alias or expr_display_name(item.expr)
        if isinstance(item.expr, VarRef) and item.expr.var != "*":
            row[name] = describe_element(graph, item.expr.var, binding, var_kinds)
        else:
            row[name] = eval_expr(graph, item.expr, binding, var_kinds)
    return row


_SORT_RANK = {type(None): 0, bool: 1, int: 2, float: 2, str: 3}


def _sort_key(value):
    rank = _SORT_RANK.get(type(value), 4)
    if rank in (0, 4):
        return (rank, 0)
    if rank == 1:
        return (rank, int(value))
    if rank == 2:
        return (rank, float(value))
    return (rank, value)


def sort_bindings(graph, bindings, order_by, var_kinds):
    result = list(bindings)
    for item in reversed(order_by):
        result.sort(key=lambda b: _sort_key(eval_expr(graph, item.expr, b, var_kinds)), reverse=item.desc)
    return result


# ------------------------------------------------------------- mutation --

def apply_create(graph, pattern, binding, var_kinds):
    elements = pattern.elements
    node_ids = {}
    for pos in range(0, len(elements), 2):
        node_pat: NodePattern = elements[pos]
        if node_pat.var and node_pat.var in binding:
            node_ids[pos] = binding[node_pat.var]
            continue
        nid = graph.create_node(node_pat.labels, node_pat.props)
        node_ids[pos] = nid
        if node_pat.var:
            binding[node_pat.var] = nid
    for pos in range(1, len(elements), 2):
        rel_pat: RelPattern = elements[pos]
        left_id, right_id = node_ids[pos - 1], node_ids[pos + 1]
        rel_type = rel_pat.types[0] if rel_pat.types else "RELATED"
        src, dst = (left_id, right_id) if rel_pat.direction == "->" else (right_id, left_id)
        eid = graph.create_edge(src, dst, rel_type, rel_pat.props)
        if rel_pat.var:
            binding[rel_pat.var] = eid


def execute(graph, stmt: Statement, explain: bool = False):
    var_kinds = compute_var_kinds(stmt)
    plan = None

    if stmt.match is not None:
        bindings, plan = match_pattern(graph, stmt.match)
    else:
        bindings = [{}]

    if stmt.where is not None:
        bindings = [b for b in bindings if _truthy(eval_expr(graph, stmt.where, b, var_kinds))]

    has_mutation = stmt.create is not None or stmt.set_items or stmt.delete_vars
    auto_commit = has_mutation and not graph.in_transaction()
    if has_mutation and auto_commit:
        graph.begin()
    try:
        if has_mutation:
            for binding in bindings:
                for create_pattern in stmt.create or []:
                    apply_create(graph, create_pattern, binding, var_kinds)
                if stmt.set_items:
                    for target, expr in stmt.set_items:
                        value = eval_expr(graph, expr, binding, var_kinds)
                        kind = var_kinds.get(target.var, "node")
                        if kind == "node":
                            graph.set_node_prop(binding[target.var], target.prop, value)
                        else:
                            graph.set_edge_prop(binding[target.var], target.prop, value)
                if stmt.delete_vars:
                    for v in stmt.delete_vars:
                        kind = var_kinds.get(v, "node")
                        vid = binding.get(v)
                        if vid is None:
                            continue
                        if kind == "node":
                            if vid in graph.nodes:
                                graph.delete_node(vid, detach=stmt.detach)
                        else:
                            if vid in graph.edges:
                                graph.delete_edge(vid)
        if has_mutation and auto_commit:
            graph.commit()
    except Exception:
        if has_mutation and auto_commit:
            graph.rollback()
        raise

    rows = None
    if stmt.return_items is not None:
        if len(stmt.return_items) == 1 and _is_count_star(stmt.return_items[0].expr):
            name = stmt.return_items[0].alias or "count"
            rows = [{name: len(bindings)}]
        else:
            ordered = sort_bindings(graph, bindings, stmt.order_by, var_kinds) if stmt.order_by else bindings
            if stmt.limit is not None:
                ordered = ordered[: stmt.limit]
            rows = [project_row(graph, stmt.return_items, b, var_kinds) for b in ordered]

    if explain:
        return rows, plan
    return rows
