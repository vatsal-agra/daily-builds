"""Proof-of-work: compact-bits target encoding (Bitcoin's `nBits` format),
a real mining search loop, and a periodic difficulty retarget.

Difficulty is kept low enough that a single Python process mines a block in
well under a second on average — this is a genuine hashcash-style search
(no shortcuts), just tuned for a demo/test timescale rather than a
real-world one.
"""
from __future__ import annotations

import time

from .crypto import sha256

MAX_TARGET = (1 << 224) - 1  # genesis / easiest-allowed difficulty
RETARGET_INTERVAL = 10  # blocks between difficulty retargets
TARGET_BLOCK_TIME = 0.5  # seconds — compressed timescale for a runnable demo


def target_to_bits(target: int) -> int:
    """Encode an integer target in Bitcoin's compact nBits form: a 1-byte
    exponent plus a 3-byte mantissa, exponent counts bytes not bits."""
    if target <= 0:
        raise ValueError("target must be positive")
    raw = target.to_bytes(32, "big").lstrip(b"\x00") or b"\x00"
    if raw[0] & 0x80:
        raw = b"\x00" + raw  # avoid the mantissa being read as negative
    exponent = len(raw)
    mantissa = raw[:3] if len(raw) >= 3 else raw + b"\x00" * (3 - len(raw))
    return (exponent << 24) | int.from_bytes(mantissa, "big")


def bits_to_target(bits: int) -> int:
    exponent = bits >> 24
    mantissa = bits & 0xFFFFFF
    if exponent <= 3:
        return mantissa >> (8 * (3 - exponent))
    return mantissa << (8 * (exponent - 3))


def block_work(bits: int) -> int:
    """Expected number of hashes to find a block at this difficulty —
    what "cumulative work" sums across a chain for fork resolution, exactly
    like Bitcoin (chain length is *not* what decides the winning fork)."""
    target = bits_to_target(bits)
    if target <= 0:
        return 0
    return ((1 << 256) // (target + 1))


def meets_target(block_hash: bytes, bits: int) -> bool:
    return int.from_bytes(block_hash, "big") <= bits_to_target(bits)


class MiningInterrupted(Exception):
    """Raised (by a caller-supplied `should_stop`) to abort a mining search
    early, e.g. because a competing block for this height already arrived."""


def mine(header_prefix_bytes_fn, bits: int, max_nonce: int = 1 << 32, should_stop=None, start_nonce: int = 0):
    """Search nonces for a hash meeting `bits`'s target.

    `header_prefix_bytes_fn(nonce) -> bytes` builds the exact byte string to
    hash for a given nonce (the caller owns header serialization); this
    function only owns the search + stopping-condition logic, kept generic
    so block.py doesn't need to know how mining works and pow.py doesn't
    need to know how a block header serializes.

    Returns (nonce, hash) on success, or None if max_nonce exhausted or
    should_stop() became true.
    """
    nonce = start_nonce
    checked = 0
    while nonce < max_nonce:
        if should_stop is not None and checked % 2048 == 0 and should_stop():
            return None
        h = sha256(sha256(header_prefix_bytes_fn(nonce)))
        if meets_target(h, bits):
            return nonce, h
        nonce += 1
        checked += 1
    return None


def next_bits(prev_bits: int, first_block_time: float, last_block_time: float, blocks_in_period: int) -> int:
    """Bitcoin-style retarget: scale the target by (actual timespan /
    expected timespan), clamped to [1/4x, 4x] so one wild outlier block
    can't swing difficulty by an absurd factor in one step."""
    expected_timespan = TARGET_BLOCK_TIME * blocks_in_period
    actual_timespan = max(last_block_time - first_block_time, 0.0)
    # clamp actual timespan to [expected/4, expected*4]
    actual_timespan = max(expected_timespan / 4, min(actual_timespan, expected_timespan * 4))
    if actual_timespan <= 0:
        actual_timespan = expected_timespan / 4  # degenerate (near-zero elapsed time): harden fast

    old_target = bits_to_target(prev_bits)
    new_target = (old_target * int(actual_timespan * 1_000_000)) // int(expected_timespan * 1_000_000)
    new_target = min(new_target, MAX_TARGET)
    new_target = max(new_target, 1)
    return target_to_bits(new_target)


def now() -> float:
    return time.time()
