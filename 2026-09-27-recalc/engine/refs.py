"""A1-notation cell references: column-letter <-> column-number conversion,
parsing/formatting of `$`-locked references, range expansion, and the
relative-reference translation used by copy/paste and fill.
"""

import re

CELL_RE = re.compile(r"^(\$?)([A-Za-z]{1,3})(\$?)([0-9]+)$")

MAX_COL = 18278  # ZZZ
MAX_ROW = 1_000_000


def col_to_letters(col):
    """1-based column number -> letters (1 -> 'A', 26 -> 'Z', 27 -> 'AA')."""
    if col < 1:
        raise ValueError("column must be >= 1")
    letters = ""
    n = col
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def letters_to_col(letters):
    """Letters -> 1-based column number."""
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n


class CellRef:
    """A single cell reference, e.g. A1, $A1, A$1, $A$1."""

    __slots__ = ("col", "row", "col_abs", "row_abs")

    def __init__(self, col, row, col_abs=False, row_abs=False):
        self.col = col
        self.row = row
        self.col_abs = col_abs
        self.row_abs = row_abs

    def key(self):
        return (self.col, self.row)

    def to_a1(self):
        c = ("$" if self.col_abs else "") + col_to_letters(self.col)
        r = ("$" if self.row_abs else "") + str(self.row)
        return c + r

    def translate(self, d_col, d_row):
        """Shift the *relative* components by (d_col, d_row); absolute
        ($-locked) components are left untouched. Returns a new CellRef, or
        None if the translated reference would fall off the grid (col/row
        < 1) — the caller renders that as #REF!, matching how a real
        spreadsheet handles a copy/paste (or row/column deletion) that
        would push a relative reference past the sheet edge."""
        new_col = self.col if self.col_abs else self.col + d_col
        new_row = self.row if self.row_abs else self.row + d_row
        if new_col < 1 or new_row < 1 or new_col > MAX_COL or new_row > MAX_ROW:
            return None
        return CellRef(new_col, new_row, self.col_abs, self.row_abs)

    def __eq__(self, other):
        return (
            isinstance(other, CellRef)
            and self.col == other.col
            and self.row == other.row
            and self.col_abs == other.col_abs
            and self.row_abs == other.row_abs
        )

    def __repr__(self):
        return f"CellRef({self.to_a1()})"


class RangeRef:
    """A rectangular range between two corners, e.g. A1:B10. Corners are
    stored exactly as written (so `$` locking round-trips) but are not
    assumed to be in top-left/bottom-right order."""

    __slots__ = ("start", "end")

    def __init__(self, start, end):
        self.start = start
        self.end = end

    def to_a1(self):
        return f"{self.start.to_a1()}:{self.end.to_a1()}"

    def normalized_bounds(self):
        """(min_col, min_row, max_col, max_row), tolerating either corner
        order (e.g. B2:A1 is the same range as A1:B2)."""
        c1, r1 = self.start.col, self.start.row
        c2, r2 = self.end.col, self.end.row
        return (min(c1, c2), min(r1, r2), max(c1, c2), max(r1, r2))

    def cells(self):
        """All (col, row) pairs in the range, row-major."""
        min_c, min_r, max_c, max_r = self.normalized_bounds()
        out = []
        for r in range(min_r, max_r + 1):
            for c in range(min_c, max_c + 1):
                out.append((c, r))
        return out

    def translate(self, d_col, d_row):
        new_start = self.start.translate(d_col, d_row)
        new_end = self.end.translate(d_col, d_row)
        if new_start is None or new_end is None:
            return None
        return RangeRef(new_start, new_end)

    def __repr__(self):
        return f"RangeRef({self.to_a1()})"


def parse_cell_ref(text):
    """Parse a single-cell A1-notation reference. Returns a CellRef or
    raises ValueError."""
    m = CELL_RE.match(text)
    if not m:
        raise ValueError(f"not a cell reference: {text!r}")
    col_abs = m.group(1) == "$"
    col = letters_to_col(m.group(2))
    row_abs = m.group(3) == "$"
    row = int(m.group(4))
    if row < 1 or col < 1 or col > MAX_COL:
        raise ValueError(f"reference out of range: {text!r}")
    return CellRef(col, row, col_abs, row_abs)


def looks_like_cell_ref(text):
    return bool(CELL_RE.match(text))
