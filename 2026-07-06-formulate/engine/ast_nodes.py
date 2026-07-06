"""AST node types for parsed formulas, plus an unparser (AST -> formula text).

The unparser exists because autofill needs to take an existing formula,
shift its relative references by a row/col delta, and produce new formula
text — without re-deriving a serialization format by hand at each call site.
"""

from dataclasses import dataclass, field


@dataclass
class Number:
    value: float


@dataclass
class String:
    value: str


@dataclass
class Bool:
    value: bool


@dataclass
class CellRef:
    sheet: str          # None means "current sheet"
    col: int             # 0-based column index
    row: int              # 0-based row index
    col_abs: bool
    row_abs: bool


@dataclass
class RangeRef:
    sheet: str
    start: CellRef
    end: CellRef


@dataclass
class FuncCall:
    name: str
    args: list = field(default_factory=list)


@dataclass
class UnaryOp:
    op: str   # '-'
    operand: object


@dataclass
class PostfixOp:
    op: str   # '%'
    operand: object


@dataclass
class BinOp:
    op: str   # '+','-','*','/','^','&','=','<>','<','<=','>','>='
    left: object
    right: object


def col_to_letters(col):
    """0-based column index -> spreadsheet letters (0 -> A, 25 -> Z, 26 -> AA)."""
    col += 1
    letters = ""
    while col > 0:
        col, rem = divmod(col - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def letters_to_col(letters):
    """Spreadsheet letters -> 0-based column index."""
    col = 0
    for ch in letters:
        col = col * 26 + (ord(ch.upper()) - ord("A") + 1)
    return col - 1


def format_cellref(ref):
    text = ""
    if ref.col_abs:
        text += "$"
    text += col_to_letters(ref.col)
    if ref.row_abs:
        text += "$"
    text += str(ref.row + 1)
    if ref.sheet:
        text = f"{ref.sheet}!{text}"
    return text


def unparse(node):
    """Render an AST node back to formula text (no leading '=')."""
    if isinstance(node, Number):
        v = node.value
        if v == int(v) and abs(v) < 1e15:
            return str(int(v))
        return repr(v)
    if isinstance(node, String):
        return '"' + node.value.replace('"', '""') + '"'
    if isinstance(node, Bool):
        return "TRUE" if node.value else "FALSE"
    if isinstance(node, CellRef):
        return format_cellref(node)
    if isinstance(node, RangeRef):
        start = format_cellref(node.start)
        end_ref = CellRef(None, node.end.col, node.end.row, node.end.col_abs, node.end.row_abs)
        end = format_cellref(end_ref)
        text = f"{start}:{end}"
        if node.sheet:
            text = f"{node.sheet}!{text}"
        return text
    if isinstance(node, FuncCall):
        return f"{node.name}(" + ",".join(unparse(a) for a in node.args) + ")"
    if isinstance(node, UnaryOp):
        return f"{node.op}{_maybe_paren(node, node.operand)}"
    if isinstance(node, PostfixOp):
        return f"{_maybe_paren(node, node.operand)}{node.op}"
    if isinstance(node, BinOp):
        return f"{_maybe_paren(node, node.left)}{node.op}{_maybe_paren(node, node.right)}"
    raise TypeError(f"cannot unparse {node!r}")


# Matches Excel's real precedence order: % > ^ > unary- > * / > + - > & > comparisons.
_PRECEDENCE = {
    "%": 6, "^": 5, "unary-": 4, "*": 3, "/": 3, "+": 2, "-": 2, "&": 1,
    "=": 0, "<>": 0, "<": 0, "<=": 0, ">": 0, ">=": 0,
}


def _prec_of(node):
    if isinstance(node, BinOp):
        return _PRECEDENCE[node.op]
    if isinstance(node, UnaryOp):
        return _PRECEDENCE["unary-"]
    if isinstance(node, PostfixOp):
        return _PRECEDENCE["%"]
    return 100


def _prec_of_parent(parent):
    if isinstance(parent, BinOp):
        return _PRECEDENCE[parent.op]
    if isinstance(parent, UnaryOp):
        return _PRECEDENCE["unary-"]
    if isinstance(parent, PostfixOp):
        return _PRECEDENCE["%"]
    return -1


def _maybe_paren(parent, child):
    text = unparse(child)
    if _prec_of(child) < _prec_of_parent(parent):
        return f"({text})"
    return text


def walk_refs(node):
    """Yield every CellRef / RangeRef node reachable from `node`."""
    if isinstance(node, (CellRef, RangeRef)):
        yield node
    elif isinstance(node, FuncCall):
        for a in node.args:
            yield from walk_refs(a)
    elif isinstance(node, (UnaryOp, PostfixOp)):
        yield from walk_refs(node.operand)
    elif isinstance(node, BinOp):
        yield from walk_refs(node.left)
        yield from walk_refs(node.right)


def shift_refs(node, row_delta, col_delta):
    """Return a deep copy of `node` with all *relative* refs shifted.

    Absolute components ($-pinned) are left untouched. Used by autofill.
    """
    if isinstance(node, Number):
        return Number(node.value)
    if isinstance(node, String):
        return String(node.value)
    if isinstance(node, Bool):
        return Bool(node.value)
    if isinstance(node, CellRef):
        return _shift_cellref(node, row_delta, col_delta)
    if isinstance(node, RangeRef):
        return RangeRef(
            node.sheet,
            _shift_cellref(node.start, row_delta, col_delta),
            _shift_cellref(node.end, row_delta, col_delta),
        )
    if isinstance(node, FuncCall):
        return FuncCall(node.name, [shift_refs(a, row_delta, col_delta) for a in node.args])
    if isinstance(node, UnaryOp):
        return UnaryOp(node.op, shift_refs(node.operand, row_delta, col_delta))
    if isinstance(node, PostfixOp):
        return PostfixOp(node.op, shift_refs(node.operand, row_delta, col_delta))
    if isinstance(node, BinOp):
        return BinOp(node.op, shift_refs(node.left, row_delta, col_delta),
                     shift_refs(node.right, row_delta, col_delta))
    raise TypeError(f"cannot shift {node!r}")


def _shift_cellref(ref, row_delta, col_delta):
    row = ref.row if ref.row_abs else ref.row + row_delta
    col = ref.col if ref.col_abs else ref.col + col_delta
    return CellRef(ref.sheet, col, row, ref.col_abs, ref.row_abs)
