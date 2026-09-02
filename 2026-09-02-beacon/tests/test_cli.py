import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "beacon.cli", *args],
        cwd=REPO_DIR, capture_output=True, text=True, timeout=60,
    )


class TestCliValidation(unittest.TestCase):
    def test_zero_particles_rejected_cleanly(self):
        result = run_cli("run", "--world", "open", "--particles", "0", "--max-steps", "5")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--particles", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_malformed_waypoint_rejected_cleanly(self):
        result = run_cli("run", "--mode", "waypoints", "--waypoint", "not-a-point", "--max-steps", "5")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--waypoint", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_waypoints_mode_without_any_waypoint_rejected(self):
        result = run_cli("run", "--mode", "waypoints", "--max-steps", "5")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)

    def test_unknown_world_rejected_by_argparse(self):
        result = run_cli("run", "--world", "nonexistent", "--max-steps", "5")
        self.assertNotEqual(result.returncode, 0)


class TestCliRunHappyPath(unittest.TestCase):
    def test_run_prints_valid_json_report(self):
        result = run_cli("run", "--world", "open", "--particles", "60", "--max-steps", "40")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        for key in ("world", "steps", "pose_rmse_m", "map_iou", "exploration_done"):
            self.assertIn(key, report)

    def test_demo_command_runs_all_worlds(self):
        result = run_cli("demo", "--max-steps", "40")
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = [l for l in result.stdout.strip().splitlines() if l]
        self.assertEqual(len(lines), 3)
        for line in lines:
            json.loads(line)  # must be valid JSON

    def test_viz_command_writes_a_self_contained_html_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "run.html")
            result = run_cli(
                "viz", "--world", "office", "--particles", "60",
                "--max-steps", "40", "--out", out,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(os.path.exists(out))
            with open(out) as f:
                html = f.read()
            self.assertIn("<html", html)
            self.assertIn("const DATA = ", html)
            # embedded JSON payload must actually parse
            start = html.index("const DATA = ") + len("const DATA = ")
            end = html.index(";\n", start)
            json.loads(html[start:end])


if __name__ == "__main__":
    unittest.main()
