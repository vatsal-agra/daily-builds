import hashlib
import unittest

from bedrock.merkle import merkle_proof, merkle_root, verify_merkle_proof


def brute_force_root(leaves):
    """Independent, deliberately non-shared-code reference implementation."""
    if not leaves:
        return b"\x00" * 32
    level = list(leaves)
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            left = level[i]
            right = level[i + 1] if i + 1 < len(level) else level[i]
            nxt.append(hashlib.sha256(hashlib.sha256(left + right).digest()).digest())
        level = nxt
    return level[0]


def leaf(n: int) -> bytes:
    return hashlib.sha256(str(n).encode()).digest()


class TestMerkle(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(merkle_root([]), b"\x00" * 32)

    def test_single_leaf_root_is_itself_hashed_with_itself(self):
        leaves = [leaf(1)]
        self.assertEqual(merkle_root(leaves), brute_force_root(leaves))

    def test_matches_brute_force_oracle_for_various_sizes(self):
        for n in range(1, 20):
            leaves = [leaf(i) for i in range(n)]
            self.assertEqual(merkle_root(leaves), brute_force_root(leaves), f"mismatch at n={n}")

    def test_changing_any_leaf_changes_root(self):
        leaves = [leaf(i) for i in range(9)]
        base = merkle_root(leaves)
        for i in range(9):
            mutated = list(leaves)
            mutated[i] = leaf(999)
            self.assertNotEqual(merkle_root(mutated), base, f"leaf {i} change didn't affect root")

    def test_proofs_verify_for_every_leaf(self):
        for n in (1, 2, 3, 5, 8, 13):
            leaves = [leaf(i) for i in range(n)]
            root = merkle_root(leaves)
            for i in range(n):
                proof = merkle_proof(leaves, i)
                self.assertTrue(verify_merkle_proof(leaves[i], proof, root), f"proof failed at n={n}, i={i}")

    def test_proof_fails_for_wrong_leaf(self):
        leaves = [leaf(i) for i in range(7)]
        root = merkle_root(leaves)
        proof = merkle_proof(leaves, 3)
        self.assertFalse(verify_merkle_proof(leaf(999), proof, root))

    def test_proof_out_of_range_raises(self):
        leaves = [leaf(i) for i in range(3)]
        with self.assertRaises(IndexError):
            merkle_proof(leaves, 3)


if __name__ == "__main__":
    unittest.main()
