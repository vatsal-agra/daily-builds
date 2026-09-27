"""Runtime value model: Number (float), Text (str), Bool (bool), Blank (None),
and Error (a str subclass carrying an Excel-style error code), plus the
coercion rules the evaluator and function library share.
"""

import math


class Error(str):
    """A spreadsheet error value. Subclasses str so it prints/serializes as
    its own error code, but must be distinguished from ordinary text via
    isinstance(v, Error) *before* any isinstance(v, str) check, since it is
    also a str.
    """
    __slots__ = ()


DIV0 = Error("#DIV/0!")
VALUE = Error("#VALUE!")
REF = Error("#REF!")
NAME = Error("#NAME?")
NA = Error("#N/A")
NUM = Error("#NUM!")
CYCLE = Error("#CYCLE!")

ALL_ERRORS = (DIV0, VALUE, REF, NAME, NA, NUM, CYCLE)


def is_error(v):
    return isinstance(v, Error)


def is_blank(v):
    return v is None


def first_error(*values):
    """Excel propagates the first error value it encounters left-to-right;
    flatten any nested lists (from ranges) in the same order."""
    for v in values:
        if isinstance(v, list):
            e = first_error(*v)
            if e is not None:
                return e
        elif is_error(v):
            return v
    return None


def to_number(v):
    """Coerce a scalar value to a float, or an Error."""
    if is_error(v):
        return v
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, float):
        return v
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return 0.0
        try:
            return float(s)
        except ValueError:
            return VALUE
    return VALUE


def to_text(v):
    """Coerce a scalar value to its display text."""
    if is_error(v):
        return v
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        return format_number(v)
    if isinstance(v, str):
        return v
    return str(v)


def to_bool(v):
    """Coerce a scalar value to a bool, or an Error."""
    if is_error(v):
        return v
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        return v != 0.0
    if isinstance(v, str):
        s = v.strip().upper()
        if s == "TRUE":
            return True
        if s == "FALSE":
            return False
        return VALUE
    return VALUE


def format_number(x):
    """Render a float the way a spreadsheet cell would: no trailing '.0'
    for integral values, otherwise a compact general-format representation."""
    if isinstance(x, Error):
        return x
    if math.isnan(x) or math.isinf(x):
        return NUM
    if x == 0:
        x = 0.0  # normalize -0.0
    if x == int(x) and abs(x) < 1e15:
        return str(int(x))
    s = f"{x:.10g}"
    return s.replace("e", "E")  # Excel's own scientific-notation style


def display(v):
    """Render any runtime value as the text a cell would show."""
    if is_error(v):
        return str(v)
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        return format_number(v)
    if isinstance(v, str):
        return v
    return str(v)


def flatten(args):
    """Flatten a mix of scalars and 2D range lists (list-of-rows-of-cells)
    into a single flat list of scalar values, in left-to-right, row-major
    order."""
    out = []
    for a in args:
        if isinstance(a, list):
            for row in a:
                if isinstance(row, list):
                    out.extend(row)
                else:
                    out.append(row)
        else:
            out.append(a)
    return out
