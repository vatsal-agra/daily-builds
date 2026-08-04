"""A from-scratch binary Merkle tree over transaction ids.

Odd levels duplicate the last node (the same convention Bitcoin uses),
implemented explicitly here rather than imported from anywhere.
"""

from bedrock.crypto import sha256d


def _hash_pair(left: bytes, right: bytes) -> bytes:
    return sha256d(left + right)


def merkle_root(leaf_hashes: list) -> bytes:
    """leaf_hashes: list of 32-byte digests (e.g. txid bytes). Returns the
    32-byte Merkle root. An empty list roots to 32 zero bytes."""
    if not leaf_hashes:
        return b"\x00" * 32
    level = list(leaf_hashes)
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        level = [_hash_pair(level[i], level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]


def merkle_proof(leaf_hashes: list, index: int) -> list:
    """Returns a list of (sibling_hash, is_sibling_on_right) pairs proving
    leaf_hashes[index] is included, from the leaf level up to the root."""
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
            proof.append((sibling, True))
        else:
            sibling = level[idx - 1]
            proof.append((sibling, False))
        level = [_hash_pair(level[i], level[i + 1]) for i in range(0, len(level), 2)]
        idx //= 2
    return proof


def verify_merkle_proof(leaf_hash: bytes, proof: list, root: bytes) -> bool:
    current = leaf_hash
    for sibling, sibling_on_right in proof:
        if sibling_on_right:
            current = _hash_pair(current, sibling)
        else:
            current = _hash_pair(sibling, current)
    return current == root
