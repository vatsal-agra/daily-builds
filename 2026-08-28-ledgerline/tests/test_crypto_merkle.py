import unittest

from ledgerline import crypto, merkle


class TestBase58Check(unittest.TestCase):
    def test_roundtrip(self):
        payload = crypto.hash160(b"some public key bytes")
        addr = crypto.b58check_encode(payload)
        self.assertEqual(crypto.b58check_decode(addr), payload)

    def test_addresses_use_our_version_byte(self):
        for i in range(20):
            addr = crypto.b58check_encode(crypto.hash160(str(i).encode()))
            self.assertTrue(addr.startswith("L"), addr)

    def test_corrupted_checksum_rejected(self):
        addr = crypto.b58check_encode(crypto.hash160(b"payload"))
        bad_char = "1" if addr[-1] != "1" else "2"
        corrupted = addr[:-1] + bad_char
        with self.assertRaises(ValueError):
            crypto.b58check_decode(corrupted)

    def test_wrong_version_rejected(self):
        addr = crypto.b58check_encode(crypto.hash160(b"payload"), version=0x00)
        with self.assertRaises(ValueError):
            crypto.b58check_decode(addr, expected_version=crypto.ADDRESS_VERSION)

    def test_invalid_character_rejected(self):
        with self.assertRaises(ValueError):
            crypto.b58decode("0OIl")  # all excluded from the base58 alphabet

    def test_leading_zero_bytes_preserved(self):
        payload = b"\x00\x00" + b"hello"
        encoded = crypto.b58encode(payload)
        self.assertTrue(encoded.startswith("11"))
        self.assertEqual(crypto.b58decode(encoded), payload)


class TestSha256d(unittest.TestCase):
    def test_double_hash(self):
        import hashlib
        data = b"ledgerline"
        expected = hashlib.sha256(hashlib.sha256(data).digest()).digest()
        self.assertEqual(crypto.sha256d(data), expected)


class TestMerkle(unittest.TestCase):
    def test_single_leaf_root_is_itself_hashed(self):
        leaf = crypto.sha256d(b"only")
        self.assertEqual(merkle.merkle_root([leaf]), leaf)

    def test_empty_tree_is_deterministic(self):
        self.assertEqual(merkle.merkle_root([]), merkle.merkle_root([]))

    def test_order_matters(self):
        a, b = crypto.sha256d(b"a"), crypto.sha256d(b"b")
        self.assertNotEqual(merkle.merkle_root([a, b]), merkle.merkle_root([b, a]))

    def test_proof_verifies_for_every_leaf(self):
        leaves = [crypto.sha256d(str(i).encode()) for i in range(7)]  # odd count -> exercises duplication
        root = merkle.merkle_root(leaves)
        for i, leaf in enumerate(leaves):
            proof = merkle.merkle_proof(leaves, i)
            self.assertTrue(merkle.verify_merkle_proof(leaf, proof, root), f"leaf {i}")

    def test_proof_fails_for_wrong_leaf(self):
        leaves = [crypto.sha256d(str(i).encode()) for i in range(5)]
        root = merkle.merkle_root(leaves)
        proof = merkle.merkle_proof(leaves, 2)
        self.assertFalse(merkle.verify_merkle_proof(leaves[3], proof, root))

    def test_proof_fails_against_wrong_root(self):
        leaves = [crypto.sha256d(str(i).encode()) for i in range(4)]
        other_root = merkle.merkle_root([crypto.sha256d(b"x")] * 4)
        proof = merkle.merkle_proof(leaves, 0)
        self.assertFalse(merkle.verify_merkle_proof(leaves[0], proof, other_root))

    def test_out_of_range_index_raises(self):
        leaves = [crypto.sha256d(b"a")]
        with self.assertRaises(IndexError):
            merkle.merkle_proof(leaves, 5)


if __name__ == "__main__":
    unittest.main()
