class HornError(Exception):
    """A Prolog-style error: instantiation_error, type_error, evaluation_error,
    existence_error, or a syntax error while parsing. Raised for genuine
    program bugs (unbound arithmetic operand, unknown predicate, division by
    zero) rather than ordinary goal failure, matching how ISO Prolog
    distinguishes "no" from "error"."""


class HaltSignal(Exception):
    """Raised by halt/0 and halt/1 to unwind out of the engine cleanly."""

    def __init__(self, code=0):
        super().__init__(f"halt({code})")
        self.code = code
