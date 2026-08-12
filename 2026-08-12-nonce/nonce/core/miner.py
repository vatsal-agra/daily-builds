"""The mining loop: grind nonces (and, once the 32-bit nonce space is
exhausted, bump the timestamp and keep going — same trick real miners
use) until the block header hash satisfies the proof-of-work target.
"""

import time

from .block import Block

NONCE_MAX = 0xFFFFFFFF


class MiningAborted(Exception):
    """Raised when a mine() call is cancelled (e.g. a competing block
    arrived on the network mid-mine) via the should_abort callback."""


def mine(block: Block, max_attempts=None, should_abort=None) -> Block:
    """Mutates block.header.nonce (and, rarely, timestamp) in place until
    header.meets_target() is true, then returns the same block.

    should_abort: optional zero-arg callable polled periodically; if it
    returns True, raises MiningAborted so a node can stop wasted work the
    instant a peer's block makes this one moot.
    """
    attempts = 0
    header = block.header
    while True:
        header.nonce = 0
        for nonce in range(NONCE_MAX + 1):
            header.nonce = nonce
            header._hash_cache = None
            attempts += 1
            if header.meets_target():
                return block
            if should_abort is not None and attempts % 2000 == 0 and should_abort():
                raise MiningAborted()
            if max_attempts is not None and attempts >= max_attempts:
                raise TimeoutError(f"mining gave up after {attempts} attempts without finding a valid nonce")
        # exhausted the whole 32-bit nonce space at this timestamp (won't
        # happen at demo difficulty, but real miners do exactly this)
        header.timestamp += 1
