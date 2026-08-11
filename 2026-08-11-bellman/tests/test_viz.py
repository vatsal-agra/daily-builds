import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bellman.viz.report import _downsample, build_report


class TestDownsample(unittest.TestCase):
    def test_empty_input_returns_empty_not_a_crash(self):
        self.assertEqual(_downsample([], 100), [])

    def test_short_input_is_returned_unchanged(self):
        self.assertEqual(_downsample([1.0, 2.0, 3.0], 100), [1.0, 2.0, 3.0])

    def test_last_bucket_always_reaches_the_final_value(self):
        # a length that doesn't divide evenly by the bucket count used to
        # drop the final data point to float rounding in (i+1)*bucket
        values = list(range(1000))
        out = _downsample(values, 120)
        self.assertEqual(len(out), 120)
        # the last bucket's average must include index 999, not stop at 998
        self.assertGreater(out[-1], 990)

    def test_downsampled_length_matches_bucket_count(self):
        values = [float(i) for i in range(500)]
        out = _downsample(values, 50)
        self.assertEqual(len(out), 50)

    def test_preserves_overall_trend(self):
        values = [float(i) for i in range(300)]
        out = _downsample(values, 30)
        self.assertLess(out[0], out[-1])


class TestReportBuildsRealHTML(unittest.TestCase):
    """A fast smoke build (tiny episode counts) -- just checks the report
    actually runs every code path and produces valid, non-placeholder
    embedded data. The full-scale report is built separately by demo.sh."""

    def test_report_embeds_real_computed_data(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "report.html")
            build_report(out_path=out, seed=0, dqn_episodes=5,
                          reinforce_episodes=5, tabular_episodes=20)
            with open(out) as f:
                html = f.read()
            self.assertIn("<title>Bellman", html)
            start = html.index("const DATA = ") + len("const DATA = ")
            end = html.index(";\n", start)
            data = json.loads(html[start:end])
            self.assertIn("gridworld", data["gridworlds"])
            self.assertGreater(len(data["cartpole"]["dqn"]["reward_curve"]), 0)
            self.assertGreater(len(data["cliff_compare"]["qlearning_path"]), 0)


if __name__ == "__main__":
    unittest.main()
