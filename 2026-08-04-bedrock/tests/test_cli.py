import json
import os
import subprocess
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_cli(*args, cwd):
    env = dict(os.environ, PYTHONPATH=PROJECT_ROOT)
    result = subprocess.run(
        [sys.executable, "-m", "bedrock.cli", *args],
        cwd=cwd, env=env, capture_output=True, text=True, timeout=60,
    )
    return result


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.data = os.path.join(self.tmpdir.name, "state.json")

    def tearDown(self):
        self.tmpdir.cleanup()

    def _keygen(self):
        result = run_cli("--data", self.data, "keygen", cwd=self.tmpdir.name)
        self.assertEqual(result.returncode, 0, result.stderr)
        for line in result.stdout.splitlines():
            if line.startswith("address:"):
                return line.split()[1]
        raise AssertionError("no address in keygen output")

    def test_keygen_creates_state_file(self):
        addr = self._keygen()
        self.assertTrue(os.path.exists(self.data))
        with open(self.data) as f:
            data = json.load(f)
        self.assertIn(addr, data["wallets"])

    def test_keygen_twice_preserves_both_wallets(self):
        a1 = self._keygen()
        a2 = self._keygen()
        self.assertNotEqual(a1, a2)
        with open(self.data) as f:
            data = json.load(f)
        self.assertEqual(set(data["wallets"]), {a1, a2})

    def test_chain_on_fresh_data_shows_genesis(self):
        result = run_cli("--data", self.data, "chain", cwd=self.tmpdir.name)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("height: 0", result.stdout)

    def test_balance_on_fresh_data_is_zero(self):
        addr = self._keygen()
        result = run_cli("--data", self.data, "balance", addr, cwd=self.tmpdir.name)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "0.00000000")

    def test_mine_credits_reward_and_persists(self):
        addr = self._keygen()
        result = run_cli("--data", self.data, "mine", addr, cwd=self.tmpdir.name)
        self.assertEqual(result.returncode, 0, result.stderr)
        bal = run_cli("--data", self.data, "balance", addr, cwd=self.tmpdir.name)
        self.assertEqual(bal.stdout.strip(), "50.00000000")

    def test_send_and_receive_end_to_end(self):
        a1 = self._keygen()
        a2 = self._keygen()
        run_cli("--data", self.data, "mine", a1, cwd=self.tmpdir.name)
        send = run_cli("--data", self.data, "send", a1, a2, "5", "--fee", "0.00001", cwd=self.tmpdir.name)
        self.assertEqual(send.returncode, 0, send.stderr)
        self.assertIn("broadcast txid:", send.stdout)
        run_cli("--data", self.data, "mine", a1, cwd=self.tmpdir.name)
        bal = run_cli("--data", self.data, "balance", a2, cwd=self.tmpdir.name)
        self.assertEqual(bal.stdout.strip(), "5.00000000")

    def test_validate_confirms_persisted_chain(self):
        addr = self._keygen()
        run_cli("--data", self.data, "mine", addr, cwd=self.tmpdir.name)
        result = run_cli("--data", self.data, "validate", cwd=self.tmpdir.name)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("VALID:", result.stdout)

    # -- error paths: every one must exit non-zero with a clean message, never a traceback --

    def test_send_to_invalid_address_clean_error(self):
        a1 = self._keygen()
        result = run_cli("--data", self.data, "send", a1, "not-a-real-address", "1", cwd=self.tmpdir.name)
        self.assertEqual(result.returncode, 1)
        self.assertIn("not a valid Bedrock address", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_send_from_unknown_wallet_clean_error(self):
        a2 = self._keygen()
        result = run_cli("--data", self.data, "send", "SomeUnknownAddress", a2, "1", cwd=self.tmpdir.name)
        self.assertEqual(result.returncode, 1)
        self.assertIn("no local wallet", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_send_insufficient_funds_clean_error(self):
        a1 = self._keygen()
        a2 = self._keygen()
        run_cli("--data", self.data, "mine", a1, cwd=self.tmpdir.name)
        result = run_cli("--data", self.data, "send", a1, a2, "999999", cwd=self.tmpdir.name)
        self.assertEqual(result.returncode, 1)
        self.assertIn("insufficient funds", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_send_garbage_amount_clean_error(self):
        a1 = self._keygen()
        a2 = self._keygen()
        run_cli("--data", self.data, "mine", a1, cwd=self.tmpdir.name)
        result = run_cli("--data", self.data, "send", a1, a2, "not-a-number", cwd=self.tmpdir.name)
        self.assertEqual(result.returncode, 1)
        self.assertIn("not a valid decimal amount", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_excess_precision_amount_clean_error(self):
        a1 = self._keygen()
        a2 = self._keygen()
        run_cli("--data", self.data, "mine", a1, cwd=self.tmpdir.name)
        result = run_cli("--data", self.data, "send", a1, a2, "1.123456789", cwd=self.tmpdir.name)
        self.assertEqual(result.returncode, 1)
        self.assertIn("decimal places", result.stderr)

    def test_mine_invalid_address_clean_error(self):
        result = run_cli("--data", self.data, "mine", "garbage-address", cwd=self.tmpdir.name)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)

    def test_balance_invalid_address_clean_error(self):
        result = run_cli("--data", self.data, "balance", "garbage", cwd=self.tmpdir.name)
        self.assertEqual(result.returncode, 1)
        self.assertIn("not a valid Bedrock address", result.stderr)

    def test_validate_missing_file_clean_error(self):
        result = run_cli("--data", os.path.join(self.tmpdir.name, "nope.json"), "validate", cwd=self.tmpdir.name)
        self.assertEqual(result.returncode, 1)
        self.assertIn("no state file", result.stderr)

    def test_no_command_shows_usage_not_traceback(self):
        result = run_cli(cwd=self.tmpdir.name)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
