import hashlib
import unittest

from concord.merkle import merkle_proof, merkle_root, sha256d, verify_proof


def leaf(n):
    return hashlib.sha256(str(n).encode()).digest()


class TestMerkle(unittest.TestCase):
    def test_empty_tree_is_sentinel(self):
        self.assertEqual(merkle_root([]), b"\x00" * 32)

    def test_single_leaf_root_equals_leaf(self):
        l = leaf(1)
        self.assertEqual(merkle_root([l]), l)

    def test_two_leaves_root_matches_manual_hash(self):
        a, b = leaf(1), leaf(2)
        self.assertEqual(merkle_root([a, b]), sha256d(a + b))

    def test_odd_leaf_count_duplicates_last(self):
        a, b, c = leaf(1), leaf(2), leaf(3)
        expected = sha256d(sha256d(a + b) + sha256d(c + c))
        self.assertEqual(merkle_root([a, b, c]), expected)

    def test_proof_verifies_for_every_leaf_various_sizes(self):
        for n in (1, 2, 3, 4, 5, 7, 8, 16, 17):
            leaves = [leaf(i) for i in range(n)]
            root = merkle_root(leaves)
            for i in range(n):
                proof = merkle_proof(leaves, i)
                self.assertTrue(verify_proof(leaves[i], proof, root), f"n={n} i={i}")

    def test_single_leaf_proof_is_empty(self):
        leaves = [leaf(1)]
        proof = merkle_proof(leaves, 0)
        self.assertEqual(proof, [])
        self.assertTrue(verify_proof(leaves[0], proof, merkle_root(leaves)))

    def test_proof_fails_for_wrong_leaf(self):
        leaves = [leaf(i) for i in range(5)]
        root = merkle_root(leaves)
        proof = merkle_proof(leaves, 2)
        self.assertFalse(verify_proof(leaf(999), proof, root))

    def test_proof_fails_against_wrong_root(self):
        leaves = [leaf(i) for i in range(5)]
        wrong_root = merkle_root([leaf(i) for i in range(5, 10)])
        proof = merkle_proof(leaves, 2)
        self.assertFalse(verify_proof(leaves[2], proof, wrong_root))

    def test_proof_out_of_range_raises(self):
        leaves = [leaf(i) for i in range(3)]
        with self.assertRaises(IndexError):
            merkle_proof(leaves, 10)
        with self.assertRaises(IndexError):
            merkle_proof(leaves, -1)


if __name__ == "__main__":
    unittest.main()
