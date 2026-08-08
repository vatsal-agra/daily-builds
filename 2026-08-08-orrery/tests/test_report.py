import json
import os
import tempfile
import unittest

from orrery import scenarios, report
from orrery.simulation import Simulation


class TestReport(unittest.TestCase):
    def test_history_to_traj_data_rejects_empty_history(self):
        with self.assertRaises(ValueError):
            report.history_to_traj_data([], "t", "d")

    def test_write_trajectory_report_produces_valid_looking_html(self):
        sim = Simulation.from_scenario(scenarios.binary_star(), use_barnes_hut=False)
        history = sim.run(20, 0.001)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.html")
            report.write_trajectory_report(history, "binary_star", "desc", path)
            with open(path) as f:
                content = f.read()
        self.assertIn("<!doctype html>", content.lower())
        self.assertIn("const DATA", content)
        self.assertIn("binary_star", content)
        # Embedded JSON must actually parse.
        start = content.index("const DATA = ") + len("const DATA = ")
        end = content.index(";\n", start)
        data = json.loads(content[start:end])
        self.assertEqual(len(data["frames"]), 21)  # initial + 20 steps
        self.assertEqual(len(data["names"]), 2)

    def test_collision_events_attached_to_nearest_frame(self):
        sim = Simulation.from_scenario(scenarios.binary_star(), use_barnes_hut=False, collisions=True)
        history = sim.run(10, 0.001)
        fake_log = [{"t": 0.0035, "survivor": "Alpha", "absorbed": "Beta"}]
        data = report.history_to_traj_data(history, "t", "d", collision_log=fake_log)
        self.assertEqual(len(data["collisions"]), 1)
        self.assertIn("frame", data["collisions"][0])
        self.assertGreaterEqual(data["collisions"][0]["frame"], 0)
        self.assertLess(data["collisions"][0]["frame"], len(data["frames"]))

    def test_run_benchmark_produces_timing_and_accuracy_rows(self):
        results = report.run_benchmark(ns=(5, 10), thetas=(0.0, 0.5))
        self.assertEqual(len(results["timing"]), 2)
        self.assertGreater(len(results["accuracy"]), 0)
        for row in results["timing"]:
            self.assertGreaterEqual(row["bruteforce_s"], 0)
            self.assertGreaterEqual(row["barnes_hut_s"], 0)

    def test_theta_zero_benchmark_accuracy_near_exact(self):
        results = report.run_benchmark(ns=(20,), thetas=(0.0,))
        row = results["accuracy"][0]
        self.assertEqual(row["theta"], 0.0)
        self.assertLess(row["max_rel_err"], 1e-6)

    def test_render_benchmark_html_writes_file(self):
        results = report.run_benchmark(ns=(5,), thetas=(0.5,))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bench.html")
            report.render_benchmark_html(results, path)
            with open(path) as f:
                content = f.read()
        self.assertIn("<!doctype html>", content.lower())
        self.assertIn("<svg", content)


if __name__ == "__main__":
    unittest.main()
