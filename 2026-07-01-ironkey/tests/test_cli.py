from . import _path  # noqa: F401
import os
import subprocess
import sys
import tempfile
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_CLI = os.path.join(_ROOT, "cli.py")


def run_cli(*args, input=None):
    return subprocess.run(
        [sys.executable, _CLI, *args],
        capture_output=True, text=True, input=input, cwd=_ROOT,
    )


class TestCLIBasics(unittest.TestCase):
    def test_hash(self):
        r = run_cli("hash", "--text", "hello")
        self.assertEqual(r.returncode, 0)
        import hashlib
        self.assertEqual(r.stdout.strip(), hashlib.sha256(b"hello").hexdigest())

    def test_hmac(self):
        r = run_cli("hmac", "--key", "k", "--text", "m")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(len(r.stdout.strip()), 64)

    def test_kdf(self):
        r = run_cli("kdf", "--password", "pw", "--iterations", "100")
        self.assertEqual(r.returncode, 0)
        self.assertIn("key=", r.stdout)

    def test_bad_hex_key_gives_clean_error_not_traceback(self):
        r = run_cli("hmac", "--key-hex", "nothex", "--text", "x")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("error:", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_no_command_shows_usage(self):
        r = run_cli()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("usage", r.stderr)


class TestCLIAES(unittest.TestCase):
    def test_gcm_round_trip(self):
        key_hex = os.urandom(32).hex()
        with tempfile.TemporaryDirectory() as d:
            ct_path = os.path.join(d, "ct.bin")
            r1 = run_cli("aes", "encrypt", "--key-hex", key_hex, "--mode", "gcm",
                         "--text", "cli aes test", "--out", ct_path)
            self.assertEqual(r1.returncode, 0)
            r2 = run_cli("aes", "decrypt", "--key-hex", key_hex, "--mode", "gcm", "--in", ct_path)
            self.assertEqual(r2.returncode, 0)
            self.assertEqual(r2.stdout, "cli aes test")

    def test_cbc_round_trip(self):
        key_hex = os.urandom(32).hex()
        with tempfile.TemporaryDirectory() as d:
            ct_path = os.path.join(d, "ct.bin")
            run_cli("aes", "encrypt", "--key-hex", key_hex, "--mode", "cbc",
                     "--text", "cli aes cbc test", "--out", ct_path)
            r2 = run_cli("aes", "decrypt", "--key-hex", key_hex, "--mode", "cbc", "--in", ct_path)
            self.assertEqual(r2.returncode, 0)
            self.assertEqual(r2.stdout, "cli aes cbc test")

    def test_wrong_key_length_clean_error(self):
        r = run_cli("aes", "encrypt", "--key-hex", "aabb", "--text", "x")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("error:", r.stderr)


class TestCLIRSA(unittest.TestCase):
    def test_genkey_encrypt_decrypt_sign_verify(self):
        with tempfile.TemporaryDirectory() as d:
            pub = os.path.join(d, "pub.json")
            priv = os.path.join(d, "priv.json")
            r = run_cli("rsa", "genkey", "--bits", "1024", "--pub-out", pub, "--priv-out", priv)
            self.assertEqual(r.returncode, 0)

            ct = os.path.join(d, "ct.bin")
            run_cli("rsa", "encrypt", "--pub", pub, "--text", "rsa cli test", "--out", ct)
            r2 = run_cli("rsa", "decrypt", "--priv", priv, "--in", ct)
            self.assertEqual(r2.stdout, "rsa cli test")

            sig = os.path.join(d, "sig.bin")
            run_cli("rsa", "sign", "--priv", priv, "--text", "sign this", "--out", sig)
            r3 = run_cli("rsa", "verify", "--pub", pub, "--text", "sign this", "--sig", sig)
            self.assertEqual(r3.returncode, 0)
            self.assertEqual(r3.stdout.strip(), "VALID")

            r4 = run_cli("rsa", "verify", "--pub", pub, "--text", "tampered", "--sig", sig)
            self.assertEqual(r4.returncode, 1)
            self.assertEqual(r4.stdout.strip(), "INVALID")


class TestCLIVaultAndDH(unittest.TestCase):
    def test_vault_round_trip_and_wrong_password(self):
        with tempfile.TemporaryDirectory() as d:
            v = os.path.join(d, "secret.vault")
            r1 = run_cli("vault", "encrypt", "--password", "pw123", "--iterations", "100",
                         "--text", "vault cli test", "--out", v)
            self.assertEqual(r1.returncode, 0)
            r2 = run_cli("vault", "decrypt", "--password", "pw123", "--in", v)
            self.assertEqual(r2.stdout, "vault cli test")
            r3 = run_cli("vault", "decrypt", "--password", "wrong", "--in", v)
            self.assertNotEqual(r3.returncode, 0)

    def test_dh_demo(self):
        r = run_cli("dh", "demo")
        self.assertEqual(r.returncode, 0)
        self.assertIn("MATCH", r.stdout)

    def test_session_demo(self):
        r = run_cli("session", "demo")
        self.assertEqual(r.returncode, 0)

    def test_attack_demo(self):
        r = run_cli("attack", "demo", "--text", "cli attack test")
        self.assertEqual(r.returncode, 0)
        self.assertIn("ATTACK SUCCEEDED", r.stdout)

    def test_viz_generates_file(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "viz.html")
            r = run_cli("viz", "--out", out)
            self.assertEqual(r.returncode, 0)
            self.assertTrue(os.path.exists(out))
            self.assertGreater(os.path.getsize(out), 1000)


if __name__ == "__main__":
    unittest.main()
