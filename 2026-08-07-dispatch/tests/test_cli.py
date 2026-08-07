import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
CLI = ROOT / "cli.py"


def run_cli(*args):
    return subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True, cwd=ROOT)


class HappyPathTest(unittest.TestCase):
    def test_run_fcfs(self):
        r = run_cli("run", "--algo", "fcfs", "--workload", "textbook_fcfs_sjf")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("avg waiting=5.75", r.stdout)

    def test_run_priority_aging(self):
        r = run_cli("run", "--algo", "priority-aging", "--workload", "mixed_general",
                     "--aging-rate", "1", "--aging-period", "3")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Priority (aging)", r.stdout)

    def test_compare(self):
        r = run_cli("compare", "--workload", "mixed_general")
        self.assertEqual(r.returncode, 0, r.stderr)
        for algo in ("FCFS", "SJF", "SRTF", "Round Robin", "MLFQ"):
            self.assertIn(algo, r.stdout)

    def test_vm_all(self):
        r = run_cli("vm", "--algo", "all", "--ref", "belady", "--frames", "3")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("faults=9", r.stdout)
        self.assertIn("anomaly CONFIRMED", r.stdout)

    def test_deadlock_bankers(self):
        r = run_cli("deadlock", "--mode", "bankers", "--available", "[3,3,2]",
                     "--max", "[[7,5,3],[3,2,2],[9,0,2],[2,2,2],[4,3,3]]",
                     "--allocation", "[[0,1,0],[2,0,0],[3,0,2],[2,1,1],[0,0,2]]")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("SAFE state", r.stdout)

    def test_deadlock_detect(self):
        r = run_cli("deadlock", "--mode", "detect",
                     "--assignment", '[["R0","P0"],["R1","P1"]]',
                     "--request-edges", '[["P0","R1"],["P1","R0"]]')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("DEADLOCK DETECTED", r.stdout)

    def test_generate(self):
        out = Path("/tmp/dispatch_cli_test_generate.json")
        try:
            r = run_cli("generate", "--n", "5", "--rate", "0.3", "--seed", "1", "--output", str(out))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(out.exists())
            self.assertIn('"pid": "G0"', out.read_text())
        finally:
            out.unlink(missing_ok=True)

    def test_report(self):
        out = Path("/tmp/dispatch_cli_test_report.html")
        try:
            r = run_cli("report", "--workload", "mixed_general", "--vm-ref", "belady",
                         "--frames", "3", "--output", str(out))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(out.exists())
            self.assertGreater(out.stat().st_size, 1000)
        finally:
            out.unlink(missing_ok=True)

    def test_demo(self):
        r = run_cli("demo")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Belady's Anomaly", r.stdout)
        self.assertIn("Banker's algorithm", r.stdout)

    def test_help(self):
        r = run_cli("--help")
        self.assertEqual(r.returncode, 0, r.stderr)


class ErrorPathTest(unittest.TestCase):
    """Every error path must print a clean `error: ...` line and exit 1 --
    never a raw Python traceback."""

    def _assert_clean_error(self, r):
        self.assertEqual(r.returncode, 1)
        self.assertIn("error:", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_unknown_workload_preset(self):
        self._assert_clean_error(run_cli("run", "--algo", "fcfs", "--workload", "nope"))

    def test_zero_quantum(self):
        self._assert_clean_error(run_cli("run", "--algo", "rr", "--workload", "textbook_fcfs_sjf", "--quantum", "0"))

    def test_zero_vm_frames(self):
        self._assert_clean_error(run_cli("vm", "--algo", "fifo", "--ref", "belady", "--frames", "0"))

    def test_zero_boost_interval(self):
        self._assert_clean_error(run_cli("run", "--algo", "mlfq", "--workload", "mixed_general", "--boost", "0"))

    def test_zero_aging_period(self):
        self._assert_clean_error(run_cli("run", "--algo", "priority-aging", "--workload", "mixed_general",
                                          "--aging-period", "0"))

    def test_malformed_deadlock_matrices(self):
        self._assert_clean_error(run_cli("deadlock", "--mode", "bankers",
                                          "--available", "[3,3]",
                                          "--max", "[[7,5,3]]", "--allocation", "[[0,1,0]]"))

    def test_generate_zero_n(self):
        self._assert_clean_error(run_cli("generate", "--n", "0", "--rate", "0.3", "--output", "/tmp/x.json"))

    def test_bad_algo_choice_rejected_by_argparse(self):
        r = run_cli("run", "--algo", "not-an-algo", "--workload", "mixed_general")
        self.assertEqual(r.returncode, 2)  # argparse's own usage-error exit code
        self.assertNotIn("Traceback", r.stderr)


if __name__ == "__main__":
    unittest.main()
