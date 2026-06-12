"""DFA compilation: subset construction over the NFA program, then Hopcroft
minimization.  Provides a fast boolean `fullmatch` path and state-count
reporting (NFA → subset DFA → minimal DFA).

Anchors are handled positionally: `^` edges are passable only in the start
state's closure, `$` edges only when testing acceptance.  Word boundaries
(\\b/\\B) are context-dependent and rejected with a clear error — use the
NFA engine for those patterns.
"""

from bisect import bisect_right

from .lexer import RegexCompileError
from .nfa import char_in_ranges


class DFA:
    def __init__(self, prog, minimize=True):
        for inst in prog:
            if inst.op == "assert" and inst.kind in ("b", "B"):
                raise RegexCompileError(
                    "word boundaries (\\b, \\B) are not supported by the DFA "
                    "engine; use the NFA engine for this pattern")
        self.prog = prog
        self.minimized = minimize
        self.n_nfa = len(prog)
        self._build_alphabet()
        self._subset_construct()
        self.n_subset = len(self.trans)
        if minimize:
            self._minimize()
        self.n_states = len(self.trans)

    # ---- alphabet partition -----------------------------------------

    def _build_alphabet(self):
        """Partition the codepoint space into intervals on which every char
        instruction is constant.  Intervals used by no instruction collapse
        into a single implicit 'other' class (always a dead move)."""
        marks = {0}
        for inst in self.prog:
            if inst.op == "char":
                for lo, hi in inst.ranges:
                    marks.add(lo)
                    marks.add(hi + 1)
        marks.discard(0x110000)
        starts = sorted(marks)
        self.class_ranges = []   # class id -> list of (lo, hi) intervals
        self._interval_class = []  # parallel to starts: class id or -1
        for i, lo in enumerate(starts):
            hi = (starts[i + 1] - 1) if i + 1 < len(starts) else 0x10FFFF
            used = any(inst.op == "char" and char_in_ranges(lo, inst.ranges)
                       for inst in self.prog)
            if used:
                self._interval_class.append(len(self.class_ranges))
                self.class_ranges.append((lo, hi))
            else:
                self._interval_class.append(-1)
        self._starts = starts
        self.n_classes = len(self.class_ranges)

    def class_of(self, cp):
        """Alphabet class of a codepoint, or -1 for the dead 'other' class."""
        i = bisect_right(self._starts, cp) - 1
        return self._interval_class[i]

    # ---- subset construction -----------------------------------------

    def _closure(self, kernel, at_start, at_end):
        """Set of char/match pcs reachable from kernel via epsilon edges.
        `^` passes only if at_start; `$` only if at_end."""
        seen = set()
        out = set()
        stack = list(kernel)
        while stack:
            pc = stack.pop()
            if pc in seen:
                continue
            seen.add(pc)
            inst = self.prog[pc]
            if inst.op in ("char", "match"):
                out.add(pc)
            elif inst.op == "assert":
                ok = (at_start if inst.kind == "^" else at_end)
                if ok:
                    stack.append(inst.x)
            else:
                stack.extend(inst.succs())
        return out

    def _subset_construct(self):
        start_key = (frozenset([0]), True)
        ids = {start_key: 0}
        worklist = [start_key]
        trans = [dict()]
        accept = [False]
        while worklist:
            kernel, at_start = worklist.pop()
            sid = ids[(kernel, at_start)]
            closed = self._closure(kernel, at_start, at_end=False)
            accept_closed = self._closure(kernel, at_start, at_end=True)
            accept[sid] = any(self.prog[pc].op == "match"
                              for pc in accept_closed)
            chars = [pc for pc in closed if self.prog[pc].op == "char"]
            for cls in range(self.n_classes):
                rep = self.class_ranges[cls][0]
                nk = frozenset(pc + 1 for pc in chars
                               if char_in_ranges(rep, self.prog[pc].ranges))
                if not nk:
                    continue
                key = (nk, False)
                if key not in ids:
                    ids[key] = len(trans)
                    trans.append(dict())
                    accept.append(False)
                    worklist.append(key)
                trans[sid][cls] = ids[key]
        self.trans = trans
        self.accept = accept
        self.start = 0

    # ---- Hopcroft minimization ----------------------------------------

    def _minimize(self):
        n = len(self.trans)
        dead = n  # implicit non-accepting sink to make the function total
        total = n + 1

        def delta(q, c):
            if q == dead:
                return dead
            return self.trans[q].get(c, dead)

        # inverse transition sets per (class, target)
        inv = [[set() for _ in range(total)] for _ in range(self.n_classes)]
        for q in range(total):
            for c in range(self.n_classes):
                inv[c][delta(q, c)].add(q)

        F = {q for q in range(n) if self.accept[q]}
        NF = set(range(total)) - F
        partition = [s for s in (F, NF) if s]
        work = [min(partition, key=len).copy()] if len(partition) > 1 \
            else [s.copy() for s in partition]
        while work:
            A = work.pop()
            for c in range(self.n_classes):
                X = set()
                for q in A:
                    X |= inv[c][q]
                if not X:
                    continue
                new_partition = []
                for Y in partition:
                    inter, diff = Y & X, Y - X
                    if inter and diff:
                        new_partition.append(inter)
                        new_partition.append(diff)
                        replaced = False
                        for i, Wset in enumerate(work):
                            if Wset == Y:
                                work[i] = inter
                                work.append(diff)
                                replaced = True
                                break
                        if not replaced:
                            work.append(min(inter, diff, key=len))
                    else:
                        new_partition.append(Y)
                partition = new_partition

        block_of = {}
        for b, states in enumerate(partition):
            for q in states:
                block_of[q] = b

        # Rebuild, renumbering blocks by BFS from the start block.
        # Transitions into the dead block stay implicit (missing = reject);
        # if the start state itself is equivalent to dead (a pattern that
        # matches nothing), the result is a single rejecting state.
        dead_block = block_of[dead]
        start_block = block_of[self.start]
        order = {start_block: 0}
        bfs = [start_block]
        new_trans, new_accept = [dict()], [False]
        i = 0
        while i < len(bfs):
            b = bfs[i]
            i += 1
            rep = next(q for q in partition[b] if q != dead)
            new_accept[order[b]] = self.accept[rep]
            for c in range(self.n_classes):
                tb = block_of[delta(rep, c)]
                if tb == dead_block:
                    continue
                if tb not in order:
                    order[tb] = len(new_trans)
                    new_trans.append(dict())
                    new_accept.append(False)
                    bfs.append(tb)
                new_trans[order[b]][c] = order[tb]
        self.trans = new_trans
        self.accept = new_accept
        self.start = 0

    # ---- matching ------------------------------------------------------

    def fullmatch(self, text):
        q = self.start
        for ch in text:
            c = self.class_of(ord(ch))
            if c == -1:
                return False
            q = self.trans[q].get(c)
            if q is None:
                return False
        return self.accept[q]
