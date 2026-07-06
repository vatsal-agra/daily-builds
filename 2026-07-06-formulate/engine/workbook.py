"""The core spreadsheet model: cells, sheets, the live dependency graph,
incremental (dirty-propagation) recalculation, circular-reference detection,
undo/redo, and autofill.
"""

import math
from collections import deque

from . import parser
from .ast_nodes import RangeRef, col_to_letters, letters_to_col, shift_refs, unparse, walk_refs
from .errors import ErrorValue, CIRC
from .evaluator import EvalContext, evaluate
from .lexer import LexError

SYNTAX = "#SYNTAX!"

MAX_RANGE_CELLS = 20000


class RangeTooLargeError(Exception):
    pass


class Cell:
    __slots__ = ("raw", "ast", "computed")

    def __init__(self, raw, ast, computed):
        self.raw = raw
        self.ast = ast
        self.computed = computed


def parse_literal(text):
    """Coerce plain (non-'=') cell text the way typing it into Excel would."""
    stripped = text.strip()
    upper = stripped.upper()
    if upper == "TRUE":
        return True
    if upper == "FALSE":
        return False
    try:
        value = float(stripped)
    except ValueError:
        return text
    # A literal like "1e400" parses fine but overflows to inf: fall back to
    # text rather than storing a value that would crash display formatting.
    return value if math.isfinite(value) else text


def display_value(value):
    """Render a computed cell value the way a spreadsheet UI/CSV export would."""
    if value is None:
        return ""
    if isinstance(value, ErrorValue):
        return value.code
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        if not math.isfinite(value):
            return "#NUM!"  # defence in depth; evaluate()/parse_literal should never let this through
        if value == int(value) and abs(value) < 1e15:
            return str(int(value))
        return repr(value)
    return str(value)


def ref_to_a1(row, col):
    return f"{col_to_letters(col)}{row + 1}"


def a1_to_ref(a1):
    i = 0
    while i < len(a1) and a1[i].isalpha():
        i += 1
    return int(a1[i:]) - 1, letters_to_col(a1[:i])


class Sheet:
    def __init__(self, name):
        self.name = name
        self.cells = {}  # (row, col) -> Cell

    def get_computed(self, row, col):
        cell = self.cells.get((row, col))
        return cell.computed if cell else None

    def get_raw(self, row, col):
        cell = self.cells.get((row, col))
        return cell.raw if cell else None

    def used_bounds(self):
        if not self.cells:
            return (0, 0)
        return (max(r for r, c in self.cells) + 1, max(c for r, c in self.cells) + 1)


class Workbook:
    def __init__(self):
        self.sheets = {}
        self.sheet_order = []
        self.precedents = {}   # key -> set(keys) this cell reads
        self.dependents = {}   # key -> set(keys) that read this cell
        self.history = []      # undo stack: list of {key: (old_raw, new_raw)}
        self.future = []       # redo stack

    def add_sheet(self, name):
        if name in self.sheets:
            raise ValueError(f"sheet {name!r} already exists")
        self.sheets[name] = Sheet(name)
        self.sheet_order.append(name)
        return self.sheets[name]

    def get_or_create_sheet(self, name):
        return self.sheets.get(name) or self.add_sheet(name)

    # -- editing -----------------------------------------------------------

    def edit(self, edits):
        """edits: iterable of (sheet, row, col, raw_text_or_None). Returns
        {key: computed_value} for every cell touched by the resulting
        recalculation. Pushes one undo frame for the whole batch."""
        old_raw = {(s, r, c): self._get_raw(s, r, c) for s, r, c, _ in edits}
        changed = self._apply(edits)
        frame = {key: (old_raw[key], self._get_raw(*key)) for key in old_raw}
        self.history.append(frame)
        self.future.clear()
        return changed

    def undo(self):
        if not self.history:
            return None
        frame = self.history.pop()
        edits = [(s, r, c, old) for (s, r, c), (old, _new) in frame.items()]
        changed = self._apply(edits)
        self.future.append(frame)
        return changed

    def redo(self):
        if not self.future:
            return None
        frame = self.future.pop()
        edits = [(s, r, c, new) for (s, r, c), (_old, new) in frame.items()]
        changed = self._apply(edits)
        self.history.append(frame)
        return changed

    def _get_raw(self, sheet, row, col):
        return self.sheets[sheet].get_raw(row, col)

    def _apply(self, edits):
        touched = set()
        for sheet_name, row, col, raw in edits:
            sheet = self.get_or_create_sheet(sheet_name)
            key = (sheet_name, row, col)
            self._set_raw(sheet, key, raw)
            touched.add(key)
        dirty = self._collect_dirty(touched)
        self._recalculate(dirty)
        return {key: self._value_at(key) for key in dirty}

    def _set_raw(self, sheet, key, raw):
        _, row, col = key
        old_precedents = self.precedents.get(key, set())
        for p in old_precedents:
            self.dependents.get(p, set()).discard(key)

        if raw is None or raw == "":
            sheet.cells.pop((row, col), None)
            self.precedents.pop(key, None)
            return

        if raw.startswith("="):
            try:
                ast = parser.parse_formula(raw[1:])
                new_precedents = self._extract_precedents(ast, key[0])
            except (parser.ParseError, LexError, RangeTooLargeError):
                sheet.cells[(row, col)] = Cell(raw, None, ErrorValue(SYNTAX))
                self.precedents[key] = set()
                return
            sheet.cells[(row, col)] = Cell(raw, ast, None)
            self.precedents[key] = new_precedents
            for p in new_precedents:
                self.dependents.setdefault(p, set()).add(key)
        else:
            literal = parse_literal(raw)
            sheet.cells[(row, col)] = Cell(raw, None, literal)
            self.precedents[key] = set()

    def _extract_precedents(self, ast, owner_sheet):
        cells = set()
        for ref in walk_refs(ast):
            sheet = ref.sheet or owner_sheet
            if isinstance(ref, RangeRef):
                r1, c1 = ref.start.row, ref.start.col
                r2, c2 = ref.end.row, ref.end.col
                lo_r, hi_r = min(r1, r2), max(r1, r2)
                lo_c, hi_c = min(c1, c2), max(c1, c2)
                if (hi_r - lo_r + 1) * (hi_c - lo_c + 1) > MAX_RANGE_CELLS:
                    raise RangeTooLargeError("range too large")
                for r in range(lo_r, hi_r + 1):
                    for c in range(lo_c, hi_c + 1):
                        cells.add((sheet, r, c))
            else:
                cells.add((sheet, ref.row, ref.col))
        return cells

    # -- recalculation -------------------------------------------------------

    def _collect_dirty(self, seed_keys):
        dirty = set(seed_keys)
        queue = deque(seed_keys)
        while queue:
            key = queue.popleft()
            for dep in self.dependents.get(key, ()):
                if dep not in dirty:
                    dirty.add(dep)
                    queue.append(dep)
        return dirty

    def _recalculate(self, keys):
        indegree = {}
        for key in keys:
            indegree[key] = sum(1 for p in self.precedents.get(key, ()) if p in keys)
        queue = deque(k for k in keys if indegree[k] == 0)
        order = []
        while queue:
            key = queue.popleft()
            order.append(key)
            for dep in self.dependents.get(key, ()):
                if dep in indegree:
                    indegree[dep] -= 1
                    if indegree[dep] == 0:
                        queue.append(dep)
        for key in order:
            self._compute_one(key)
        remaining = keys - set(order)
        for key in remaining:
            self._set_value(key, ErrorValue(CIRC))

    def _compute_one(self, key):
        sheet_name, row, col = key
        sheet = self.sheets[sheet_name]
        cell = sheet.cells.get((row, col))
        if cell is None:
            return
        if cell.ast is None:
            return  # literal or syntax-error cell: computed value is fixed, no precedents
        ctx = EvalContext(self, sheet_name)
        cell.computed = evaluate(cell.ast, ctx)

    def _set_value(self, key, value):
        sheet_name, row, col = key
        cell = self.sheets[sheet_name].cells.get((row, col))
        if cell is not None:
            cell.computed = value

    def _value_at(self, key):
        sheet_name, row, col = key
        return self.sheets[sheet_name].get_computed(row, col)

    # -- full recompute oracle (used by tests + `formulate verify`) --------

    def full_recalculate(self):
        """Recompute every formula cell from scratch, ignoring the cache.
        Used to prove the incremental engine is not silently wrong."""
        all_keys = set()
        for sheet_name, sheet in self.sheets.items():
            for (row, col) in sheet.cells:
                all_keys.add((sheet_name, row, col))
        self._recalculate(all_keys)
        return {key: self._value_at(key) for key in all_keys}

    def snapshot_values(self):
        out = {}
        for sheet_name, sheet in self.sheets.items():
            for (row, col), cell in sheet.cells.items():
                out[(sheet_name, row, col)] = cell.computed
        return out

    # -- autofill ------------------------------------------------------------

    def autofill(self, sheet_name, src_row, src_col, dst_row, dst_col):
        """Compute the raw text that would land in (dst_row, dst_col) if the
        formula/value at (src_row, src_col) were drag-filled there."""
        sheet = self.sheets.get(sheet_name)
        raw = sheet.get_raw(src_row, src_col) if sheet else None
        if raw is None:
            return None
        if not raw.startswith("="):
            return raw
        cell = sheet.cells[(src_row, src_col)]
        shifted = shift_refs(cell.ast, dst_row - src_row, dst_col - src_col)
        return "=" + unparse(shifted)
