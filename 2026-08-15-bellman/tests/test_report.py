import json
import re
import tempfile
import unittest
from pathlib import Path

from bellman.report import build_report
from bellman.train import run_gridworld_experiment, run_cartpole_experiment, run_blackjack_experiment


class TestReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = {
            "gridworld": run_gridworld_experiment(episodes=60, seed=0),
            "cartpole": run_cartpole_experiment(episodes=20, seed=0),
            "blackjack": run_blackjack_experiment(episodes=5000, seed=0),
        }

    def test_report_writes_html_with_no_unresolved_placeholders(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.html"
            build_report(self.bundle, out)
            html = out.read_text()
            self.assertNotIn("__DATA_JSON__", html)
            self.assertNotIn("__APP_JS__", html)
            self.assertTrue(html.startswith("<!doctype html>"))

    def test_embedded_json_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.html"
            build_report(self.bundle, out)
            html = out.read_text()
            m = re.search(
                r'<script id="bellman-data" type="application/json">(.*?)</script>',
                html, re.S)
            self.assertIsNotNone(m)
            data = json.loads(m.group(1))
            self.assertIn("gridworld", data)
            self.assertIn("cartpole", data)
            self.assertIn("blackjack", data)
            self.assertEqual(data["gridworld"]["optimal_return"], self.bundle["gridworld"]["optimal_return"])

    def test_no_stray_closing_script_tag_in_payload(self):
        # A literal "</script>" inside the JSON blob would truncate the page;
        # report.py must escape it. Force one into the bundle and check it
        # doesn't break the embedding <script> tag's structure.
        bundle = dict(self.bundle)
        bundle["gridworld"] = dict(bundle["gridworld"])
        bundle["gridworld"]["_poison"] = "</script><script>alert(1)</script>"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.html"
            build_report(bundle, out)
            html = out.read_text()
            # exactly the two real <script> tags this template ships (data + app js)
            self.assertEqual(html.count("<script id=\"bellman-data\""), 1)
            m = re.search(
                r'<script id="bellman-data" type="application/json">(.*?)</script>',
                html, re.S)
            data = json.loads(m.group(1))
            self.assertEqual(data["gridworld"]["_poison"], "</script><script>alert(1)</script>")

    def test_missing_blackjack_bundle_is_handled_gracefully(self):
        bundle = {"gridworld": self.bundle["gridworld"], "cartpole": self.bundle["cartpole"]}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.html"
            build_report(bundle, out)
            html = out.read_text()
            self.assertIn("blackjack", html.lower())


if __name__ == "__main__":
    unittest.main()
