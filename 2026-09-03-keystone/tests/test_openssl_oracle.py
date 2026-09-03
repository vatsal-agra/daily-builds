"""Cross-verify keystone/crypto.py's from-scratch secp256k1 ECDSA against
real OpenSSL, in both directions — the same independent-oracle pattern this
repo's Ironkey build used for its own primitives. If `openssl` isn't on the
box, these tests skip cleanly rather than failing (self-consistency is
still covered exhaustively by test_crypto.py either way)."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from keystone import crypto  # noqa: E402
from der_helpers import (  # noqa: E402
    public_key_pem, private_key_pem, signature_der, parse_signature_der,
)

OPENSSL = shutil.which("openssl")


@unittest.skipUnless(OPENSSL, "openssl binary not available on this box")
class TestOpenSSLOracle(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="keystone_openssl_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _path(self, name):
        return str(Path(self.tmpdir) / name)

    def test_openssl_verifies_our_signature(self):
        """We sign; real openssl dgst -verify checks it."""
        priv = crypto.generate_private_key()
        pub = crypto.private_to_public(priv)
        message = b"keystone <-> openssl interop check, direction 1"

        digest = crypto.sha256(message)
        r, s = crypto.sign(priv, digest)
        self.assertTrue(crypto.verify(pub, digest, (r, s)), "sanity: our own verify should already accept this")

        pub_pem_path = self._path("pub.pem")
        Path(pub_pem_path).write_text(public_key_pem(pub[0], pub[1]))

        sig_path = self._path("sig.der")
        Path(sig_path).write_bytes(signature_der(r, s))

        msg_path = self._path("msg.bin")
        Path(msg_path).write_bytes(message)

        result = subprocess.run(
            [OPENSSL, "dgst", "-sha256", "-verify", pub_pem_path, "-signature", sig_path, msg_path],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, f"openssl rejected our signature: {result.stdout} {result.stderr}")
        self.assertIn("Verified OK", result.stdout)

    def test_openssl_rejects_tampered_signature(self):
        priv = crypto.generate_private_key()
        pub = crypto.private_to_public(priv)
        message = b"keystone <-> openssl interop check, tamper case"
        digest = crypto.sha256(message)
        r, s = crypto.sign(priv, digest)

        pub_pem_path = self._path("pub.pem")
        Path(pub_pem_path).write_text(public_key_pem(pub[0], pub[1]))
        sig_path = self._path("sig.der")
        Path(sig_path).write_bytes(signature_der(r, (s + 1) % crypto.N))  # tamper
        msg_path = self._path("msg.bin")
        Path(msg_path).write_bytes(message)

        result = subprocess.run(
            [OPENSSL, "dgst", "-sha256", "-verify", pub_pem_path, "-signature", sig_path, msg_path],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0, "openssl should have rejected a tampered signature")

    def test_our_verify_accepts_openssl_signature(self):
        """Real openssl signs (with a key WE generated); we verify."""
        priv = crypto.generate_private_key()
        pub = crypto.private_to_public(priv)
        message = b"keystone <-> openssl interop check, direction 2"

        priv_pem_path = self._path("priv.pem")
        Path(priv_pem_path).write_text(private_key_pem(priv, pub[0], pub[1]))
        msg_path = self._path("msg.bin")
        Path(msg_path).write_bytes(message)
        sig_path = self._path("sig.der")

        result = subprocess.run(
            [OPENSSL, "dgst", "-sha256", "-sign", priv_pem_path, "-out", sig_path, msg_path],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, f"openssl failed to sign: {result.stderr}")

        r, s = parse_signature_der(Path(sig_path).read_bytes())
        digest = crypto.sha256(message)
        self.assertTrue(crypto.verify(pub, digest, (r, s)), "our verify() rejected a real openssl signature")

    def test_openssl_confirms_our_pubkey_derivation(self):
        """openssl derives the public key from a raw private scalar we
        generated; it must match our own private_to_public()."""
        priv = crypto.generate_private_key()
        pub = crypto.private_to_public(priv)

        priv_pem_path = self._path("priv_only.pem")
        Path(priv_pem_path).write_text(private_key_pem(priv, pub[0], pub[1]))

        result = subprocess.run(
            [OPENSSL, "ec", "-in", priv_pem_path, "-pubout", "-text", "-noout"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, f"openssl ec failed: {result.stderr}")
        hex_blob = "".join(
            line.strip().replace(":", "") for line in result.stdout.splitlines() if ":" in line and "pub" not in line.lower()
        )
        self.assertIn(pub[0].to_bytes(32, "big").hex(), hex_blob.lower())


if __name__ == "__main__":
    unittest.main()
