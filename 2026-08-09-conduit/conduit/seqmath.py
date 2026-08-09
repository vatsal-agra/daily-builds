"""32-bit serial-number arithmetic (RFC 1982 style) for sequence numbers.

Sequence numbers wrap at 2**32. `seq_diff(a, b)` returns the signed
difference `a - b` as if both were points on a 32-bit circle, which is
what lets comparisons like "has this ACK advanced past this segment"
stay correct across a wraparound. Real TCP stacks do exactly this.
"""

_MOD = 1 << 32
_HALF = 1 << 31


def seq_diff(a: int, b: int) -> int:
    d = (a - b) & (_MOD - 1)
    if d >= _HALF:
        d -= _MOD
    return d


def seq_lt(a: int, b: int) -> bool:
    return seq_diff(a, b) < 0


def seq_le(a: int, b: int) -> bool:
    return seq_diff(a, b) <= 0


def seq_ge(a: int, b: int) -> bool:
    return seq_diff(a, b) >= 0
