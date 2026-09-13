"""A simple hash-based commitment scheme.

commit(message, nonce) = SHA-256(nonce || 0x00 || message)

Properties needed by the graph-coloring protocol (Section 2.4 of Goldreich's
"Foundations of Cryptography" formalizes exactly this primitive):

- **Hiding**: given only the commitment, the message is computationally
  indistinguishable from random (the nonce is a fresh, uniformly random
  32-byte string every time, so SHA-256's preimage resistance hides the
  short message value behind it).
- **Binding**: a committer cannot open one commitment to two different
  messages, since that would require a SHA-256 collision.

This is deliberately not a from-scratch SHA-256 (Vein already derived
SHA-256 from its specification as its own exercise) — the "from scratch"
content of Veil is the commitment/proof *protocols* layered on top.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

NONCE_BYTES = 32


@dataclass(frozen=True)
class Commitment:
    digest: bytes

    def hex(self) -> str:
        return self.digest.hex()


def commit(message: bytes, nonce: bytes | None = None) -> tuple[Commitment, bytes]:
    """Commit to `message`. Returns (commitment, nonce) — the nonce must be
    kept secret until reveal time, then supplied to `open_commitment`."""
    nonce = nonce if nonce is not None else os.urandom(NONCE_BYTES)
    digest = hashlib.sha256(nonce + b"\x00" + message).digest()
    return Commitment(digest), nonce


def open_commitment(c: Commitment, message: bytes, nonce: bytes) -> bool:
    """Verify that `message`/`nonce` really open commitment `c`."""
    expected = hashlib.sha256(nonce + b"\x00" + message).digest()
    return expected == c.digest
