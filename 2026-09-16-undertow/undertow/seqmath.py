"""RFC 1982 serial-number arithmetic over a 32-bit sequence-number space.

Every module that compares sequence numbers (the sliding window, the
receiver's out-of-order buffer, congestion-window "bytes in flight" math)
goes through here instead of plain ``<``/``-``, because a live connection's
sequence number wraps past 2**32-1 and plain integer comparison silently
breaks the instant it does.
"""

SEQ_BITS = 32
SEQ_MOD = 1 << SEQ_BITS
SEQ_HALF = SEQ_MOD // 2
SEQ_MASK = SEQ_MOD - 1


def seq_add(a: int, n: int) -> int:
    """a + n, wrapped into [0, 2**32)."""
    return (a + n) & SEQ_MASK


def seq_diff(a: int, b: int) -> int:
    """Signed distance b - a in serial-number space, in (-2**31, 2**31].

    Positive means b is "after" a; negative means b is "before" a. This is
    what window/inflight arithmetic uses instead of plain subtraction.
    """
    d = (b - a) & SEQ_MASK
    if d > SEQ_HALF:
        d -= SEQ_MOD
    return d


def seq_lt(a: int, b: int) -> bool:
    """True iff a comes strictly before b in serial-number order."""
    return seq_diff(a, b) > 0


def seq_le(a: int, b: int) -> bool:
    return a == b or seq_lt(a, b)


def seq_gt(a: int, b: int) -> bool:
    return seq_lt(b, a)


def seq_ge(a: int, b: int) -> bool:
    return seq_le(b, a)
