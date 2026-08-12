import os
import unittest

from nonce.core.merkle import merkle_root, merkle_proof, verify_merkle_proof


class TestMerkle(unittest.TestCase):
    def test_empty_list_roots_to_zero(self):
        self.assertEqual(merkle_root([]), b"\x00" * 32)

    def test_single_leaf_root_is_the_leaf(self):
        leaf = os.urandom(32)
        self.assertEqual(merkle_root([leaf]), leaf)

    def test_deterministic(self):
        leaves = [os.urandom(32) for _ in range(5)]
        self.assertEqual(merkle_root(leaves), merkle_root(list(leaves)))

    def test_order_sensitive(self):
        leaves = [os.urandom(32) for _ in range(4)]
        reordered = [leaves[1], leaves[0], leaves[2], leaves[3]]
        self.assertNotEqual(merkle_root(leaves), merkle_root(reordered))

    def test_proofs_verify_for_various_leaf_counts(self):
        for n in [1, 2, 3, 4, 5, 6, 7, 8, 9, 16, 17, 31]:
            leaves = [os.urandom(32) for _ in range(n)]
            root = merkle_root(leaves)
            for i in range(n):
                proof = merkle_proof(leaves, i)
                self.assertTrue(verify_merkle_proof(leaves[i], proof, root), f"n={n} i={i}")

    def test_wrong_leaf_fails_proof(self):
        leaves = [os.urandom(32) for _ in range(6)]
        root = merkle_root(leaves)
        proof = merkle_proof(leaves, 2)
        self.assertFalse(verify_merkle_proof(os.urandom(32), proof, root))

    def test_wrong_root_fails_proof(self):
        leaves = [os.urandom(32) for _ in range(6)]
        proof = merkle_proof(leaves, 2)
        self.assertFalse(verify_merkle_proof(leaves[2], proof, os.urandom(32)))

    def test_out_of_range_index_raises(self):
        leaves = [os.urandom(32) for _ in range(3)]
        with self.assertRaises(IndexError):
            merkle_proof(leaves, 3)
        with self.assertRaises(IndexError):
            merkle_proof(leaves, -1)


if __name__ == "__main__":
    unittest.main()
