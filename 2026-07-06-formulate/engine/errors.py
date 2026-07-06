"""Excel-style formula error values and value coercion helpers.

A formula error is a first-class value (like Excel's #DIV/0!), not a Python
exception that unwinds the stack — arithmetic and functions that touch an
error value propagate it rather than raising, matching how a real
spreadsheet behaves. `FormulaError` is only raised internally within a
single function's evaluation and immediately caught by the evaluator, which
turns it into the corresponding error *value*.
"""


class FormulaError(Exception):
    """Raised during evaluation; caught by the evaluator and converted to an ErrorValue."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class ErrorValue:
    """A propagating error value, e.g. #DIV/0!, #VALUE!, #REF!, #NAME?, #N/A, #CIRC!."""

    __slots__ = ("code",)

    def __init__(self, code):
        self.code = code

    def __eq__(self, other):
        return isinstance(other, ErrorValue) and self.code == other.code

    def __hash__(self):
        return hash(("ErrorValue", self.code))

    def __repr__(self):
        return self.code

    def __str__(self):
        return self.code


DIV0 = "#DIV/0!"
VALUE = "#VALUE!"
NAME = "#NAME?"
REF = "#REF!"
NA = "#N/A"
CIRC = "#CIRC!"
NUM = "#NUM!"


def to_number(value):
    """Coerce a formula value to a float, or raise FormulaError(#VALUE!)."""
    if isinstance(value, ErrorValue):
        raise FormulaError(value.code)
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if s == "":
            return 0.0
        try:
            return float(s)
        except ValueError:
            raise FormulaError(VALUE)
    raise FormulaError(VALUE)


def to_string(value):
    if isinstance(value, ErrorValue):
        raise FormulaError(value.code)
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        if value == int(value) and abs(value) < 1e15:
            return str(int(value))
        return repr(value)
    return str(value)


def to_bool(value):
    if isinstance(value, ErrorValue):
        raise FormulaError(value.code)
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        s = value.strip().upper()
        if s == "TRUE":
            return True
        if s == "FALSE":
            return False
        raise FormulaError(VALUE)
    raise FormulaError(VALUE)
