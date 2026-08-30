import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import merkle as m
from crypto import hash256


class TestMerkleTree(unittest.TestCase):
    def test_single_leaf_root_is_the_leaf_itself_hashed_with_itself_once(self):
        leaf = hash256(b"only")
        root = m.merkle_root([leaf])
        self.assertEqual(root, leaf)  # a lone leaf IS the root (no combining needed)

    def test_proofs_verify_for_every_tree_size_and_index(self):
        for n in [1, 2, 3, 4, 5, 7, 8, 9, 16, 17]:
            leaves = [hash256(str(i).encode()) for i in range(n)]
            root = m.merkle_root(leaves)
            for i in range(n):
                proof = m.build_proof(leaves, i)
                self.assertTrue(proof.verify(root), f"n={n} i={i} failed to verify")

    def test_forged_leaf_fails_proof(self):
        leaves = [hash256(str(i).encode()) for i in range(6)]
        root = m.merkle_root(leaves)
        proof = m.build_proof(leaves, 2)
        proof.leaf = hash256(b"forged")
        self.assertFalse(proof.verify(root))

    def test_forged_sibling_fails_proof(self):
        leaves = [hash256(str(i).encode()) for i in range(6)]
        root = m.merkle_root(leaves)
        proof = m.build_proof(leaves, 2)
        proof.siblings[0] = hash256(b"forged-sibling")
        self.assertFalse(proof.verify(root))

    def test_different_trees_produce_different_roots(self):
        a = m.merkle_root([hash256(b"a"), hash256(b"b")])
        b = m.merkle_root([hash256(b"a"), hash256(b"c")])
        self.assertNotEqual(a, b)

    def test_out_of_range_index_raises(self):
        leaves = [hash256(b"x")]
        with self.assertRaises(IndexError):
            m.build_proof(leaves, 5)

    def test_empty_leaves_root_is_deterministic(self):
        self.assertEqual(m.merkle_root([]), m.merkle_root([]))


if __name__ == "__main__":
    unittest.main()
