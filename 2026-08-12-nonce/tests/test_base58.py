import os
import unittest

from nonce.crypto.base58 import b58encode, b58decode, b58check_encode, b58check_decode


class TestBase58(unittest.TestCase):
    def test_round_trip_random_bytes(self):
        for _ in range(50):
            data = os.urandom(20)
            self.assertEqual(b58decode(b58encode(data)), data)

    def test_leading_zero_bytes_preserved(self):
        data = b"\x00\x00" + os.urandom(18)
        encoded = b58encode(data)
        self.assertTrue(encoded.startswith("11"))
        self.assertEqual(b58decode(encoded), data)

    def test_invalid_character_raises_clear_error(self):
        with self.assertRaises(ValueError) as ctx:
            b58decode("0OIl")  # every one of these is excluded from the base58 alphabet
        self.assertIn("not a valid base58", str(ctx.exception))


class TestBase58Check(unittest.TestCase):
    def test_round_trip(self):
        for _ in range(50):
            payload = os.urandom(20)
            addr = b58check_encode(b"\x00", payload)
            version, decoded = b58check_decode(addr)
            self.assertEqual(version, b"\x00")
            self.assertEqual(decoded, payload)

    def test_tampered_checksum_detected(self):
        addr = b58check_encode(b"\x00", b"\x11" * 20)
        tampered = addr[:-1] + ("A" if addr[-1] != "A" else "B")
        with self.assertRaises(ValueError):
            b58check_decode(tampered)

    def test_empty_string_rejected_cleanly(self):
        with self.assertRaises(ValueError):
            b58check_decode("")

    def test_truncated_address_rejected(self):
        addr = b58check_encode(b"\x00", os.urandom(20))
        with self.assertRaises(ValueError):
            b58check_decode(addr[:4])


if __name__ == "__main__":
    unittest.main()
