"""Proof-of-work target math and Bitcoin-style difficulty retargeting.

Difficulty is represented directly as a 256-bit integer target T: a block
header is valid proof-of-work iff int(sha256d(header_bytes)) <= T. Smaller
T = harder. This is target space, the same quantity Bitcoin's compact
`nBits` encodes, just not bit-packed — no need for that encoding's edge
cases in a from-scratch toy chain.
"""

MAX_TARGET = (1 << 256) - 1

# kept low so a full demo (mine several blocks, retarget, run a network)
# finishes in seconds on a single dev box, not real-world ASIC difficulty.
# At ~150K header-hashes/sec (pure-Python JSON + double-SHA256), this
# averages ~65536 attempts -> well under a second per block for one miner.
GENESIS_TARGET = MAX_TARGET >> 16

RETARGET_INTERVAL = 5      # blocks between difficulty adjustments
TARGET_BLOCK_SECONDS = 1   # desired average seconds per block
MAX_ADJUSTMENT_FACTOR = 4  # clamp swings to 4x up or down, same spirit as Bitcoin's clamp


def target_to_difficulty(target: int) -> float:
    """A human-readable relative-difficulty number, 1.0 at genesis target."""
    return GENESIS_TARGET / target


def meets_target(block_hash: bytes, target: int) -> bool:
    return int.from_bytes(block_hash, "big") <= target


def next_target(prev_target: int, actual_seconds: float, n_blocks: int) -> int:
    """actual_seconds: real wall-clock time the last `n_blocks` took.
    Slower than expected -> raise target (easier). Faster -> lower target
    (harder). Clamped so one retarget can't swing more than 4x either way."""
    expected_seconds = TARGET_BLOCK_SECONDS * n_blocks
    if actual_seconds <= 0:
        actual_seconds = 0.001
    factor = actual_seconds / expected_seconds
    factor = max(1 / MAX_ADJUSTMENT_FACTOR, min(MAX_ADJUSTMENT_FACTOR, factor))
    new_target = int(prev_target * factor)
    return max(1, min(MAX_TARGET, new_target))
