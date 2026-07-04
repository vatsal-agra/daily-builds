from . import _path  # noqa: F401
import os
import shutil
import subprocess
import tempfile
import unittest

import modes

_OPENSSL = shutil.which("openssl")


class TestPKCS7(unittest.TestCase):
    def test_pad_unpad_round_trip(self):
        for n in range(0, 33):
            data = bytes(range(n % 256)) if n else b""
            data = os.urandom(n)
            padded = modes.pkcs7_pad(data)
            self.assertEqual(len(padded) % 16, 0)
            self.assertEqual(modes.pkcs7_unpad(padded), data)

    def test_full_block_of_padding_when_input_is_block_aligned(self):
        data = os.urandom(32)
        padded = modes.pkcs7_pad(data)
        self.assertEqual(len(padded), 48)  # a whole extra padding block

    def test_rejects_bad_padding(self):
        with self.assertRaises(ValueError):
            modes.pkcs7_unpad(b"\x00" * 16)  # pad_len byte 0 is invalid
        with self.assertRaises(ValueError):
            modes.pkcs7_unpad(b"\x11" * 16)  # pad_len > block size
        with self.assertRaises(ValueError):
            modes.pkcs7_unpad(b"\x03\x03\x03\x02" + b"\x00" * 12)  # inconsistent bytes


class TestCBC(unittest.TestCase):
    def test_round_trip(self):
        key, iv = os.urandom(32), os.urandom(16)
        for n in [0, 1, 15, 16, 17, 100]:
            data = os.urandom(n)
            ct = modes.cbc_encrypt(key, iv, data)
            self.assertEqual(modes.cbc_decrypt(key, iv, ct), data)

    def test_tampered_ciphertext_detected_via_padding(self):
        key, iv = os.urandom(32), os.urandom(16)
        ct = modes.cbc_encrypt(key, iv, b"a reasonably long plaintext message")
        bad = bytearray(ct)
        bad[-1] ^= 0xFF
        with self.assertRaises(ValueError):
            modes.cbc_decrypt(key, iv, bytes(bad))

    def test_wrong_iv_gives_wrong_first_block_only(self):
        key, iv1, iv2 = os.urandom(32), os.urandom(16), os.urandom(16)
        pt = os.urandom(32)
        ct = modes.cbc_encrypt(key, iv1, pt)
        wrong = modes.cbc_decrypt(key, iv2, ct, unpad=False)
        self.assertNotEqual(wrong[:16], pt[:16])
        self.assertEqual(wrong[16:32], pt[16:32])  # CBC self-heals after block 1

    @unittest.skipUnless(_OPENSSL, "openssl CLI not available")
    def test_cross_check_against_openssl_cbc(self):
        key, iv = os.urandom(32), os.urandom(16)
        pt = os.urandom(64)  # multiple of block size, no padding ambiguity
        with tempfile.TemporaryDirectory() as d:
            pt_path = os.path.join(d, "pt.bin")
            ct_path = os.path.join(d, "ct.bin")
            with open(pt_path, "wb") as f:
                f.write(pt)
            subprocess.run(
                ["openssl", "enc", "-aes-256-cbc", "-K", key.hex(), "-iv", iv.hex(),
                 "-nopad", "-in", pt_path, "-out", ct_path, "-e"],
                check=True, capture_output=True,
            )
            with open(ct_path, "rb") as f:
                openssl_ct = f.read()
        ours = modes.cbc_encrypt(key, iv, pt)[:len(pt)]  # strip our extra padding block
        self.assertEqual(ours, openssl_ct)
        self.assertEqual(modes.cbc_decrypt(key, iv, openssl_ct, unpad=False), pt)


class TestGCM(unittest.TestCase):
    def test_round_trip_with_and_without_aad(self):
        key, iv = os.urandom(32), os.urandom(12)
        for aad in [b"", b"associated data"]:
            for n in [0, 1, 16, 100]:
                pt = os.urandom(n)
                ct, tag = modes.gcm_encrypt(key, iv, pt, aad)
                self.assertEqual(modes.gcm_decrypt(key, iv, ct, tag, aad), pt)

    def test_tampered_ciphertext_rejected(self):
        key, iv = os.urandom(32), os.urandom(12)
        ct, tag = modes.gcm_encrypt(key, iv, b"secret data")
        bad = bytes([ct[0] ^ 1]) + ct[1:]
        with self.assertRaises(ValueError):
            modes.gcm_decrypt(key, iv, bad, tag)

    def test_tampered_tag_rejected(self):
        key, iv = os.urandom(32), os.urandom(12)
        ct, tag = modes.gcm_encrypt(key, iv, b"secret data")
        bad_tag = bytes([tag[0] ^ 1]) + tag[1:]
        with self.assertRaises(ValueError):
            modes.gcm_decrypt(key, iv, ct, bad_tag)

    def test_tampered_aad_rejected(self):
        key, iv = os.urandom(32), os.urandom(12)
        ct, tag = modes.gcm_encrypt(key, iv, b"secret data", aad=b"real aad")
        with self.assertRaises(ValueError):
            modes.gcm_decrypt(key, iv, ct, tag, aad=b"wrong aad")

    def test_requires_96_bit_iv(self):
        key = os.urandom(32)
        with self.assertRaises(ValueError):
            modes.gcm_encrypt(key, os.urandom(16), b"data")

    def test_wrong_key_fails_auth(self):
        key1, key2, iv = os.urandom(32), os.urandom(32), os.urandom(12)
        ct, tag = modes.gcm_encrypt(key1, iv, b"data")
        with self.assertRaises(ValueError):
            modes.gcm_decrypt(key2, iv, ct, tag)

    def test_truncated_tag_length_option(self):
        key, iv = os.urandom(32), os.urandom(12)
        ct, tag = modes.gcm_encrypt(key, iv, b"data", tag_len=8)
        self.assertEqual(len(tag), 8)
        self.assertEqual(modes.gcm_decrypt(key, iv, ct, tag, tag_len=8), b"data")


if __name__ == "__main__":
    unittest.main()
