from . import _path  # noqa: F401
import os
import unittest

import modes
import padding_oracle
import vulnerable_cbc


class TestPaddingOracleAttack(unittest.TestCase):
    def test_recovers_short_single_block_message(self):
        box = vulnerable_cbc.VulnerableCBCBox()
        secret = b"hi bob"
        ct = box.encrypt(secret)
        recovered = padding_oracle.recover_plaintext(box.padding_oracle, ct)
        self.assertEqual(recovered, secret)

    def test_recovers_multi_block_message(self):
        box = vulnerable_cbc.VulnerableCBCBox()
        secret = b"a longer secret message spanning multiple 16-byte AES blocks"
        ct = box.encrypt(secret)
        recovered = padding_oracle.recover_plaintext(box.padding_oracle, ct)
        self.assertEqual(recovered, secret)

    def test_recovers_message_needing_full_padding_block(self):
        # exactly one block (16 bytes) -> PKCS7 adds a full extra padding block
        box = vulnerable_cbc.VulnerableCBCBox()
        secret = b"sixteen byteszz!"
        self.assertEqual(len(secret), 16)
        ct = box.encrypt(secret)
        recovered = padding_oracle.recover_plaintext(box.padding_oracle, ct)
        self.assertEqual(recovered, secret)

    def test_recovers_empty_message(self):
        box = vulnerable_cbc.VulnerableCBCBox()
        ct = box.encrypt(b"")
        recovered = padding_oracle.recover_plaintext(box.padding_oracle, ct)
        self.assertEqual(recovered, b"")

    def test_never_needs_the_key(self):
        # the oracle callable given to the attack only ever returns a bool;
        # the attack module itself never imports or touches box.key
        box = vulnerable_cbc.VulnerableCBCBox()
        secret = b"attacker never sees this key material"
        ct = box.encrypt(secret)
        calls = []

        def spying_oracle(candidate):
            calls.append(candidate)
            return box.padding_oracle(candidate)

        recovered = padding_oracle.recover_plaintext(spying_oracle, ct)
        self.assertEqual(recovered, secret)
        self.assertGreater(len(calls), 0)
        self.assertTrue(all(isinstance(c, bytes) for c in calls))

    def test_rejects_malformed_input_shape(self):
        with self.assertRaises(ValueError):
            padding_oracle.recover_plaintext(lambda c: True, b"tooshort")
        with self.assertRaises(ValueError):
            padding_oracle.recover_plaintext(lambda c: True, b"x" * 33)  # not a block multiple

    def test_fails_against_authenticated_gcm_ciphertext(self):
        """The whole point of finding #1's fix and vault.py's design:
        GCM has no padding-validity oracle to exploit at all."""
        key = os.urandom(32)
        iv = os.urandom(12)
        plaintext = b"protected by real authenticated encryption, not CBC+padding"
        ciphertext, tag = modes.gcm_encrypt(key, iv, plaintext)

        fake_iv_prefix = iv + b"\x00" * 4
        body = ciphertext[: (len(ciphertext) // 16) * 16 or 16]
        blob = fake_iv_prefix + body

        def gcm_oracle(candidate):
            forged_prefix, forged_body = candidate[:16], candidate[16:]
            try:
                modes.gcm_decrypt(key, forged_prefix[:12], forged_body, tag)
                return True
            except ValueError:
                return False

        with self.assertRaises(RuntimeError):
            padding_oracle.recover_plaintext(gcm_oracle, blob, unpad=False)


if __name__ == "__main__":
    unittest.main()
