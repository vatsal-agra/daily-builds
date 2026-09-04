import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_cli(*args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "matchbook.cli", *args],
        cwd=cwd or REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


class TestCliHappyPaths(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_run_prints_valid_json_summary(self):
        result = run_cli("run", "--ticks", "50", "--seed", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertIn("trade_count", summary)

    def test_viz_writes_a_file(self):
        out = os.path.join(self.tmpdir, "session.html")
        result = run_cli("viz", "--ticks", "50", "--seed", "1", "--out", out)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.path.exists(out))
        with open(out, "r", encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn("<html", content)
        self.assertIn("DATA", content)

    def test_run_then_replay_agree(self):
        journal = os.path.join(self.tmpdir, "x.journal")
        r1 = run_cli("run", "--ticks", "80", "--seed", "3", "--journal", journal)
        self.assertEqual(r1.returncode, 0, r1.stderr)
        r2 = run_cli("replay", journal)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        s1 = json.loads(r1.stdout)
        s2 = json.loads(r2.stdout)
        self.assertEqual(s1, s2)

    def test_crash_demo_reports_matching_fingerprints(self):
        journal = os.path.join(self.tmpdir, "crash.journal")
        result = run_cli("crash-demo", "--journal", journal, "--ticks", "100")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["fingerprints_match"])

    def test_demo_subcommand_runs_clean(self):
        journal = os.path.join(self.tmpdir, "demo.journal")
        out = os.path.join(self.tmpdir, "demo.html")
        result = run_cli("demo", "--journal", journal, "--out", out)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Demo complete", result.stdout)
        self.assertTrue(os.path.exists(out))


class TestCliAdversarialInput(unittest.TestCase):
    """Regression coverage for the input-handling bugs found in REVIEW.md."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_run_rejects_zero_ticks(self):
        result = run_cli("run", "--ticks", "0")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be positive", result.stderr)

    def test_run_rejects_negative_ticks(self):
        result = run_cli("run", "--ticks", "-5")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be positive", result.stderr)

    def test_viz_rejects_zero_ticks_like_run_does(self):
        out = os.path.join(self.tmpdir, "bad.html")
        result = run_cli("viz", "--ticks", "0", "--out", out)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be positive", result.stderr)
        self.assertFalse(os.path.exists(out), "must not write a broken HTML file")

    def test_crash_demo_rejects_zero_ticks(self):
        journal = os.path.join(self.tmpdir, "z.journal")
        result = run_cli("crash-demo", "--journal", journal, "--ticks", "0")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be positive", result.stderr)

    def test_replay_missing_file_gives_clean_error(self):
        result = run_cli("replay", os.path.join(self.tmpdir, "nope.journal"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not found", result.stderr)

    def test_replay_wrong_symbols_gives_actionable_error_not_a_bare_keyerror(self):
        journal = os.path.join(self.tmpdir, "sym.journal")
        r1 = run_cli("run", "--ticks", "30", "--symbols", "ACME", "--journal", journal)
        self.assertEqual(r1.returncode, 0, r1.stderr)
        r2 = run_cli("replay", journal, "--symbols", "WRONGSYM")
        self.assertNotEqual(r2.returncode, 0)
        self.assertNotEqual(r2.stderr.strip(), "error: 'ACME'")
        self.assertIn("--symbols", r2.stderr)

    def test_replay_no_longer_accepts_dead_risk_flags(self):
        result = run_cli("replay", "--help")
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("--position-limit", result.stdout)
        self.assertNotIn("--fat-finger-pct", result.stdout)
        self.assertNotIn("--max-order-qty", result.stdout)

    def test_duplicate_symbols_are_deduped(self):
        result = run_cli("run", "--ticks", "10", "--symbols", "ACME,ACME,acme")
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(list(summary["last_price"].keys()), ["ACME"])

    def test_empty_symbols_string_rejected_by_argparse(self):
        result = run_cli("run", "--symbols", "  ,, ")
        self.assertNotEqual(result.returncode, 0)

    def test_no_subcommand_prints_usage_not_a_traceback(self):
        result = run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)

    def test_negative_start_price_rejected(self):
        result = run_cli("run", "--ticks", "10", "--start-price", "-5")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--start-price", result.stderr)

    def test_zero_start_price_rejected(self):
        result = run_cli("run", "--ticks", "10", "--start-price", "0")
        self.assertNotEqual(result.returncode, 0)

    def test_negative_volatility_rejected(self):
        result = run_cli("run", "--ticks", "10", "--vol", "-1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--vol", result.stderr)

    def test_negative_agent_count_rejected(self):
        result = run_cli("run", "--ticks", "10", "--market-makers", "-1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--market-makers", result.stderr)

    def test_journal_in_nonexistent_directory_gives_clean_error(self):
        result = run_cli("run", "--ticks", "10", "--journal", "/no/such/dir/x.journal")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("--journal", result.stderr)

    def test_viz_rejects_the_same_bad_input_as_run(self):
        out = os.path.join(self.tmpdir, "bad2.html")
        result = run_cli("viz", "--ticks", "10", "--start-price", "-1", "--out", out)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(os.path.exists(out))

    def test_default_market_maker_count_matches_simulation_config(self):
        """Regression test: the CLI's own --market-makers argparse default
        once drifted out of sync with SimulationConfig's default (1 vs 2)
        after a mid-build retune, silently running every default `viz`/`run`
        with only one market maker instead of two. Assert they agree."""
        from matchbook.simulator import SimulationConfig
        from matchbook.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["run", "--ticks", "1"])
        self.assertEqual(args.market_makers, SimulationConfig().n_market_makers)
        self.assertEqual(args.noise_traders, SimulationConfig().n_noise_traders)
        self.assertEqual(args.momentum_traders, SimulationConfig().n_momentum_traders)
        self.assertEqual(args.informed_traders, SimulationConfig().n_informed_traders)


if __name__ == "__main__":
    unittest.main()
