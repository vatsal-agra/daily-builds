"""Proof-of-work target <-> compact "bits" encoding (Bitcoin's nBits
format) and the difficulty retarget algorithm.

Compact encoding packs an arbitrary-precision target into 4 bytes:
the top byte is an exponent (in bytes), the bottom 3 bytes are the
mantissa. target = mantissa * 256**(exponent - 3).
"""

MAX_TARGET = (1 << 250) - 1  # genesis difficulty: ~2^6 expected hashes/block, fast in a
# pure-Python demo miner (~3-4k h/s) yet still real grinding, not a rubber-stamp check

# Demo-scaled retarget parameters (Bitcoin retargets every 2016 blocks
# toward a 10-minute block time; compressed here to a much shorter window
# so a retarget is actually observable in a same-day demo run).
RETARGET_INTERVAL = 10          # blocks between retargets
TARGET_BLOCK_TIME_SECONDS = 2   # demo block time
MAX_ADJUSTMENT_FACTOR = 4       # clamp any single retarget to [1/4x, 4x], as Bitcoin does


def target_to_bits(target: int) -> int:
    if target <= 0:
        raise ValueError("target must be positive")
    raw = target.to_bytes(32, "big").lstrip(b"\x00")
    if not raw:
        raw = b"\x00"
    if raw[0] & 0x80:
        # top bit set would be read as a sign bit in Bitcoin's convention;
        # pad with a leading zero byte
        raw = b"\x00" + raw
    exponent = len(raw)
    mantissa = raw[:3]
    if len(mantissa) < 3:
        mantissa = mantissa + b"\x00" * (3 - len(mantissa))
    return (exponent << 24) | int.from_bytes(mantissa, "big")


def bits_to_target(bits: int) -> int:
    exponent = bits >> 24
    mantissa = bits & 0xFFFFFF
    if exponent <= 3:
        return mantissa >> (8 * (3 - exponent))
    return mantissa << (8 * (exponent - 3))


def next_bits(prev_bits: int, height_after_prev: int, actual_timespan: int) -> int:
    """Called for the block at height `height_after_prev + 1`. Only
    retargets every RETARGET_INTERVAL blocks; otherwise the target is
    unchanged. actual_timespan is the wall-clock seconds the last
    RETARGET_INTERVAL blocks actually took."""
    next_height = height_after_prev + 1
    if next_height % RETARGET_INTERVAL != 0:
        return prev_bits

    expected_timespan = RETARGET_INTERVAL * TARGET_BLOCK_TIME_SECONDS
    lo = expected_timespan // MAX_ADJUSTMENT_FACTOR
    hi = expected_timespan * MAX_ADJUSTMENT_FACTOR
    clamped = max(lo, min(hi, actual_timespan))

    prev_target = bits_to_target(prev_bits)
    new_target = (prev_target * clamped) // expected_timespan
    new_target = max(1, min(MAX_TARGET, new_target))
    return target_to_bits(new_target)


def work_for_bits(bits: int) -> int:
    """'Chainwork' contributed by one block at this difficulty: higher for
    a smaller target, so cumulative work — not just chain length — is
    the tie-breaker between competing forks (exactly like real Bitcoin)."""
    target = bits_to_target(bits)
    return ((1 << 256) // (target + 1))
