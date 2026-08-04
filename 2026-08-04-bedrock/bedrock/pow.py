"""Proof-of-work mining and difficulty retargeting.

The target is stored as a raw 256-bit integer rather than Bitcoin's packed
float-like "bits" encoding — a deliberate simplification (documented in
PLAN.md) that keeps the retargeting math exact instead of going through a
lossy compact re-encoding, while still being real, continuously adjustable
proof-of-work difficulty.
"""

import time

# A block is valid once int(block_hash, 16) < target: a *smaller* target
# means fewer valid hashes means more work required to find one.
CEILING_TARGET = 1 << 255       # loosest allowed target (easiest difficulty)
FLOOR_TARGET = 1                 # tightest allowed target (hardest difficulty)

# Tuned for a demo/test run to finish in seconds, not minutes: ~2^16 hashes
# per block on average at the initial difficulty.
INITIAL_TARGET = 1 << 240
TARGET_BLOCK_TIME = 2            # seconds
RETARGET_INTERVAL = 10           # blocks
MAX_ADJUSTMENT_FACTOR = 4.0      # clamp swings exactly like Bitcoin's 4x cap


class MiningTimeout(Exception):
    pass


def meets_target(block_hash_hex: str, target: int) -> bool:
    return int(block_hash_hex, 16) < target


def mine(header, max_nonce: int = None, deadline: float = None):
    """Search nonce space until header.hash meets header.target. Mutates and
    returns `header` with a winning nonce set. Raises MiningTimeout if
    max_nonce/deadline is exceeded first (used by tests and interruptible
    network mining loops)."""
    nonce = 0
    while True:
        header.nonce = nonce
        if meets_target(header.hash, header.target):
            return header
        nonce += 1
        if max_nonce is not None and nonce > max_nonce:
            raise MiningTimeout(f"no valid nonce found within {max_nonce} tries")
        if deadline is not None and time.time() > deadline:
            raise MiningTimeout("mining deadline exceeded")


def compute_next_target(prev_target: int, actual_time_span: float, expected_time_span: float) -> int:
    """Standard Bitcoin-style retarget: scale the target by how far actual
    block-finding time deviated from the expected schedule, clamped to
    prevent a single retarget from swinging difficulty more than 4x."""
    if actual_time_span <= 0:
        actual_time_span = 1  # guard against a zero/negative clock span
    ratio = actual_time_span / expected_time_span
    ratio = max(1.0 / MAX_ADJUSTMENT_FACTOR, min(MAX_ADJUSTMENT_FACTOR, ratio))
    new_target = int(prev_target * ratio)
    return max(FLOOR_TARGET, min(new_target, CEILING_TARGET))


def target_for_height(heights_and_headers, height: int, prev_target: int) -> int:
    """Given (height -> BlockHeader) lookups for the chain up to `height - 1`,
    return the target the block at `height` must satisfy. Retargets every
    RETARGET_INTERVAL blocks; otherwise inherits the previous block's target."""
    if height == 0:
        return INITIAL_TARGET
    if height % RETARGET_INTERVAL != 0:
        return prev_target
    period_start_height = height - RETARGET_INTERVAL
    start_header = heights_and_headers(period_start_height)
    end_header = heights_and_headers(height - 1)
    actual_span = end_header.timestamp - start_header.timestamp
    expected_span = RETARGET_INTERVAL * TARGET_BLOCK_TIME
    return compute_next_target(prev_target, actual_span, expected_span)


def work_for_target(target: int) -> int:
    """Cumulative-work contribution of one block at this target: how many
    hash attempts a block at this difficulty represents on average, so a
    chain can be compared by total work rather than merely block count."""
    return (1 << 256) // (target + 1)
