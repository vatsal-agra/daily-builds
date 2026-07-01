from . import _path  # noqa: F401
import os
import tempfile
import unittest

import vault

_FAST_ITERS = 100  # keep the suite fast; CLI/vault.py default is calibrated separately


class TestVault(unittest.TestCase):
    def test_round_trip(self):
        data = b"these are my secret notes" * 20
        v = vault.encrypt_file("correct horse battery staple", data, iterations=_FAST_ITERS)
        self.assertEqual(vault.decrypt_file("correct horse battery staple", v), data)

    def test_empty_plaintext(self):
        v = vault.encrypt_file("pw", b"", iterations=_FAST_ITERS)
        self.assertEqual(vault.decrypt_file("pw", v), b"")

    def test_wrong_password_rejected(self):
        v = vault.encrypt_file("right password", b"data", iterations=_FAST_ITERS)
        with self.assertRaises(ValueError):
            vault.decrypt_file("wrong password", v)

    def test_tampered_vault_rejected(self):
        v = bytearray(vault.encrypt_file("pw", b"data" * 10, iterations=_FAST_ITERS))
        v[-1] ^= 1
        with self.assertRaises(ValueError):
            vault.decrypt_file("pw", bytes(v))

    def test_garbage_input_rejected_cleanly(self):
        with self.assertRaises(ValueError):
            vault.decrypt_file("pw", b"not a vault file at all")

    def test_empty_password_rejected(self):
        with self.assertRaises(ValueError):
            vault.encrypt_file("", b"data")

    def test_wrong_password_and_tamper_give_same_error_message(self):
        """Vault decrypt failures should not be distinguishable, same
        principle as the OAEP fix in REVIEW.md finding #2."""
        v = vault.encrypt_file("pw", b"some data", iterations=_FAST_ITERS)
        with self.assertRaises(ValueError) as ctx1:
            vault.decrypt_file("wrong", v)
        tampered = bytearray(v)
        tampered[-1] ^= 1
        with self.assertRaises(ValueError) as ctx2:
            vault.decrypt_file("pw", bytes(tampered))
        self.assertEqual(str(ctx1.exception), str(ctx2.exception))

    def test_file_helpers_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            in_path = os.path.join(d, "secret.txt")
            vault_path = os.path.join(d, "secret.vault")
            out_path = os.path.join(d, "secret_out.txt")
            with open(in_path, "wb") as f:
                f.write(b"file contents to protect")
            vault.encrypt_path("pw", in_path, vault_path, iterations=_FAST_ITERS)
            vault.decrypt_path("pw", vault_path, out_path)
            with open(out_path, "rb") as f:
                self.assertEqual(f.read(), b"file contents to protect")


if __name__ == "__main__":
    unittest.main()
