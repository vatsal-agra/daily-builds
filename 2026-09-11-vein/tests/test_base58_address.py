import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vein.crypto.base58 import b58encode, b58decode, b58check_encode, b58check_decode
from vein.crypto.address import (
    serialize_pubkey, parse_pubkey, address_from_pubkey, pubkey_hash_from_address, is_valid_address,
)
from vein.crypto.curve import derive_pubkey
from vein.crypto.ecdsa import generate_privkey
from vein.crypto.hashes import hash160


class TestBase58(unittest.TestCase):
    def test_roundtrip(self):
        cases = [b"", b"\x00", b"\x00\x00abc", b"hello world", os.urandom(20), b"\x00" * 5 + os.urandom(10)]
        for data in cases:
            self.assertEqual(b58decode(b58encode(data)), data)

    def test_leading_zero_preserved_as_leading_one(self):
        enc = b58encode(b"\x00\x00\x01")
        self.assertTrue(enc.startswith("11"))

    def test_check_roundtrip(self):
        payload = os.urandom(21)
        addr = b58check_encode(payload)
        self.assertEqual(b58check_decode(addr), payload)

    def test_checksum_corruption_detected(self):
        payload = os.urandom(21)
        addr = b58check_encode(payload)
        corrupted = addr[:-1] + ("1" if addr[-1] != "1" else "2")
        with self.assertRaises(ValueError):
            b58check_decode(corrupted)

    def test_invalid_character_rejected(self):
        with self.assertRaises(ValueError):
            b58decode("0OIl")  # all four excluded characters


class TestAddress(unittest.TestCase):
    def test_pubkey_roundtrip(self):
        priv = generate_privkey()
        pub = derive_pubkey(priv)
        ser = serialize_pubkey(pub)
        self.assertEqual(len(ser), 33)
        self.assertEqual(parse_pubkey(ser), pub)

    def test_address_roundtrip(self):
        priv = generate_privkey()
        ser = serialize_pubkey(derive_pubkey(priv))
        addr = address_from_pubkey(ser)
        self.assertEqual(pubkey_hash_from_address(addr), hash160(ser))
        self.assertTrue(is_valid_address(addr))

    def test_invalid_address_detected(self):
        self.assertFalse(is_valid_address("not-a-real-address"))
        self.assertFalse(is_valid_address(""))

    def test_tampered_address_detected(self):
        priv = generate_privkey()
        addr = address_from_pubkey(serialize_pubkey(derive_pubkey(priv)))
        tampered = addr[:-2] + ("11" if addr[-2:] != "11" else "22")
        self.assertFalse(is_valid_address(tampered))

    def test_uncompressed_prefix_rejected(self):
        priv = generate_privkey()
        pub = derive_pubkey(priv)
        bad = bytes([0x04]) + pub.x.to_bytes(32, "big")  # wrong prefix byte
        with self.assertRaises(ValueError):
            parse_pubkey(bad)


if __name__ == "__main__":
    unittest.main()
