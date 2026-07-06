"""Runtime value helpers shared between the evaluator and the function library."""

from .errors import ErrorValue, FormulaError


class RangeValue:
    """The result of evaluating a RangeRef: a 2D grid of scalar cell values."""

    __slots__ = ("rows",)

    def __init__(self, rows):
        self.rows = rows  # list[list[scalar]]

    def flat(self):
        return [v for row in self.rows for v in row]

    def first(self):
        if self.rows and self.rows[0]:
            return self.rows[0][0]
        return None


def flatten_args(args):
    """Flatten a mixed list of scalars / RangeValue into one flat scalar list."""
    out = []
    for a in args:
        if isinstance(a, RangeValue):
            out.extend(a.flat())
        else:
            out.append(a)
    return out


def numeric_only(values):
    """Filter a flat value list down to numbers, coercing bools, skipping blanks/text.

    Matches Excel's SUM/AVERAGE/MIN/MAX behaviour: text and empty cells inside a
    *range* argument are ignored rather than erroring, but a stray error value
    still propagates.
    """
    out = []
    for v in values:
        if isinstance(v, ErrorValue):
            raise FormulaError(v.code)
        if v is None:
            continue
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            out.append(float(v))
            continue
        # bare strings inside ranges are ignored by SUM/AVERAGE et al.
    return out
