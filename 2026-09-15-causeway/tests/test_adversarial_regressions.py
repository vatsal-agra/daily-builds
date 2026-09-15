"""Pins every bug found during Phase 3's adversarial review as a permanent
regression test, so none of them can silently come back."""
import subprocess
import sys
import unittest

from causeway.clock import VirtualClock
from causeway.connection import Connection
from causeway.wire import SimulatedLink


class TestInputValidation(unittest.TestCase):
    def test_zero_mss_rejected_at_construction(self):
        clock = VirtualClock()
        link = SimulatedLink(clock)
        with self.assertRaises(ValueError):
            Connection("client", link.endpoint_a, clock, mss=0)

    def test_negative_mss_rejected(self):
        clock = VirtualClock()
        link = SimulatedLink(clock)
        with self.assertRaises(ValueError):
            Connection("client", link.endpoint_a, clock, mss=-10)

    def test_zero_recv_capacity_rejected(self):
        clock = VirtualClock()
        link = SimulatedLink(clock)
        with self.assertRaises(ValueError):
            Connection("client", link.endpoint_a, clock, recv_capacity=0)


def _run_cli(*args):
    return subprocess.run([sys.executable, "-m", "causeway.cli", *args],
                           capture_output=True, text=True, timeout=30)


class TestCliCleanErrors(unittest.TestCase):
    """Each of these used to crash with a raw Python traceback; now they
    should fail with a clean one-line message and exit code 1."""

    def test_negative_bytes(self):
        r = _run_cli("demo", "--bytes", "-5")
        self.assertEqual(r.returncode, 1)
        self.assertIn("--bytes", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_loss_out_of_range(self):
        r = _run_cli("demo", "--loss", "5.0", "--bytes", "1000")
        self.assertEqual(r.returncode, 1)
        self.assertIn("--loss", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_mss_zero(self):
        r = _run_cli("demo", "--mss", "0", "--bytes", "1000")
        self.assertEqual(r.returncode, 1)
        self.assertIn("--mss", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_send_missing_file(self):
        r = _run_cli("send", "/no/such/file.bin", "--peer", "127.0.0.1:1")
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr)

    def test_demo_still_works_after_random_flag_removed(self):
        r = _run_cli("demo", "--bytes", "2000", "--loss", "0.05")
        self.assertEqual(r.returncode, 0)
        self.assertIn("byte-exact match: True", r.stdout)


if __name__ == "__main__":
    unittest.main()
