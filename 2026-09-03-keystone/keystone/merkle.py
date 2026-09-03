"""Merkle tree construction + inclusion proofs, Bitcoin-style (duplicate the
last hash when a level has an odd number of nodes)."""
from __future__ import annotations

from .crypto import double_sha256


def _pair_hash(left: bytes, right: bytes) -> bytes:
    return double_sha256(left + right)


def merkle_root(leaf_hashes: list) -> bytes:
    """leaf_hashes: list of 32-byte digests (e.g. txids), already hashed."""
    if not leaf_hashes:
        return double_sha256(b"")  # empty block still has a well-defined root
    level = list(leaf_hashes)
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        level = [_pair_hash(level[i], level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]


def merkle_proof(leaf_hashes: list, index: int) -> list:
    """Return [(sibling_hash, sibling_is_on_right)] from leaf to root."""
    if not (0 <= index < len(leaf_hashes)):
        raise IndexError("index out of range")
    level = list(leaf_hashes)
    idx = index
    proof = []
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        if idx % 2 == 0:
            sibling = level[idx + 1]
            proof.append((sibling, True))
        else:
            sibling = level[idx - 1]
            proof.append((sibling, False))
        level = [_pair_hash(level[i], level[i + 1]) for i in range(0, len(level), 2)]
        idx //= 2
    return proof


def verify_merkle_proof(leaf_hash: bytes, proof: list, root: bytes) -> bool:
    current = leaf_hash
    for sibling, sibling_is_right in proof:
        if sibling_is_right:
            current = _pair_hash(current, sibling)
        else:
            current = _pair_hash(sibling, current)
    return current == root
