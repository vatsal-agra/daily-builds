import json
import os
import tempfile
import unittest
import _pathsetup  # noqa: F401

from report_template import build_report


def minimal_session(agent_name="alice"):
    return {
        "total_ticks": 3, "agents": [agent_name], "rejected_actions": 0,
        "symbols": {"X": {"trades": [
            {"ts": 1, "price": 10000, "qty": 5, "aggressor_side": "BUY",
             "maker_owner": "seed", "taker_owner": agent_name},
        ], "candles": [], "depth_snapshots": [{"t": 0, "bids": [], "asks": []}]}},
        "pnl_history": {agent_name: [[1, 100]]},
        "final_inventory": {agent_name: {"X": 5}},
    }


class TestReportRendering(unittest.TestCase):
    def test_builds_valid_self_contained_html(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "report.html")
            build_report(minimal_session(), path)
            with open(path, encoding="utf-8") as f:
                html = f.read()
        self.assertIn("<html", html)
        self.assertIn("Matchbook", html)
        self.assertNotIn("__DATA__", html)   # placeholder must be substituted
        self.assertNotIn("__TITLE__", html)

    def test_script_close_tag_in_agent_name_is_escaped(self):
        malicious_name = "</script><script>window.__pwned=true</script>"
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "report.html")
            build_report(minimal_session(agent_name=malicious_name), path)
            with open(path, encoding="utf-8") as f:
                html = f.read()
        # the literal, unescaped closing sequence must never appear inside
        # the embedded JSON payload
        self.assertNotIn("</script><script>window.__pwned", html)
        self.assertIn("<\\/script><script>window.__pwned", html)

    def test_embedded_payload_is_recoverable_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "report.html")
            build_report(minimal_session(), path)
            with open(path, encoding="utf-8") as f:
                html = f.read()
        start = html.index("const DATA = ") + len("const DATA = ")
        end = html.index(";\n", start)
        payload = html[start:end].replace("<\\/", "</")
        data = json.loads(payload)
        self.assertEqual(data["agents"], ["alice"])


if __name__ == "__main__":
    unittest.main()
