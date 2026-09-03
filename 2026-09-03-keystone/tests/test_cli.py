"""Subprocess-driven CLI smoke tests -- exercises `keystone` exactly as a
user would run it, including its input-validation and error paths."""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_next_port = [23500]


def alloc_port():
    p = _next_port[0]
    _next_port[0] += 20
    return p


def run_cli(*args, timeout=40):
    return subprocess.run(
        [sys.executable, "-m", "keystone", *args],
        capture_output=True, text=True, cwd=str(ROOT), timeout=timeout,
    )


class TestKeygen(unittest.TestCase):
    def test_keygen_outputs_valid_looking_wallet(self):
        r = run_cli("keygen")
        self.assertEqual(r.returncode, 0)
        self.assertIn("private key:", r.stdout)
        self.assertIn("address:", r.stdout)

    def test_keygen_is_random(self):
        r1 = run_cli("keygen")
        r2 = run_cli("keygen")
        self.assertNotEqual(r1.stdout, r2.stdout)


class TestScriptDemo(unittest.TestCase):
    def test_script_demo_passes(self):
        r = run_cli("script-demo")
        self.assertEqual(r.returncode, 0)
        self.assertIn("RESULT: PASS", r.stdout)


class TestDemo(unittest.TestCase):
    def test_demo_end_to_end(self):
        port = alloc_port()
        r = run_cli("demo", "--nodes", "3", "--seconds", "6", "--base-port", str(port), timeout=40)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("RESULT: PASS", r.stdout)
        self.assertIn("converged on one tip: True", r.stdout)
        self.assertIn("wallet-to-wallet payment confirmed on-chain: True", r.stdout)

    def test_demo_rejects_zero_nodes(self):
        r = run_cli("demo", "--nodes", "0", "--seconds", "1")
        self.assertEqual(r.returncode, 2)
        self.assertIn("must be at least 1", r.stderr)

    def test_demo_rejects_negative_nodes(self):
        r = run_cli("demo", "--nodes", "-3", "--seconds", "1")
        self.assertEqual(r.returncode, 2)

    def test_demo_single_node_still_works(self):
        port = alloc_port()
        r = run_cli("demo", "--nodes", "1", "--seconds", "3", "--base-port", str(port))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("converged on one tip: True", r.stdout)

    def test_port_collision_gives_clean_error_not_traceback(self):
        import socket
        port = alloc_port()
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        blocker.bind(("127.0.0.1", port))
        blocker.listen(1)
        try:
            r = run_cli("demo", "--nodes", "2", "--seconds", "2", "--base-port", str(port))
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("Address already in use", r.stderr)
            self.assertNotIn("Traceback", r.stderr)
        finally:
            blocker.close()


class TestExplorerCLI(unittest.TestCase):
    def test_explorer_rejects_zero_nodes(self):
        r = run_cli("explorer", "--nodes", "0", "--seconds", "1")
        self.assertEqual(r.returncode, 2)
        self.assertIn("must be at least 1", r.stderr)

    def test_explorer_runs_and_serves(self):
        import urllib.request
        port = alloc_port()
        http_port = alloc_port()
        proc = subprocess.Popen(
            [sys.executable, "-m", "keystone", "explorer", "--nodes", "2", "--seconds", "8",
             "--base-port", str(port), "--port", str(http_port)],
            cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            import time
            deadline = time.time() + 10
            body = None
            while time.time() < deadline:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{http_port}/", timeout=1) as resp:
                        body = resp.read().decode()
                        break
                except Exception:
                    time.sleep(0.3)
            self.assertIsNotNone(body, "explorer never became reachable")
            self.assertIn("Keystone", body)
            self.assertIn("<title>", body)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            if proc.stdout:
                proc.stdout.close()
            if proc.stderr:
                proc.stderr.close()


if __name__ == "__main__":
    unittest.main()
