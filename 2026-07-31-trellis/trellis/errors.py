"""Typed error values that flow through formula evaluation like any other
value, instead of raising Python exceptions out of the evaluator."""

DIV0 = "#DIV/0!"
VALUE = "#VALUE!"
REF = "#REF!"
NAME = "#NAME?"
CIRCULAR = "#CIRCULAR!"
NUM = "#NUM!"
NA = "#N/A"

ALL_CODES = {DIV0, VALUE, REF, NAME, CIRCULAR, NUM, NA}


class TrellisError(Exception):
    """A spreadsheet error *value*. Subclasses Exception so evaluator code
    can `raise TrellisError(...)` and have it caught at the cell boundary,
    but every caught instance is also stored and displayed as a first-class
    cell value (mirrors how real spreadsheets treat #DIV/0! etc. as values
    that propagate through formulas, not crashes)."""

    def __init__(self, code):
        assert code in ALL_CODES, f"unknown error code {code!r}"
        self.code = code
        super().__init__(code)

    def __eq__(self, other):
        return isinstance(other, TrellisError) and self.code == other.code

    def __hash__(self):
        return hash(("TrellisError", self.code))

    def __repr__(self):
        return f"TrellisError({self.code})"

    def __str__(self):
        return self.code
