class EmberRuntimeError(Exception):
    """Raised for well-defined runtime failures (undefined var/fn, div by
    zero, INT64_MIN / -1 overflow, ...). Both the interpreter and the JIT
    are required to raise exactly this for exactly these conditions, so a
    program's error behavior is part of what the differential harness
    checks -- a JIT that silently miscomputes on division by zero instead
    of raising would be caught, not just one that returns the wrong
    number on ordinary input.
    """
