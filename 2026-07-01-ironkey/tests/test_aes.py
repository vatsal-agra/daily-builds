from . import _path  # noqa: F401
import os
import unittest

import aes


class TestSBox(unittest.TestCase):
    def test_known_sbox_values_fips197_figure7(self):
        # FIPS 197 Figure 7's S-box table, spot-checked (row/col 0x00 -> 0x63, etc.)
        self.assertEqual(aes.SBOX[0x00], 0x63)
        self.assertEqual(aes.SBOX[0x01], 0x7C)
        self.assertEqual(aes.SBOX[0x53], 0xED)
        self.assertEqual(aes.SBOX[0xFF], 0x16)

    def test_sbox_is_a_bijection(self):
        self.assertEqual(sorted(aes.SBOX), list(range(256)))

    def test_inv_sbox_actually_inverts(self):
        for x in range(256):
            self.assertEqual(aes.INV_SBOX[aes.SBOX[x]], x)


class TestGF256(unittest.TestCase):
    def test_multiply_by_zero_and_one(self):
        for x in range(256):
            self.assertEqual(aes.gf_mul(x, 0), 0)
            self.assertEqual(aes.gf_mul(x, 1), x)

    def test_inverse_round_trips(self):
        for x in range(1, 256):
            inv = aes.gf_inv(x)
            self.assertEqual(aes.gf_mul(x, inv), 1)


class TestFIPS197Vectors(unittest.TestCase):
    PT = bytes.fromhex("00112233445566778899aabbccddeeff")

    def test_aes128(self):
        key = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
        expected = bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")
        ct = aes.encrypt_block(self.PT, key)
        self.assertEqual(ct, expected)
        self.assertEqual(aes.decrypt_block(ct, key), self.PT)

    def test_aes192(self):
        key = bytes.fromhex("000102030405060708090a0b0c0d0e0f1011121314151617")
        expected = bytes.fromhex("dda97ca4864cdfe06eaf70a0ec0d7191")
        ct = aes.encrypt_block(self.PT, key)
        self.assertEqual(ct, expected)
        self.assertEqual(aes.decrypt_block(ct, key), self.PT)

    def test_aes256(self):
        key = bytes.fromhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
        expected = bytes.fromhex("8ea2b7ca516745bfeafc49904b496089")
        ct = aes.encrypt_block(self.PT, key)
        self.assertEqual(ct, expected)
        self.assertEqual(aes.decrypt_block(ct, key), self.PT)

    def test_cached_schedule_class_matches_free_functions(self):
        key = bytes.fromhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
        expected = bytes.fromhex("8ea2b7ca516745bfeafc49904b496089")
        a = aes.AES(key)
        self.assertEqual(a.encrypt_block(self.PT), expected)
        self.assertEqual(a.decrypt_block(expected), self.PT)


class TestRoundTripAndErrors(unittest.TestCase):
    def test_random_round_trip_all_key_sizes(self):
        for keylen in (16, 24, 32):
            key = os.urandom(keylen)
            pt = os.urandom(16)
            ct = aes.encrypt_block(pt, key)
            self.assertEqual(aes.decrypt_block(ct, key), pt)
            self.assertNotEqual(ct, pt)

    def test_rejects_bad_key_length(self):
        with self.assertRaises(ValueError):
            aes.AES(b"short")
        with self.assertRaises(ValueError):
            aes.encrypt_block(b"x" * 16, b"short")

    def test_rejects_bad_block_length(self):
        key = os.urandom(32)
        with self.assertRaises(ValueError):
            aes.encrypt_block(b"tooshort", key)
        with self.assertRaises(ValueError):
            aes.AES(key).encrypt_block(b"tooshort")


class TestTraceEncrypt(unittest.TestCase):
    def test_trace_final_step_matches_encrypt_block(self):
        key = os.urandom(32)
        pt = os.urandom(16)
        steps = aes.trace_encrypt(pt, key)
        self.assertEqual(steps[0][1], pt)
        self.assertEqual(steps[-1][1], aes.encrypt_block(pt, key))

    def test_trace_step_count_for_aes256(self):
        # AES-256: Nr=14 rounds. Steps: Input, AddRoundKey(0), then 13 full
        # rounds x 4 steps, then final round x 3 steps (no MixColumns).
        key = os.urandom(32)
        pt = os.urandom(16)
        steps = aes.trace_encrypt(pt, key)
        expected = 1 + 1 + 13 * 4 + 3
        self.assertEqual(len(steps), expected)


if __name__ == "__main__":
    unittest.main()
