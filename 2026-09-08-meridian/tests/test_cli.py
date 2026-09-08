import json
import tempfile
import unittest
from pathlib import Path

from meridian.cli import main


class TestArgValidation(unittest.TestCase):
    def test_nodes_must_be_positive(self):
        with self.assertRaises(SystemExit):
            main(["run", "--nodes", "0"])

    def test_latency_max_must_be_at_least_min(self):
        with self.assertRaises(SystemExit):
            main(["run", "--latency-min", "50", "--latency-max", "10"])

    def test_loss_must_be_in_unit_interval(self):
        with self.assertRaises(SystemExit):
            main(["run", "--loss", "1.5"])
        with self.assertRaises(SystemExit):
            main(["run", "--loss", "-0.1"])

    def test_k_must_be_positive(self):
        with self.assertRaises(SystemExit):
            main(["run", "--k", "0"])

    def test_alpha_must_be_positive(self):
        with self.assertRaises(SystemExit):
            main(["run", "--alpha", "0"])

    def test_bad_int_flag_is_a_clean_argparse_error_not_a_traceback(self):
        with self.assertRaises(SystemExit):
            main(["run", "--nodes", "not-a-number"])

    def test_unknown_command_is_a_clean_error(self):
        with self.assertRaises(SystemExit):
            main(["not-a-real-command"])

    def test_filedemo_missing_file_reported_cleanly(self):
        with self.assertRaises(SystemExit):
            main(["filedemo", "/no/such/file/anywhere.bin"])


class TestRunCommand(unittest.TestCase):
    def test_small_run_succeeds(self):
        rc = main(["run", "--nodes", "10", "--seed", "1", "--ticks", "1000", "--lookups", "3"])
        self.assertEqual(rc, 0)

    def test_run_with_churn_succeeds(self):
        rc = main(["run", "--nodes", "12", "--seed", "2", "--ticks", "1500", "--churn", "--lookups", "2"])
        self.assertEqual(rc, 0)

    def test_run_with_zero_lookups(self):
        rc = main(["run", "--nodes", "5", "--ticks", "500", "--lookups", "0"])
        self.assertEqual(rc, 0)


class TestDemoCommand(unittest.TestCase):
    def test_demo_passes_all_checks_at_small_scale(self):
        rc = main(["demo", "--nodes", "18", "--seed", "7"])
        self.assertEqual(rc, 0)

    def test_demo_rejects_fewer_than_two_nodes(self):
        with self.assertRaises(SystemExit):
            main(["demo", "--nodes", "1"])

    def test_demo_can_emit_viz_trace(self):
        with tempfile.TemporaryDirectory() as td:
            out = str(Path(td) / "trace.json")
            rc = main(["demo", "--nodes", "16", "--seed", "8", "--emit-viz", out])
            self.assertEqual(rc, 0)
            payload = json.loads(Path(out).read_text())
            self.assertIn("events", payload)
            self.assertGreater(len(payload["events"]), 0)


class TestFiledemoCommand(unittest.TestCase):
    def test_round_trips_a_real_file(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "input.txt"
            src.write_bytes(b"meridian file demo payload\n" * 100)
            rc = main(["filedemo", str(src), "--nodes", "15", "--seed", "9", "--chunk-size", "256"])
            self.assertEqual(rc, 0)

    def test_round_trips_an_empty_file(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "empty.bin"
            src.write_bytes(b"")
            rc = main(["filedemo", str(src), "--nodes", "12", "--seed", "13"])
            self.assertEqual(rc, 0)

    def test_rejects_fewer_than_two_nodes(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "x.bin"
            src.write_bytes(b"abc")
            with self.assertRaises(SystemExit):
                main(["filedemo", str(src), "--nodes", "1"])

    def test_rejects_a_directory(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(SystemExit):
                main(["filedemo", td])

    def test_rejects_nonpositive_chunk_size(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "x.bin"
            src.write_bytes(b"abc")
            with self.assertRaises(SystemExit):
                main(["filedemo", str(src), "--chunk-size", "0", "--nodes", "5"])


class TestVizCommand(unittest.TestCase):
    def test_writes_valid_trace_json(self):
        with tempfile.TemporaryDirectory() as td:
            out = str(Path(td) / "sub" / "trace.json")
            rc = main(["viz", "--nodes", "14", "--seed", "10", "--out", out, "--lookups", "3", "--churn-ticks", "300"])
            self.assertEqual(rc, 0)
            payload = json.loads(Path(out).read_text())
            self.assertIn("nodes", payload)
            self.assertIn("events", payload)
            self.assertEqual(len(payload["nodes"]), 14)
            kinds = {e["kind"] for e in payload["events"]}
            self.assertIn("join", kinds)
            self.assertIn("lookup_start", kinds)

    def test_rejects_negative_churn_ticks(self):
        with self.assertRaises(SystemExit):
            main(["viz", "--churn-ticks", "-1"])

    def test_rejects_negative_lookups(self):
        with self.assertRaises(SystemExit):
            main(["viz", "--lookups", "-1"])

    def test_html_out_produces_a_standalone_viewer_with_trace_embedded(self):
        with tempfile.TemporaryDirectory() as td:
            json_out = str(Path(td) / "trace.json")
            html_out = str(Path(td) / "replay.html")
            rc = main(["viz", "--nodes", "12", "--seed", "11", "--out", json_out, "--html-out", html_out, "--lookups", "2", "--churn-ticks", "200"])
            self.assertEqual(rc, 0)
            html = Path(html_out).read_text()
            self.assertIn("<title>", html)
            self.assertIn("MERIDIAN_TRACE", html)
            self.assertNotIn("__MERIDIAN_TRACE_JSON__", html)  # placeholder must be substituted
            # the embedded payload must be the same data as the JSON sidecar
            marker = "window.MERIDIAN_TRACE = "
            start = html.index(marker) + len(marker)
            end = html.index(";\n", start)
            embedded = json.loads(html[start:end])
            sidecar = json.loads(Path(json_out).read_text())
            self.assertEqual(embedded, sidecar)

    def test_bucket_refresh_events_are_coalesced_not_one_per_bucket(self):
        """A node's very first maintenance pass can have every non-empty
        bucket due for refresh at once (they all start at
        last_refreshed=0) -- this used to emit one trace event per bucket,
        flooding the replay log. Confirms it's now one event per node per
        maintenance tick, carrying the full list of buckets refreshed."""
        with tempfile.TemporaryDirectory() as td:
            out = str(Path(td) / "trace.json")
            main(["viz", "--nodes", "20", "--seed", "12", "--out", out, "--lookups", "0", "--churn-ticks", "0"])
            payload = json.loads(Path(out).read_text())
            refresh_events = [e for e in payload["events"] if e["kind"] == "bucket_refresh"]
            self.assertTrue(refresh_events)
            for e in refresh_events:
                self.assertIn("buckets", e)
                self.assertIsInstance(e["buckets"], list)
                self.assertGreaterEqual(len(e["buckets"]), 1)


if __name__ == "__main__":
    unittest.main()
