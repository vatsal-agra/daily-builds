"""AST node types produced by the parser and consumed by the evaluator and
the dependency-graph reference extractor."""


class Node:
    __slots__ = ()


class NumberLit(Node):
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"NumberLit({self.value})"


class StringLit(Node):
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"StringLit({self.value!r})"


class BoolLit(Node):
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"BoolLit({self.value})"


class CellRef(Node):
    """A single-cell reference, e.g. `A1`, `$A$1`, `Sheet2!A1`."""

    __slots__ = ("sheet", "row", "col", "row_abs", "col_abs", "text")

    def __init__(self, sheet, row, col, row_abs=False, col_abs=False, text=None):
        self.sheet = sheet
        self.row = row
        self.col = col
        self.row_abs = row_abs
        self.col_abs = col_abs
        self.text = text

    def __repr__(self):
        return f"CellRef({self.sheet!r}, r={self.row}, c={self.col})"


class RangeRef(Node):
    """A rectangular range reference, e.g. `A1:B10`."""

    __slots__ = ("sheet", "start", "end")

    def __init__(self, sheet, start, end):
        self.sheet = sheet
        self.start = start  # CellRef
        self.end = end      # CellRef

    def __repr__(self):
        return f"RangeRef({self.sheet!r}, {self.start!r}:{self.end!r})"


class UnaryOp(Node):
    __slots__ = ("op", "operand")

    def __init__(self, op, operand):
        self.op = op
        self.operand = operand

    def __repr__(self):
        return f"UnaryOp({self.op!r}, {self.operand!r})"


class BinOp(Node):
    __slots__ = ("op", "left", "right")

    def __init__(self, op, left, right):
        self.op = op
        self.left = left
        self.right = right

    def __repr__(self):
        return f"BinOp({self.op!r}, {self.left!r}, {self.right!r})"


class FuncCall(Node):
    __slots__ = ("name", "args")

    def __init__(self, name, args):
        self.name = name
        self.args = args

    def __repr__(self):
        return f"FuncCall({self.name!r}, {self.args!r})"
