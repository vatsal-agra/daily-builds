"""Regression tests for the findings listed in REVIEW.md that are about CLI output."""
import contextlib
import io
import json
import os
import tempfile
import unittest

from argus.cli import main

MODELS = os.path.join(os.path.dirname(__file__), "..", "models")


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


def model(src):
    f = tempfile.NamedTemporaryFile("w", suffix=".arg", delete=False)
    f.write(src)
    f.close()
    return f.name


class CliRegressions(unittest.TestCase):
    def test_07_no_doubled_prefix_and_initial_state_wording(self):
        code, out, _ = run("check", model("var x = 0; proc P() { x = 1 / x; } run P();"))
        self.assertEqual(code, 1)
        self.assertNotIn("runtime error: runtime error", out)
        code, out, _ = run("check", model("var x = 0; proc P() { skip; } run P(); invariant bad: x == 1;"))
        self.assertIn("violated in the initial state", out)

    def test_08_prop_label_lists_only_checked_invariants(self):
        src = "var x = 0; proc P() { skip; } run P(); invariant a: x == 0; invariant b: x == 0;"
        code, out, _ = run("check", model(src), "--prop", "a")
        self.assertIn("runtime errors, a)", out)
        self.assertNotIn(", b)", out)

    def test_09_inconclusive_has_hint_and_exit_code_3(self):
        code, out, _ = run("check", model("var x = 0; proc P() { loop { x = x + 1; } } run P();"),
                           "--max-states", "50")
        self.assertEqual(code, 3)
        self.assertIn("hint:", out)

    def test_10_columns_align_for_long_names(self):
        code, out, _ = run("check", os.path.join(MODELS, "abp.arg"), "--prop", "all_delivered")
        rows = [l for l in out.splitlines() if "DataMedium0" in l and "recv(dtx" in l]
        self.assertTrue(rows)
        # the statement column starts at the same offset on every step row
        starts = {l.index("recv(") if "recv(" in l else l.index("send(") for l in out.splitlines()
                  if l.strip()[:2].rstrip().isdigit() and ("recv(" in l or "send(" in l)}
        self.assertEqual(len(starts), 1, starts)

    def test_11_graph_marks_only_real_deadlocks(self):
        code, out, _ = run("graph", os.path.join(MODELS, "lost_update.arg"), "--max", "6")
        self.assertNotIn("ffd6d6", out)                   # nothing deadlocked in the first 6 states
        self.assertIn("style=dashed", out)
        code, out, _ = run("graph", os.path.join(MODELS, "flag_deadlock.arg"))
        self.assertIn("ffd6d6", out)

    def test_12_sim_save_and_replay_round_trip(self):
        path = tempfile.mktemp(suffix=".json")
        code, out, _ = run("sim", os.path.join(MODELS, "peterson.arg"), "--steps", "12", "--seed", "5",
                           "--save", path)
        self.assertEqual(code, 0)
        code, out, _ = run("replay", os.path.join(MODELS, "peterson.arg"), path)
        self.assertEqual(code, 0)
        self.assertIn("replayed 12 steps", out)
        d = json.load(open(path))
        d["steps"][3]["state"][0] += 1                  # tamper
        json.dump(d, open(path, "w"))
        code, out, _ = run("replay", os.path.join(MODELS, "peterson.arg"), path)
        self.assertEqual(code, 1)
        self.assertIn("NOT valid", out)

    def test_13_deadlock_vs_termination_wording(self):
        code, out, _ = run("check", model("var x = 0; proc P() { await x == 1; } run P(); ltl l: <> (x == 1);"))
        self.assertIn("DEADLOCKED", out)
        code, out, _ = run("check", model("var x = 0; proc P() { x = 0; } run P(); ltl l: <> (x == 1);"))
        self.assertIn("all processes finished", out)

    def test_05_06_clean_errors(self):
        code, out, err = run("check", model("var v[2] = 0; proc P() { skip; } run P(); ltl l: <> (v[3] == 1);"))
        self.assertEqual(code, 2)
        self.assertIn("cannot evaluate", err)
        code, out, err = run("check", model("proc P(a, a) { skip; } run P(1, 2);"))
        self.assertEqual(code, 2)
        self.assertIn("duplicate parameter", err)

    def test_exit_codes_and_json(self):
        code, out, _ = run("check", os.path.join(MODELS, "peterson.arg"))
        self.assertEqual(code, 0)
        code, out, _ = run("check", os.path.join(MODELS, "flag_deadlock.arg"), "--json")
        self.assertEqual(code, 1)
        d = json.loads(out)
        self.assertFalse(d["properties"][0]["ok"])
        code, out, err = run("check", "/nonexistent/file.arg")
        self.assertEqual(code, 2)

    def test_verify_runner(self):
        code, out, _ = run("verify", MODELS)
        self.assertEqual(code, 0, out)
        self.assertIn("expectations met", out)


if __name__ == "__main__":
    unittest.main()
