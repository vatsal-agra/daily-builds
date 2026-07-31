"""Cell-address parsing/formatting: A1-style <-> (row, col) 1-indexed pairs,
plus optional `Sheet!` prefixes for cross-sheet references."""

import re

from .errors import TrellisError, REF

_ADDR_RE = re.compile(r"^(\$?)([A-Za-z]+)(\$?)(\d+)$")
_REF_RE = re.compile(
    r"^(?:([A-Za-z_][A-Za-z0-9_ ]*)!)?"          # optional Sheet! / 'My Sheet'!
    r"(\$?[A-Za-z]+\$?\d+)(?::(\$?[A-Za-z]+\$?\d+))?$"
)


def col_to_index(letters):
    """'A' -> 1, 'Z' -> 26, 'AA' -> 27 ..."""
    letters = letters.upper()
    n = 0
    for ch in letters:
        if not ("A" <= ch <= "Z"):
            raise ValueError(f"bad column letters: {letters!r}")
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n


def index_to_col(n):
    """27 -> 'AA' ..."""
    if n < 1:
        raise ValueError(f"column index must be >= 1, got {n}")
    letters = []
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters.append(chr(ord("A") + rem))
    return "".join(reversed(letters))


def parse_addr(text):
    """'A1' / '$A$1' -> (row, col) both 1-indexed. Raises ValueError on bad
    syntax; the caller decides whether that becomes #REF!/#NAME?."""
    m = _ADDR_RE.match(text.strip())
    if not m:
        raise ValueError(f"not a cell address: {text!r}")
    _, col_letters, _, row_digits = m.groups()
    return int(row_digits), col_to_index(col_letters)


def format_addr(row, col):
    if row < 1 or col < 1:
        raise TrellisError(REF)
    return f"{index_to_col(col)}{row}"


def split_ref(text):
    """Split a possibly-sheet-qualified, possibly-range reference into
    (sheet_name_or_None, start_addr_text, end_addr_text_or_None)."""
    m = _REF_RE.match(text.strip())
    if not m:
        raise ValueError(f"not a reference: {text!r}")
    return m.group(1), m.group(2), m.group(3)
