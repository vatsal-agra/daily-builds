from . import _path  # noqa: F401
import os
import re
import shutil
import subprocess
import tempfile
import unittest

import x25519

_OPENSSL = shutil.which("openssl")


class TestX25519(unittest.TestCase):
    def test_shared_secret_agrees_both_directions(self):
        a_priv = x25519.generate_private_key()
        b_priv = x25519.generate_private_key()
        a_pub = x25519.derive_public_key(a_priv)
        b_pub = x25519.derive_public_key(b_priv)
        shared_a = x25519.compute_shared_secret(a_priv, b_pub)
        shared_b = x25519.compute_shared_secret(b_priv, a_pub)
        self.assertEqual(shared_a, shared_b)
        self.assertEqual(len(shared_a), 32)

    def test_different_keypairs_give_different_secrets(self):
        a_priv = x25519.generate_private_key()
        b_priv = x25519.generate_private_key()
        c_priv = x25519.generate_private_key()
        b_pub = x25519.derive_public_key(b_priv)
        c_pub = x25519.derive_public_key(c_priv)
        self.assertNotEqual(
            x25519.compute_shared_secret(a_priv, b_pub),
            x25519.compute_shared_secret(a_priv, c_pub),
        )

    def test_rejects_wrong_length_inputs(self):
        with self.assertRaises(ValueError):
            x25519.x25519(b"short", b"\x00" * 32)
        with self.assertRaises(ValueError):
            x25519.x25519(b"\x00" * 32, b"short")

    def test_all_zero_peer_key_rejected_as_degenerate(self):
        priv = x25519.generate_private_key()
        with self.assertRaises(ValueError):
            x25519.compute_shared_secret(priv, b"\x00" * 32)

    @unittest.skipUnless(_OPENSSL, "openssl CLI not available")
    def test_cross_check_against_openssl(self):
        with tempfile.TemporaryDirectory() as d:
            alice_pem = os.path.join(d, "alice.pem")
            bob_pem = os.path.join(d, "bob.pem")
            subprocess.run(["openssl", "genpkey", "-algorithm", "X25519", "-out", alice_pem],
                            check=True, capture_output=True)
            subprocess.run(["openssl", "genpkey", "-algorithm", "X25519", "-out", bob_pem],
                            check=True, capture_output=True)

            def parse(path):
                text = subprocess.run(["openssl", "pkey", "-in", path, "-text", "-noout"],
                                       check=True, capture_output=True, text=True).stdout
                priv_hex = re.search(r"priv:\n((?:\s+[0-9a-f:]+\n)+)", text).group(1)
                pub_hex = re.search(r"pub:\n((?:\s+[0-9a-f:]+\n)+)", text).group(1)
                clean = lambda s: bytes.fromhex(s.replace(":", "").replace("\n", "").replace(" ", ""))
                return clean(priv_hex), clean(pub_hex)

            alice_priv, alice_pub_expected = parse(alice_pem)
            bob_priv, bob_pub_expected = parse(bob_pem)

            self.assertEqual(x25519.derive_public_key(alice_priv), alice_pub_expected)
            self.assertEqual(x25519.derive_public_key(bob_priv), bob_pub_expected)

            bob_pub_path = os.path.join(d, "bob_pub.pem")
            with open(bob_pub_path, "w") as f:
                subprocess.run(["openssl", "pkey", "-in", bob_pem, "-pubout"],
                                check=True, stdout=f)
            shared_path = os.path.join(d, "shared.bin")
            subprocess.run(["openssl", "pkeyutl", "-derive", "-inkey", alice_pem,
                             "-peerkey", bob_pub_path, "-out", shared_path],
                            check=True, capture_output=True)
            with open(shared_path, "rb") as f:
                openssl_shared = f.read()

            ours = x25519.compute_shared_secret(alice_priv, bob_pub_expected)
            self.assertEqual(ours, openssl_shared)


if __name__ == "__main__":
    unittest.main()
