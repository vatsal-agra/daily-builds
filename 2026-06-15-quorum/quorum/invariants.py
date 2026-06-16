"""Global safety-invariant monitor for Raft.

A real distributed system can never observe every node's state at one instant,
but a simulator can — which is exactly what makes correctness checkable. After
every simulation step the cluster feeds all node states to :class:`SafetyMonitor`,
which checks Raft's five canonical safety properties and raises
:class:`SafetyViolation` (with the offending nodes/indices) the moment one breaks.
"""

from __future__ import annotations

from .raft import Role


class SafetyViolation(Exception):
    def __init__(self, prop: str, detail: str):
        super().__init__(f"[{prop}] {detail}")
        self.prop = prop
        self.detail = detail


class SafetyMonitor:
    def __init__(self):
        # index -> (entry_term, command, commit_term) recorded the first time the
        # index is committed on any node. The first node to observe an index as
        # committed is the leader that drove the commit, so its current term is
        # the commit term. Used for Leader Completeness and State Machine Safety.
        self.committed: dict[int, tuple[int, object, int]] = {}
        # index -> (command, result) recorded when first applied by any node.
        self.applied: dict[int, tuple[object, object]] = {}
        # node_id -> last seen (term, log-prefix-tuple) while it was leader.
        self._leader_log_snapshot: dict[int, tuple] = {}
        self.checks_run = 0

    def record_applied(self, node_id, index, command, result):
        """Called by the cluster as entries are applied. Enforces State Machine
        Safety: no two nodes apply a different command/result at the same index."""
        if index in self.applied:
            prev_cmd, prev_res = self.applied[index]
            if prev_cmd != command:
                raise SafetyViolation(
                    "StateMachineSafety",
                    f"node {node_id} applied {command!r} at index {index} but "
                    f"{prev_cmd!r} was applied there earlier",
                )
            if prev_res != result:
                raise SafetyViolation(
                    "StateMachineSafety",
                    f"node {node_id} got result {result!r} for index {index} "
                    f"but {prev_res!r} was seen earlier (divergent state machine)",
                )
        else:
            self.applied[index] = (command, result)

    def check(self, nodes: dict, alive: set):
        """Run all global invariant checks over the current node states."""
        self.checks_run += 1
        live_nodes = {nid: n for nid, n in nodes.items() if nid in alive}

        self._election_safety(nodes)
        self._leader_append_only(nodes, alive)
        self._record_committed(nodes)
        self._log_matching(nodes)
        self._leader_completeness(nodes, alive)

    # --- 1. Election Safety: at most one leader per term ---
    def _election_safety(self, nodes):
        leaders_by_term: dict[int, int] = {}
        for nid, n in nodes.items():
            if n.role == Role.LEADER:
                t = n.current_term
                if t in leaders_by_term and leaders_by_term[t] != nid:
                    raise SafetyViolation(
                        "ElectionSafety",
                        f"nodes {leaders_by_term[t]} and {nid} are both leaders "
                        f"in term {t}",
                    )
                leaders_by_term[t] = nid

    # --- 2. Leader Append-Only: a leader never overwrites its own log ---
    def _leader_append_only(self, nodes, alive):
        for nid, n in nodes.items():
            if n.role == Role.LEADER and nid in alive:
                # Map absolute index -> (term, command) for the in-memory log.
                snap = {
                    i: (n.term_at(i),
                        n.entry_at(i).command if n.entry_at(i) else None)
                    for i in range(n.base_index + 1, n.last_log_index() + 1)
                }
                key = (n.current_term, nid)
                prev = self._leader_log_snapshot.get(key)
                if prev is not None:
                    # Any index present in both snapshots must be unchanged. (A
                    # snapshot may trim a committed prefix — that is not a
                    # mutation — so we compare only the overlapping indices.)
                    for i, val in prev.items():
                        if i in snap and snap[i] != val:
                            raise SafetyViolation(
                                "LeaderAppendOnly",
                                f"leader {nid} (term {n.current_term}) changed the "
                                f"entry at index {i} from {val!r} to {snap[i]!r}",
                            )
                    merged = dict(prev)
                    merged.update(snap)
                    self._leader_log_snapshot[key] = merged
                else:
                    self._leader_log_snapshot[key] = snap

    # --- record committed entries (helper for properties 4 & 5) ---
    def _record_committed(self, nodes):
        for nid, n in nodes.items():
            hi = min(n.commit_index, n.last_log_index())
            for i in range(n.base_index + 1, hi + 1):
                e = n.entry_at(i)
                if e is None:
                    continue
                if i in self.committed:
                    t, cmd, _ct = self.committed[i]
                    if t == e.term and cmd != e.command:
                        raise SafetyViolation(
                            "StateMachineSafety",
                            f"index {i} committed as {cmd!r} (term {t}) but node "
                            f"{nid} has {e.command!r} committed there",
                        )
                    if t != e.term:
                        # Two nodes both committed index i but with different
                        # terms => a committed entry was overwritten (split brain).
                        raise SafetyViolation(
                            "StateMachineSafety",
                            f"index {i} committed with term {t} but node {nid} has "
                            f"term {e.term} committed there",
                        )
                else:
                    self.committed[i] = (e.term, e.command, n.current_term)

    # --- 3. Log Matching: same index+term => identical prefix ---
    def _log_matching(self, nodes):
        node_list = list(nodes.values())
        for i in range(len(node_list)):
            for j in range(i + 1, len(node_list)):
                a, b = node_list[i], node_list[j]
                lo = max(a.base_index, b.base_index) + 1
                hi = min(a.last_log_index(), b.last_log_index())
                # Find the highest index where terms agree; prefix must match.
                for idx in range(hi, lo - 1, -1):
                    ea, eb = a.entry_at(idx), b.entry_at(idx)
                    if ea is None or eb is None:
                        continue
                    if ea.term == eb.term:
                        # Prefix from lo..idx must be identical.
                        for k in range(lo, idx + 1):
                            ka, kb = a.entry_at(k), b.entry_at(k)
                            if ka is None or kb is None:
                                continue
                            if ka.term != kb.term or ka.command != kb.command:
                                raise SafetyViolation(
                                    "LogMatching",
                                    f"nodes share term {ea.term} at index {idx} but "
                                    f"differ at index {k}",
                                )
                        break

    # --- 4. Leader Completeness: a leader holds all committed entries ---
    def _leader_completeness(self, nodes, alive):
        for nid, n in nodes.items():
            if n.role != Role.LEADER or nid not in alive:
                continue
            for idx, (term, cmd, commit_term) in self.committed.items():
                # The property only binds leaders of a term GREATER than the term
                # in which the entry committed. A stale lower-term leader (e.g. one
                # isolated in a minority partition) may legitimately hold a
                # conflicting *uncommitted* entry at this index.
                if n.current_term <= commit_term:
                    continue
                if idx <= n.base_index:
                    continue
                if idx > n.last_log_index():
                    raise SafetyViolation(
                        "LeaderCompleteness",
                        f"leader {nid} (term {n.current_term}) is missing committed "
                        f"index {idx} (committed in term {commit_term})",
                    )
                e = n.entry_at(idx)
                if e is not None and (e.term != term or e.command != cmd):
                    raise SafetyViolation(
                        "LeaderCompleteness",
                        f"leader {nid} (term {n.current_term}) has {e.command!r} "
                        f"(term {e.term}) at index {idx} but committed value is "
                        f"{cmd!r} (term {term}, committed in term {commit_term})",
                    )
