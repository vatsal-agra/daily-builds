"""Deadlock avoidance (Banker's Algorithm) and deadlock detection (resource-
allocation-graph cycle detection) -- the two classical answers to "how do we
know the system won't/didn't deadlock" for multi-instance and single-instance
resources respectively.
"""

from __future__ import annotations

from copy import deepcopy


class DeadlockError(ValueError):
    pass


def _need_matrix(max_matrix, allocation):
    need = []
    for i, (mx_row, al_row) in enumerate(zip(max_matrix, allocation)):
        row = [mx - al for mx, al in zip(mx_row, al_row)]
        if any(x < 0 for x in row):
            raise DeadlockError(f"process P{i}: allocation exceeds max claim ({al_row} > {mx_row})")
        need.append(row)
    return need


def _dims_ok(available, max_matrix, allocation):
    m = len(available)
    if any(len(row) != m for row in max_matrix) or any(len(row) != m for row in allocation):
        raise DeadlockError("available/max/allocation must all share the same number of resource types")
    if len(max_matrix) != len(allocation):
        raise DeadlockError("max and allocation must have the same number of process rows")


def bankers_safety(available, max_matrix, allocation):
    """The Banker's Algorithm safety check. Returns (is_safe, safe_sequence_or_None).
    `safe_sequence` is a list of process indices [0, n) such that granting each
    process's *entire remaining need* in that order, one at a time, never leaves
    the system unable to satisfy whoever's left -- the classical definition of a
    safe state. Scans candidates in index order each round (the standard
    textbook algorithm), so it is deterministic given the same input."""
    _dims_ok(available, max_matrix, allocation)
    need = _need_matrix(max_matrix, allocation)
    n = len(max_matrix)
    work = list(available)
    finish = [False] * n
    sequence = []
    changed = True
    while changed:
        changed = False
        for i in range(n):
            if finish[i]:
                continue
            if all(need[i][r] <= work[r] for r in range(len(work))):
                for r in range(len(work)):
                    work[r] += allocation[i][r]
                finish[i] = True
                sequence.append(i)
                changed = True
    if all(finish):
        return True, sequence
    return False, None


def bankers_request(available, max_matrix, allocation, process, request):
    """Evaluate (without mutating any input) whether granting `request` (a
    resource-count vector) to process index `process` right now keeps the
    system in a safe state. Returns (granted: bool, reason: str)."""
    _dims_ok(available, max_matrix, allocation)
    n = len(max_matrix)
    if not (0 <= process < n):
        raise DeadlockError(f"process index {process} out of range [0,{n})")
    need = _need_matrix(max_matrix, allocation)
    m = len(available)
    if len(request) != m:
        raise DeadlockError(f"request must have {m} resource types, got {len(request)}")
    if any(request[r] > need[process][r] for r in range(m)):
        return False, "request exceeds the process's declared maximum need"
    if any(request[r] > available[r] for r in range(m)):
        return False, "request exceeds currently available resources"
    # tentatively grant, then re-run the safety algorithm on the hypothetical state
    trial_available = [available[r] - request[r] for r in range(m)]
    trial_allocation = deepcopy(allocation)
    trial_allocation[process] = [trial_allocation[process][r] + request[r] for r in range(m)]
    safe, _seq = bankers_safety(trial_available, max_matrix, trial_allocation)
    if safe:
        return True, "state remains safe after granting"
    return False, "granting would leave the system in an unsafe state"


def brute_force_safe_sequence_exists(available, max_matrix, allocation):
    """Independent oracle for tests: try every permutation of process indices
    (only tractable for small n) and check whether any ordering can complete
    without ever exceeding available resources. Used to cross-check
    `bankers_safety`'s greedy-scan result, not shipped as the real algorithm."""
    from itertools import permutations
    need = _need_matrix(max_matrix, allocation)
    n = len(max_matrix)
    for order in permutations(range(n)):
        work = list(available)
        ok = True
        for i in order:
            if not all(need[i][r] <= work[r] for r in range(len(work))):
                ok = False
                break
            for r in range(len(work)):
                work[r] += allocation[i][r]
        if ok:
            return True
    return False


# ---------------------------------------------------------------------------
# Resource-Allocation-Graph cycle detection (single-instance-per-resource model)
# ---------------------------------------------------------------------------

def detect_cycle(assignment_edges, request_edges):
    """Build a resource-allocation graph from `assignment_edges` (list of
    (resource, process) meaning "resource is currently held by process") and
    `request_edges` (list of (process, resource) meaning "process is blocked
    waiting for resource"), then DFS for a cycle. For single-instance
    resources, a cycle in this graph is necessary *and sufficient* for
    deadlock. Returns the cycle as a list of node labels (alternating
    process/resource) if one exists, else None."""
    assignment_edges = assignment_edges or []
    request_edges = request_edges or []
    graph = {}

    def add_edge(u, v):
        graph.setdefault(u, []).append(v)
        graph.setdefault(v, [])

    for resource, process in assignment_edges:
        add_edge(f"R:{resource}", f"P:{process}")
    for process, resource in request_edges:
        add_edge(f"P:{process}", f"R:{resource}")

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node: WHITE for node in graph}
    path = []

    def dfs(u):
        color[u] = GRAY
        path.append(u)
        for v in graph.get(u, []):
            if color[v] == GRAY:
                cycle_start = path.index(v)
                return path[cycle_start:] + [v]
            if color[v] == WHITE:
                result = dfs(v)
                if result is not None:
                    return result
        path.pop()
        color[u] = BLACK
        return None

    for node in list(graph):
        if color[node] == WHITE:
            result = dfs(node)
            if result is not None:
                return [n.split(":", 1)[1] for n in result]
    return None
