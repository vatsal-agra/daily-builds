import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from bellman.cli import main


def run_cli(args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(args)
    return code, out.getvalue()


class TestCLI(unittest.TestCase):
    def test_oracle_command(self):
        code, out = run_cli(["oracle", "--rows", "3", "--cols", "4"])
        self.assertEqual(code, 0)
        self.assertIn("agree", out.lower())
        self.assertIn("V*(start)", out)

    def test_gridworld_command(self):
        code, out = run_cli(["gridworld", "--episodes", "60", "--seed", "0"])
        self.assertEqual(code, 0)
        self.assertIn("DP-optimal return", out)
        self.assertIn("Q-Learning greedy return", out)

    def test_cartpole_command(self):
        code, out = run_cli(["cartpole", "--episodes", "25", "--seed", "0"])
        self.assertEqual(code, 0)
        self.assertIn("Trained policy eval mean", out)

    def test_blackjack_command(self):
        code, out = run_cli(["blackjack", "--episodes", "5000", "--seed", "0"])
        self.assertEqual(code, 0)
        self.assertIn("Agreement vs. optimal policy", out)

    def test_viz_command_writes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = str(Path(tmp) / "report.html")
            code, out = run_cli([
                "viz", "--out", out_path,
                "--gridworld-episodes", "40", "--cartpole-episodes", "20",
                "--skip-blackjack",
            ])
            self.assertEqual(code, 0)
            self.assertTrue(Path(out_path).exists())
            self.assertGreater(Path(out_path).stat().st_size, 1000)

    def test_missing_command_errors(self):
        with self.assertRaises(SystemExit):
            main([])


if __name__ == "__main__":
    unittest.main()
