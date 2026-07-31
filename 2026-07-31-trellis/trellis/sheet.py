"""The public data model: `Cell`, `Sheet` (a grid of cells), and
`Workbook` (named sheets sharing one dependency graph + recalculation
engine). This is the module application code (CLI, server, tests) talks to.
"""

from .parser import parse, ParseError
from .ast_nodes import CellRef, RangeRef, FuncCall, UnaryOp, BinOp
from .evaluator import evaluate, Context
from .depgraph import DependencyGraph
from .errors import TrellisError, REF, VALUE, CIRCULAR


def _literal_from_text(text):
    """Non-formula cell content -> a typed literal value."""
    stripped = text.strip()
    if stripped == "":
        return None
    upper = stripped.upper()
    if upper == "TRUE":
        return True
    if upper == "FALSE":
        return False
    try:
        if any(c in stripped for c in ".eE") and stripped.lower() not in ("inf", "-inf", "nan"):
            return float(stripped)
        return int(stripped)
    except ValueError:
        try:
            return float(stripped)
        except ValueError:
            return text


class Cell:
    """One grid cell. `raw` is exactly what the user typed (or None for an
    empty cell); `value` is the computed display value (kept in sync by the
    Workbook's recalculation engine, never computed lazily by this class)."""

    __slots__ = ("raw", "ast", "value", "is_formula")

    def __init__(self):
        self.raw = None
        self.ast = None
        self.value = None
        self.is_formula = False

    def is_empty(self):
        return self.raw is None

    def to_dict(self):
        val = self.value
        err = val.code if isinstance(val, TrellisError) else None
        return {
            "raw": self.raw,
            "formula": self.raw if self.is_formula else None,
            "value": None if err else val,
            "error": err,
            "is_formula": self.is_formula,
        }


class Sheet:
    def __init__(self, name):
        self.name = name
        self.cells = {}  # (row, col) -> Cell

    def get(self, row, col):
        return self.cells.get((row, col))

    def get_or_create(self, row, col):
        key = (row, col)
        cell = self.cells.get(key)
        if cell is None:
            cell = Cell()
            self.cells[key] = cell
        return cell

    def dimensions(self):
        if not self.cells:
            return (0, 0)
        rows = [r for r, c in self.cells if self.cells[(r, c)].raw is not None]
        cols = [c for r, c in self.cells if self.cells[(r, c)].raw is not None]
        if not rows:
            return (0, 0)
        return (max(rows), max(cols))


class _WorkbookContext(Context):
    def __init__(self, workbook, current_sheet):
        self.workbook = workbook
        self.current_sheet = current_sheet

    def get_value(self, sheet_name, row, col):
        sheet = self.workbook.sheets.get(sheet_name or self.current_sheet)
        if sheet is None:
            raise TrellisError(REF)
        if row < 1 or col < 1:
            raise TrellisError(REF)
        cell = sheet.get(row, col)
        if cell is None:
            return None
        val = cell.value
        if isinstance(val, TrellisError):
            raise val
        return val


class Workbook:
    """A collection of named sheets sharing one dependency graph. Cell
    identity in the graph is `(sheet_name, row, col)`."""

    def __init__(self):
        self.sheets = {}
        self.graph = DependencyGraph()
        self.eval_count = 0
        self.add_sheet("Sheet1")
        self.active_sheet = "Sheet1"

    # -- sheet management -------------------------------------------------

    def add_sheet(self, name):
        if name in self.sheets:
            raise ValueError(f"sheet {name!r} already exists")
        self.sheets[name] = Sheet(name)
        return self.sheets[name]

    def rename_sheet(self, old, new):
        if old not in self.sheets:
            raise KeyError(old)
        if new in self.sheets:
            raise ValueError(f"sheet {new!r} already exists")
        sheet = self.sheets.pop(old)
        sheet.name = new
        self.sheets[new] = sheet

        remap = {}
        for key in list(self.graph.precedents.keys()) + list(self.graph.dependents.keys()):
            if key[0] == old:
                remap[key] = (new, key[1], key[2])
        for old_key, new_key in remap.items():
            self.graph.precedents[new_key] = {
                (new, r, c) if s == old else (s, r, c) for (s, r, c) in self.graph.precedents.pop(old_key, set())
            }
            self.graph.dependents[new_key] = {
                (new, r, c) if s == old else (s, r, c) for (s, r, c) in self.graph.dependents.pop(old_key, set())
            }
        if self.active_sheet == old:
            self.active_sheet = new
        self._recalc_all()

    def remove_sheet(self, name):
        if name not in self.sheets:
            raise KeyError(name)
        if len(self.sheets) == 1:
            raise ValueError("cannot remove the last sheet")
        del self.sheets[name]
        for key in [k for k in self.graph.precedents if k[0] == name]:
            self.graph.remove_cell(key)
        for key in [k for k in self.graph.dependents if k[0] == name]:
            self.graph.remove_cell(key)
        if self.active_sheet == name:
            self.active_sheet = next(iter(self.sheets))
        self._recalc_all()

    # -- editing ------------------------------------------------------------

    def set_cell(self, sheet_name, row, col, raw_text):
        """Set a cell's raw content (formula text starting with '=', or a
        literal). Returns the set of (sheet, row, col) keys that were
        recomputed as a result (for the API to report back)."""
        sheet = self.sheets[sheet_name]
        cell = sheet.get_or_create(row, col)
        key = (sheet_name, row, col)

        if raw_text is None or raw_text == "":
            cell.raw = None
            cell.ast = None
            cell.is_formula = False
            cell.value = None
            self.graph.set_precedents(key, set())
            return self._recalculate([key])

        cell.raw = raw_text
        if raw_text.startswith("="):
            try:
                ast = parse(raw_text[1:])
            except ParseError:
                cell.ast = None
                cell.is_formula = True
                cell.value = TrellisError(VALUE)
                self.graph.set_precedents(key, set())
                return self._recalculate([key])
            cell.ast = ast
            cell.is_formula = True
            refs = _extract_refs(ast, sheet_name)
            self.graph.set_precedents(key, refs)
        else:
            cell.ast = None
            cell.is_formula = False
            cell.value = _literal_from_text(raw_text)
            self.graph.set_precedents(key, set())

        return self._recalculate([key])

    def get_cell(self, sheet_name, row, col):
        return self.sheets[sheet_name].get(row, col)

    # -- recalculation --------------------------------------------------

    def _recalculate(self, changed_keys):
        affected = self.graph.affected_closure(changed_keys)
        cycles = self.graph.find_cycles()
        cyclic = affected & cycles

        for key in cyclic:
            sheet, row, col = key
            cell = self.sheets[sheet].get(row, col)
            if cell is not None:
                cell.value = TrellisError(CIRCULAR)

        non_cyclic = affected - cyclic
        order = self.graph.topological_order(non_cyclic)
        for key in order:
            sheet_name, row, col = key
            cell = self.sheets[sheet_name].get(row, col)
            if cell is None or not cell.is_formula:
                continue
            self.eval_count += 1
            if cell.ast is None:
                cell.value = TrellisError(VALUE)
                continue
            ctx = _WorkbookContext(self, sheet_name)
            try:
                cell.value = evaluate(cell.ast, ctx)
            except TrellisError as e:
                cell.value = e
        return affected

    def recalc_all_cells(self):
        """Force a full recompute of every formula cell in the workbook
        (used after bulk-loading, e.g. CSV import of many formulas, or
        after a sheet rename/removal that reshapes the graph's keys)."""
        all_formula_keys = {
            (s.name, r, c)
            for s in self.sheets.values()
            for (r, c), cell in s.cells.items()
            if cell.is_formula
        }
        return self._recalculate(all_formula_keys)

    _recalc_all = recalc_all_cells


def _extract_refs(node, current_sheet):
    """Collect every individual (sheet, row, col) a formula's AST reads,
    expanding range references to every cell they cover."""
    out = set()
    _walk_refs(node, current_sheet, out)
    return out


def _walk_refs(node, current_sheet, out):
    if isinstance(node, CellRef):
        sheet = node.sheet or current_sheet
        out.add((sheet, node.row, node.col))
    elif isinstance(node, RangeRef):
        sheet = node.sheet or current_sheet
        r1, r2 = sorted((node.start.row, node.end.row))
        c1, c2 = sorted((node.start.col, node.end.col))
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                out.add((sheet, r, c))
    elif isinstance(node, UnaryOp):
        _walk_refs(node.operand, current_sheet, out)
    elif isinstance(node, BinOp):
        _walk_refs(node.left, current_sheet, out)
        _walk_refs(node.right, current_sheet, out)
    elif isinstance(node, FuncCall):
        for a in node.args:
            _walk_refs(a, current_sheet, out)
    # NumberLit / StringLit / BoolLit / NameRef: no references
