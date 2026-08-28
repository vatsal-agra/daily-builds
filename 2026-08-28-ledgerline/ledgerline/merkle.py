"""Merkle tree over transaction IDs (Bitcoin-style, duplicate-last-if-odd)."""
from __future__ import annotations

from typing import List, Sequence, Tuple

from .crypto import sha256d


def merkle_root(leaf_hashes: Sequence[bytes]) -> bytes:
    if not leaf_hashes:
        return sha256d(b"")
    level = list(leaf_hashes)
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])  # duplicate last node on odd levels
        level = [sha256d(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]


def merkle_proof(leaf_hashes: Sequence[bytes], index: int) -> List[Tuple[bytes, bool]]:
    """Inclusion proof for leaf `index`: list of (sibling_hash, sibling_is_right)."""
    if not (0 <= index < len(leaf_hashes)):
        raise IndexError("leaf index out of range")
    level = list(leaf_hashes)
    proof: List[Tuple[bytes, bool]] = []
    idx = index
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        if idx % 2 == 0:
            sibling = level[idx + 1]
            proof.append((sibling, True))
        else:
            sibling = level[idx - 1]
            proof.append((sibling, False))
        level = [sha256d(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
        idx //= 2
    return proof


def verify_merkle_proof(leaf: bytes, proof: List[Tuple[bytes, bool]], root: bytes) -> bool:
    node = leaf
    for sibling, sibling_is_right in proof:
        node = sha256d(node + sibling) if sibling_is_right else sha256d(sibling + node)
    return node == root
