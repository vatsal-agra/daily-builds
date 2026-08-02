"""Merkle tree construction and inclusion proofs (Bitcoin-style: SHA-256d,
odd levels duplicate the last hash)."""

import hashlib


def sha256d(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def merkle_root(leaf_hashes):
    """leaf_hashes: list[bytes]. Returns the 32-byte root."""
    if not leaf_hashes:
        return b"\x00" * 32
    level = list(leaf_hashes)
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        level = [sha256d(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]


def merkle_proof(leaf_hashes, index):
    """Return a list of (sibling_hash, is_right) pairs proving leaf `index`
    is included, from the bottom of the tree to the top."""
    if not (0 <= index < len(leaf_hashes)):
        raise IndexError("leaf index out of range")
    level = list(leaf_hashes)
    idx = index
    proof = []
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        if idx % 2 == 0:
            sibling = level[idx + 1]
            proof.append((sibling, True))  # sibling is on the right
        else:
            sibling = level[idx - 1]
            proof.append((sibling, False))  # sibling is on the left
        level = [sha256d(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
        idx //= 2
    return proof


def verify_proof(leaf_hash, proof, root):
    h = leaf_hash
    for sibling, is_right in proof:
        h = sha256d(h + sibling) if is_right else sha256d(sibling + h)
    return h == root
