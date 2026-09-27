"""Workbook/Sheet: cell storage, dependency graph, cycle-safe topological
recalculation (both full and incremental), reference-translating
copy/paste/fill, and undo/redo.
"""

from . import parser as P
from . import refs
from . import values as V
from .evaluator import EvalContext, evaluate
from .tokenizer import TokenizeError


class Cell:
    __slots__ = ("raw", "ast", "value", "precedents")

    def __init__(self):
        self.raw = ""       # exactly what the user typed
        self.ast = None     # parsed AST, only set for formula cells
        self.value = None   # cached computed Value
        self.precedents = frozenset()  # set of (col, row) this cell reads


def _parse_literal(text):
    """Non-formula raw text -> a literal Value (number, bool, or text). A
    leading apostrophe forces text, exactly like a real spreadsheet: typing
    `'5` or `'TRUE` stores (and displays) the literal text `5`/`TRUE`
    rather than a number or boolean, without needing `=\"5\"`."""
    if text.startswith("'"):
        return text[1:]
    stripped = text.strip()
    if stripped == "":
        return None
    try:
        return float(stripped)
    except ValueError:
        pass
    upper = stripped.upper()
    if upper == "TRUE":
        return True
    if upper == "FALSE":
        return False
    return text


class Sheet:
    def __init__(self):
        self.cells = {}              # (col,row) -> Cell, only for non-empty cells
        self.dependents = {}         # (col,row) -> set of (col,row) that read it
        self.undo_stack = []
        self.redo_stack = []

    # -- basic queries --------------------------------------------------

    def get_cell(self, col, row):
        return self.cells.get((col, row))

    def get_raw(self, col, row):
        c = self.cells.get((col, row))
        return c.raw if c else ""

    def get_value(self, col, row):
        c = self.cells.get((col, row))
        return c.value if c else None

    def get_display(self, col, row):
        return V.display(self.get_value(col, row))

    def used_bounds(self):
        """(max_col, max_row) across all non-empty cells, or (0, 0) if the
        sheet is empty."""
        if not self.cells:
            return (0, 0)
        return (max(c for c, r in self.cells), max(r for c, r in self.cells))

    def _lookup_for_eval(self, col, row):
        c = self.cells.get((col, row))
        return c.value if c else None

    # -- mutation ---------------------------------------------------------

    def set_cell(self, col, row, raw_text):
        """Set a single cell and push one undo transaction for it."""
        return self.set_cells({(col, row): raw_text})

    def set_cells(self, edits):
        """Apply a batch of (col,row)->raw_text edits as a single undo
        transaction, then recompute exactly the cells that could have
        changed. Returns the list of (col, row) cells whose display value
        or error state changed, for the caller (e.g. the HTTP API) to
        report back without re-sending the whole sheet."""
        transaction = []
        dirty_seed = set()
        seed_before = {}
        for (col, row), raw_text in edits.items():
            key = (col, row)
            old_raw = self.get_raw(col, row)
            # Captured here, *before* _set_raw mutates this cell: for a
            # directly-edited cell, `_set_raw` may install its new value
            # immediately (literal cells short-circuit recompute), so
            # taking this snapshot any later would compare the new value
            # against itself and silently miss every edit to a literal
            # cell as "unchanged".
            seed_before[key] = self.get_display(col, row)
            transaction.append((col, row, old_raw, raw_text))
            self._set_raw(col, row, raw_text)
            dirty_seed.add(key)
        self.undo_stack.append(transaction)
        self.redo_stack.clear()
        return self._recompute(dirty_seed, seed_before)

    def _set_raw(self, col, row, raw_text):
        key = (col, row)
        old = self.cells.get(key)
        old_precedents = old.precedents if old else frozenset()

        if raw_text is None or raw_text == "":
            if old is not None:
                del self.cells[key]
            new_precedents = frozenset()
        else:
            cell = Cell()
            cell.raw = raw_text
            if raw_text.startswith("="):
                try:
                    ast = P.parse(raw_text[1:])
                except (TokenizeError, P.ParseError):
                    ast = None
                    cell.value = V.Error("#ERROR!")
                cell.ast = ast
                if ast is not None:
                    new_precedents = frozenset(P.collect_refs(ast))
                else:
                    new_precedents = frozenset()
            else:
                cell.ast = None
                cell.value = _parse_literal(raw_text)
                new_precedents = frozenset()
            cell.precedents = new_precedents
            self.cells[key] = cell

        # Update reverse edges: this cell no longer depends on cells it
        # used to but doesn't anymore, and now depends on its new set.
        for p in old_precedents - new_precedents:
            self.dependents.get(p, set()).discard(key)
        for p in new_precedents - old_precedents:
            self.dependents.setdefault(p, set()).add(key)

    def _all_dependents(self, seed):
        """BFS over the dependents graph: every cell transitively affected
        by a change to any cell in `seed`, including the seed itself."""
        seen = set(seed)
        queue = list(seed)
        while queue:
            cur = queue.pop()
            for dep in self.dependents.get(cur, ()):
                if dep not in seen:
                    seen.add(dep)
                    queue.append(dep)
        return seen

    def _recompute(self, seed, seed_before=None):
        dirty = self._all_dependents(seed)
        return self._recompute_set(dirty, seed_before)

    def _recompute_set(self, dirty, seed_before=None):
        """Kahn's algorithm restricted to `dirty`: precedents outside the
        set are already resolved and read via cached values; a cell left
        with nonzero in-degree after the queue drains is part of a cycle
        (or depends on one) and is assigned #CYCLE!. Returns the list of
        (col, row) whose display output changed.

        `seed_before`, if given, overrides the pre-edit display value for
        directly-edited cells, since their current cell state has already
        been overwritten by the time this runs (see `set_cells`)."""
        seed_before = seed_before or {}
        indegree = {}
        for key in dirty:
            cell = self.cells.get(key)
            precedents = cell.precedents if cell else frozenset()
            indegree[key] = sum(1 for p in precedents if p in dirty)

        queue = [k for k in dirty if indegree[k] == 0]
        before = {k: seed_before.get(k, self.get_display(*k)) for k in dirty}
        ctx = EvalContext(self._lookup_for_eval)

        processed = set()
        while queue:
            key = queue.pop()
            processed.add(key)
            self._evaluate_cell(key, ctx)
            for dep in self.dependents.get(key, ()):
                if dep in indegree:
                    indegree[dep] -= 1
                    if indegree[dep] == 0:
                        queue.append(dep)

        for key in dirty - processed:
            cell = self.cells.get(key)
            if cell is not None:
                cell.value = V.CYCLE

        changed = [k for k in dirty if before[k] != self.get_display(*k)]
        return changed

    def _evaluate_cell(self, key, ctx):
        cell = self.cells.get(key)
        if cell is None:
            return
        if cell.ast is None:
            return  # literal cell (or a parse error, whose value is fixed)
        cell.value = evaluate(cell.ast, ctx)

    def recompute_all(self):
        """Full from-scratch recomputation of every non-empty cell, used
        as (a) the oracle the incremental engine is fuzzed against and
        (b) the code path for loading a workbook fresh."""
        return self._recompute_set(set(self.cells.keys()))

    # -- copy / paste / fill --------------------------------------------

    def copy_paste(self, src_top_left, src_bottom_right, dest_top_left):
        """Copy the rectangle [src_top_left, src_bottom_right] to a new
        rectangle anchored at dest_top_left, translating every formula's
        relative references by the paste offset."""
        sc, sr = src_top_left
        ec, er = src_bottom_right
        dc, dr = dest_top_left
        d_col, d_row = dc - sc, dr - sr
        edits = {}
        for row in range(sr, er + 1):
            for col in range(sc, ec + 1):
                raw = self.get_raw(col, row)
                target = (col + d_col, row + d_row)
                edits[target] = self._translate_raw(raw, d_col, d_row)
        return self.set_cells(edits)

    def fill(self, src_col, src_row, dest_top_left, dest_bottom_right):
        """Fill (drag-fill) a single source cell's formula across a
        destination rectangle, translating references by each target
        cell's own offset from the source."""
        dc0, dr0 = dest_top_left
        dc1, dr1 = dest_bottom_right
        src_raw = self.get_raw(src_col, src_row)
        edits = {}
        for row in range(dr0, dr1 + 1):
            for col in range(dc0, dc1 + 1):
                if (col, row) == (src_col, src_row):
                    continue
                d_col, d_row = col - src_col, row - src_row
                edits[(col, row)] = self._translate_raw(src_raw, d_col, d_row)
        return self.set_cells(edits)

    @staticmethod
    def _translate_raw(raw, d_col, d_row):
        if not raw.startswith("="):
            return raw
        try:
            ast = P.parse(raw[1:])
        except (TokenizeError, P.ParseError):
            return raw
        translated = P.translate(ast, d_col, d_row)
        return "=" + P.to_formula(translated)

    def clear(self, top_left, bottom_right):
        sc, sr = top_left
        ec, er = bottom_right
        edits = {}
        for row in range(sr, er + 1):
            for col in range(sc, ec + 1):
                edits[(col, row)] = ""
        return self.set_cells(edits)

    # -- undo / redo ------------------------------------------------------

    def undo(self):
        if not self.undo_stack:
            return []
        transaction = self.undo_stack.pop()
        dirty_seed = set()
        seed_before = {}
        for col, row, old_raw, new_raw in transaction:
            key = (col, row)
            seed_before[key] = self.get_display(col, row)
            self._set_raw(col, row, old_raw)
            dirty_seed.add(key)
        self.redo_stack.append(transaction)
        return self._recompute(dirty_seed, seed_before)

    def redo(self):
        if not self.redo_stack:
            return []
        transaction = self.redo_stack.pop()
        dirty_seed = set()
        seed_before = {}
        for col, row, old_raw, new_raw in transaction:
            key = (col, row)
            seed_before[key] = self.get_display(col, row)
            self._set_raw(col, row, new_raw)
            dirty_seed.add(key)
        self.undo_stack.append(transaction)
        return self._recompute(dirty_seed, seed_before)

    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)
