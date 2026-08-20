import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bellman import viz


class TestMissingResults(unittest.TestCase):
    def test_missing_results_raises_clean_system_exit_naming_whats_missing(self):
        original = viz.RESULTS_DIR
        try:
            with tempfile.TemporaryDirectory() as tmp:
                viz.RESULTS_DIR = tmp  # empty directory: nothing present
                with self.assertRaises(SystemExit) as ctx:
                    viz.build_report(os.path.join(tmp, "out.html"))
                msg = str(ctx.exception)
                for key in ("qlearning", "sarsa", "cliff", "dqn", "reinforce", "ablation"):
                    self.assertIn(key, msg)
        finally:
            viz.RESULTS_DIR = original


class TestBuildReport(unittest.TestCase):
    """Builds a report from hand-fabricated minimal fixture JSON (not the
    real results/ directory, so this test is independent of whatever a
    real training run happened to produce) and checks the output is a
    well-formed, self-contained HTML page with the real data embedded."""

    def _write_fixtures(self, results_dir):
        layout = {"width": 2, "height": 2, "start": [1, 0], "goal": [0, 1], "walls": [], "cliffs": []}
        common_grid = {
            "episodes": 5, "returns": [1.0, 2.0], "moving_avg": [1.0, 1.5],
            "optimal_rollout": True, "achieved_return": -1.0, "optimal_return": -1.0,
            "action_matches": 4, "value_close": 4, "total_states": 4,
            "layout": layout, "policy": [1, 1, 1, 1], "Q": [[0, 0], [0, 0], [0, 0], [0, 0]],
        }
        cliff_layout = {"width": 3, "height": 2, "start": [1, 0], "goal": [1, 2], "walls": [], "cliffs": [[1, 1]]}
        cliff = {
            "episodes": 5,
            "qlearning": {"returns": [-5], "moving_avg": [-5], "final_avg_last50": -5,
                          "path": [[1, 0], [0, 0], [0, 1], [0, 2], [1, 2]],
                          "hugs_cliff_edge": False, "edge_fraction": 0.0},
            "sarsa": {"returns": [-5], "moving_avg": [-5], "final_avg_last50": -5,
                      "path": [[1, 0], [0, 0], [0, 1], [0, 2], [1, 2]],
                      "hugs_cliff_edge": False, "edge_fraction": 0.0},
            "diverged": False, "layout": cliff_layout,
        }
        cartpole_common = {
            "episodes": 3, "returns": [10.0, 20.0], "moving_avg": [10.0, 15.0],
            "eval_returns": [15.0], "eval_avg": 15.0, "elapsed_sec": 0.1,
            "replay": [[0.0, 0.0, 0.0, 0.0], [0.01, 0.1, 0.01, 0.1]],
        }
        ablation = {
            "episodes": 5, "n_seeds": 1,
            "variants": {
                "full": {"seeds": [0], "eval_avg_mean": 10.0, "eval_avg_std": 0.0,
                         "max_drawdown_mean": 1.0, "max_drawdown_std": 0.0, "example_moving_avg": [1.0, 2.0]},
                "no_replay": {"seeds": [0], "eval_avg_mean": 5.0, "eval_avg_std": 0.0,
                              "max_drawdown_mean": 2.0, "max_drawdown_std": 0.0, "example_moving_avg": [1.0, 1.0]},
                "no_target": {"seeds": [0], "eval_avg_mean": 3.0, "eval_avg_std": 0.0,
                              "max_drawdown_mean": 3.0, "max_drawdown_std": 0.0, "example_moving_avg": [1.0, 0.5]},
            },
        }
        for name, payload in (
            ("qlearning_simplegrid", common_grid),
            ("sarsa_simplegrid", common_grid),
            ("cliff_compare", cliff),
            ("dqn_cartpole", cartpole_common),
            ("reinforce_cartpole", cartpole_common),
            ("dqn_ablation_summary", ablation),
        ):
            with open(os.path.join(results_dir, f"{name}.json"), "w") as f:
                json.dump(payload, f)

    def test_report_builds_and_embeds_data(self):
        original = viz.RESULTS_DIR
        try:
            with tempfile.TemporaryDirectory() as tmp:
                viz.RESULTS_DIR = tmp
                self._write_fixtures(tmp)
                out_path = os.path.join(tmp, "report.html")
                viz.build_report(out_path)
                self.assertTrue(os.path.exists(out_path))
                with open(out_path) as f:
                    html = f.read()
                self.assertIn("<title>Bellman", html)
                self.assertIn("const DATA = ", html)
                self.assertIn("eval_avg_mean", html)
                # no unresolved template placeholder left behind
                self.assertNotIn("__BELLMAN_DATA__", html)
        finally:
            viz.RESULTS_DIR = original


if __name__ == "__main__":
    unittest.main()
