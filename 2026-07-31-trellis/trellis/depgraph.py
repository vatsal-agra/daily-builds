"""A directed graph of cell dependencies (`cell -> cells it reads`), plus
the operations the recalculation engine needs: updating edges when a
formula changes, computing the transitive closure of cells affected by an
edit, a topological order for evaluating just that closure, and Tarjan's
SCC algorithm to find every cell caught in a circular reference."""

from collections import deque


class DependencyGraph:
    def __init__(self):
        # cell -> set of cells it reads (its formula's references)
        self.precedents = {}
        # cell -> set of cells that read it
        self.dependents = {}

    def _ensure(self, key):
        self.precedents.setdefault(key, set())
        self.dependents.setdefault(key, set())

    def set_precedents(self, cell, new_precedents):
        """Rewrite `cell`'s outgoing edges to exactly `new_precedents`."""
        self._ensure(cell)
        old = self.precedents[cell]
        for p in old - new_precedents:
            self._ensure(p)
            self.dependents[p].discard(cell)
        for p in new_precedents - old:
            self._ensure(p)
            self.dependents[p].add(cell)
        self.precedents[cell] = set(new_precedents)

    def dependents_of(self, cell):
        return self.dependents.get(cell, set())

    def precedents_of(self, cell):
        return self.precedents.get(cell, set())

    def remove_cell(self, cell):
        """Fully remove a cell from the graph (used when a sheet/cell is
        deleted). Cells that referenced it keep a dangling edge -- callers
        are expected to have already re-pointed those formulas to #REF!."""
        for p in self.precedents.pop(cell, set()):
            self.dependents.get(p, set()).discard(cell)
        for d in self.dependents.pop(cell, set()):
            self.precedents.get(d, set()).discard(cell)

    def affected_closure(self, start_cells):
        """Every cell transitively dependent on any of `start_cells`,
        including the start cells themselves."""
        seen = set(start_cells)
        q = deque(start_cells)
        while q:
            cur = q.popleft()
            for dep in self.dependents.get(cur, ()):
                if dep not in seen:
                    seen.add(dep)
                    q.append(dep)
        return seen

    def topological_order(self, subset):
        """Kahn's algorithm over the subgraph induced by `subset`, using
        edges restricted to precedents that are also in `subset` (a
        precedent outside the subset is already up to date and doesn't
        need to be waited on). Raises ValueError if `subset` itself
        contains a cycle -- callers should run `find_cycles` first and
        exclude cyclic cells before calling this."""
        subset = set(subset)
        indegree = {c: 0 for c in subset}
        forward = {c: [] for c in subset}
        for c in subset:
            for p in self.precedents.get(c, ()):
                if p in subset:
                    forward[p].append(c)
                    indegree[c] += 1

        queue = deque(sorted((c for c in subset if indegree[c] == 0)))
        order = []
        while queue:
            cur = queue.popleft()
            order.append(cur)
            for nxt in forward[cur]:
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    queue.append(nxt)
        if len(order) != len(subset):
            raise ValueError("cycle detected in subset passed to topological_order")
        return order

    def find_cycles(self):
        """Tarjan's SCC over the whole graph. Returns the set of cells that
        belong to a strongly-connected component of size > 1, or a
        single-node component with a self-loop (A1 = A1+1)."""
        index_counter = [0]
        stack = []
        on_stack = set()
        indices = {}
        lowlink = {}
        result = set()

        nodes = set(self.precedents) | set(self.dependents)

        def strongconnect(v):
            work = [(v, iter(self.precedents.get(v, ())))]
            indices[v] = index_counter[0]
            lowlink[v] = index_counter[0]
            index_counter[0] += 1
            stack.append(v)
            on_stack.add(v)

            while work:
                node, it = work[-1]
                advanced = False
                for w in it:
                    if w not in indices:
                        indices[w] = index_counter[0]
                        lowlink[w] = index_counter[0]
                        index_counter[0] += 1
                        stack.append(w)
                        on_stack.add(w)
                        work.append((w, iter(self.precedents.get(w, ()))))
                        advanced = True
                        break
                    elif w in on_stack:
                        lowlink[node] = min(lowlink[node], indices[w])
                if advanced:
                    continue
                work.pop()
                if work:
                    parent = work[-1][0]
                    lowlink[parent] = min(lowlink[parent], lowlink[node])
                if lowlink[node] == indices[node]:
                    scc = []
                    while True:
                        w = stack.pop()
                        on_stack.discard(w)
                        scc.append(w)
                        if w == node:
                            break
                    if len(scc) > 1 or node in self.precedents.get(node, ()):
                        result.update(scc)

        for v in nodes:
            if v not in indices:
                strongconnect(v)
        return result
