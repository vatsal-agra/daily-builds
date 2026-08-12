"""Merkle tree construction and inclusion proofs (Bitcoin-style: pairwise
sha256d, odd node duplicated up a level).
"""

from ..crypto.sha256 import sha256d


def merkle_root(leaf_hashes):
    """leaf_hashes: list of 32-byte hashes (e.g. txids). Returns the
    32-byte merkle root. An empty list roots to 32 zero bytes."""
    if not leaf_hashes:
        return b"\x00" * 32
    level = list(leaf_hashes)
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])  # duplicate last node on odd count
        level = [sha256d(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]


def merkle_proof(leaf_hashes, index):
    """Build an inclusion proof for leaf_hashes[index]: a list of
    (sibling_hash, node_is_on_right) pairs from leaf to root, where
    node_is_on_right says whether *our* running hash sits on the right
    of the pair at that level (so the sibling belongs on the left)."""
    if not (0 <= index < len(leaf_hashes)):
        raise IndexError("index out of range")
    proof = []
    level = list(leaf_hashes)
    idx = index
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        node_is_right = idx % 2 == 1
        sibling_idx = idx - 1 if node_is_right else idx + 1
        proof.append((level[sibling_idx], node_is_right))
        level = [sha256d(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
        idx //= 2
    return proof


def verify_merkle_proof(leaf_hash, proof, root) -> bool:
    """Recompute the root from leaf_hash + proof and compare to root."""
    h = leaf_hash
    for sibling, node_is_right in proof:
        h = sha256d(sibling + h) if node_is_right else sha256d(h + sibling)
    return h == root
