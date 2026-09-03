import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from keystone.crypto import double_sha256
from keystone import merkle


def leaf(i):
    return double_sha256(f"leaf-{i}".encode())


class TestMerkle(unittest.TestCase):
    def test_single_leaf_root_is_the_leaf_itself(self):
        h = leaf(0)
        self.assertEqual(merkle.merkle_root([h]), h)

    def test_empty_tree_has_well_defined_root(self):
        root = merkle.merkle_root([])
        self.assertEqual(len(root), 32)

    def test_root_changes_if_any_leaf_changes(self):
        leaves = [leaf(i) for i in range(7)]
        root1 = merkle.merkle_root(leaves)
        leaves[3] = leaf(999)
        root2 = merkle.merkle_root(leaves)
        self.assertNotEqual(root1, root2)

    def test_root_is_order_sensitive(self):
        leaves = [leaf(i) for i in range(4)]
        root1 = merkle.merkle_root(leaves)
        root2 = merkle.merkle_root(list(reversed(leaves)))
        self.assertNotEqual(root1, root2)

    def test_proof_verifies_for_every_index_various_sizes(self):
        for n in (1, 2, 3, 4, 5, 7, 8, 9, 16, 17):
            leaves = [leaf(i) for i in range(n)]
            root = merkle.merkle_root(leaves)
            for idx in range(n):
                with self.subTest(n=n, idx=idx):
                    proof = merkle.merkle_proof(leaves, idx)
                    self.assertTrue(merkle.verify_merkle_proof(leaves[idx], proof, root))

    def test_proof_fails_for_wrong_leaf(self):
        leaves = [leaf(i) for i in range(6)]
        root = merkle.merkle_root(leaves)
        proof = merkle.merkle_proof(leaves, 2)
        self.assertFalse(merkle.verify_merkle_proof(leaf(999), proof, root))

    def test_proof_fails_against_wrong_root(self):
        leaves = [leaf(i) for i in range(6)]
        proof = merkle.merkle_proof(leaves, 2)
        wrong_root = merkle.merkle_root([leaf(i) for i in range(6, 12)])
        self.assertFalse(merkle.verify_merkle_proof(leaves[2], proof, wrong_root))

    def test_out_of_range_index_raises(self):
        leaves = [leaf(i) for i in range(3)]
        with self.assertRaises(IndexError):
            merkle.merkle_proof(leaves, 3)


if __name__ == "__main__":
    unittest.main()
