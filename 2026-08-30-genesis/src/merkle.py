"""From-scratch Merkle tree: build, root, and inclusion-proof generation/verification.

Follows the Bitcoin convention: leaves are transaction hashes (as raw
bytes, already hashed); an odd node at any level is duplicated to pair
with itself. This is documented as a known quirk (CVE-2012-2459-style
duplicate-leaf ambiguity) and we accept it deliberately for fidelity to
the real algorithm rather than "fixing" it into a different scheme.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from crypto import hash256


def _parent_hash(left: bytes, right: bytes) -> bytes:
    return hash256(left + right)


def merkle_root(leaves: List[bytes]) -> bytes:
    if not leaves:
        return hash256(b"")  # empty-block convention: hash of empty string
    level = list(leaves)
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        level = [_parent_hash(level[i], level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]


@dataclass
class MerkleProof:
    leaf: bytes
    index: int
    siblings: List[bytes]           # sibling hash at each level, bottom-up
    sibling_is_right: List[bool]    # whether that sibling is the right child

    def verify(self, expected_root: bytes) -> bool:
        current = self.leaf
        for sibling, is_right in zip(self.siblings, self.sibling_is_right):
            current = _parent_hash(current, sibling) if is_right else _parent_hash(sibling, current)
        return current == expected_root


def build_proof(leaves: List[bytes], index: int) -> MerkleProof:
    if not (0 <= index < len(leaves)):
        raise IndexError("leaf index out of range")
    level = list(leaves)
    siblings, sides = [], []
    idx = index
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        if idx % 2 == 0:
            sibling_idx = idx + 1
            sides.append(True)   # sibling is on the right
        else:
            sibling_idx = idx - 1
            sides.append(False)  # sibling is on the left
        siblings.append(level[sibling_idx])
        level = [_parent_hash(level[i], level[i + 1]) for i in range(0, len(level), 2)]
        idx //= 2
    return MerkleProof(leaf=leaves[index], index=index, siblings=siblings, sibling_is_right=sides)
