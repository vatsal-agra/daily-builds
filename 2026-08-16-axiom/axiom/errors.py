"""Exception types used throughout Axiom."""


class AxiomError(Exception):
    """Base class for all errors Axiom raises deliberately (never a raw
    traceback from deep inside the kernel — every user-facing entry point
    catches these and reports them cleanly)."""


class ParseError(AxiomError):
    """A syntax error while parsing a math expression, with a caret position."""

    def __init__(self, message, text=None, pos=None):
        super().__init__(message)
        self.message = message
        self.text = text
        self.pos = pos

    def __str__(self):
        if self.text is None or self.pos is None:
            return self.message
        caret = " " * self.pos + "^"
        return f"{self.message}\n  {self.text}\n  {caret}"


class DomainError(AxiomError):
    """A mathematically undefined operation (division by zero, 0**negative,
    log(0), a free symbol with no binding during numeric evaluation, etc.)."""
