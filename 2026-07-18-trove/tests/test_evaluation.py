import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from trove.evaluation import (
    precision_at_k, ndcg_at_k, load_judgments, evaluate_query, run_eval, DEFAULT_JUDGMENTS_PATH,
)
from trove.engine import Engine
from trove.index import InvertedIndex


class TestPrecisionAtK(unittest.TestCase):
    def test_all_relevant(self):
        self.assertEqual(precision_at_k(["a", "b", "c"], {"a", "b", "c"}, 3), 1.0)

    def test_none_relevant(self):
        self.assertEqual(precision_at_k(["a", "b", "c"], {"x", "y"}, 3), 0.0)

    def test_partial(self):
        self.assertAlmostEqual(precision_at_k(["a", "x", "b", "y"], {"a", "b"}, 4), 0.5)

    def test_empty_retrieved(self):
        self.assertEqual(precision_at_k([], {"a"}, 5), 0.0)

    def test_k_smaller_than_retrieved_list(self):
        self.assertEqual(precision_at_k(["a", "x", "x"], {"a"}, 1), 1.0)


class TestNDCGAtK(unittest.TestCase):
    def test_perfect_ranking_scores_one(self):
        self.assertAlmostEqual(ndcg_at_k(["a", "b"], {"a", "b"}, 2), 1.0)

    def test_no_relevant_docs_at_all_scores_zero(self):
        self.assertEqual(ndcg_at_k(["a", "b"], set(), 2), 0.0)

    def test_worse_ranking_scores_lower_than_perfect(self):
        # relevant = {a, b}; putting the irrelevant doc first is worse
        # than putting a relevant one first.
        good = ndcg_at_k(["a", "b", "x"], {"a", "b"}, 3)
        bad = ndcg_at_k(["x", "a", "b"], {"a", "b"}, 3)
        self.assertGreater(good, bad)
        self.assertAlmostEqual(good, 1.0)

    def test_empty_retrieved_scores_zero(self):
        self.assertEqual(ndcg_at_k([], {"a"}, 5), 0.0)


class TestJudgmentsAndEvalLoop(unittest.TestCase):
    def build_fixture_engine(self):
        idx = InvertedIndex()
        idx.add_document("cdcl-a", "CDCL SAT solver with clause learning and backjumping")
        idx.add_document("cdcl-b", "another conflict driven clause learning solver")
        idx.add_document("chess", "a chess engine with alpha beta search")
        idx.finalize()
        return Engine(idx)

    def test_default_judgments_file_loads_and_is_nonempty(self):
        judgments = load_judgments()
        self.assertGreater(len(judgments), 5)
        for query, relevant in judgments.items():
            self.assertIsInstance(query, str)
            self.assertGreater(len(relevant), 0)

    def test_default_judgments_path_exists(self):
        self.assertTrue(os.path.exists(DEFAULT_JUDGMENTS_PATH))

    def test_custom_judgments_file_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "judgments.json")
            with open(path, "w") as f:
                json.dump({"cdcl solver": ["cdcl-a", "cdcl-b"]}, f)
            judgments = load_judgments(path)
        self.assertEqual(judgments, {"cdcl solver": {"cdcl-a", "cdcl-b"}})

    def test_evaluate_query_returns_expected_shape(self):
        engine = self.build_fixture_engine()
        row = evaluate_query(engine, "CDCL clause learning", {"cdcl-a", "cdcl-b"}, k=5)
        self.assertIn("precision_at_k", row)
        self.assertIn("ndcg_at_k", row)
        self.assertGreater(row["precision_at_k"], 0.0)

    def test_run_eval_handles_zero_result_query_without_crashing(self):
        # Regression check for an operator-precedence bug: an f-string +
        # conditional-expression combo silently dropped the row's
        # query/score columns whenever retrieved was empty.
        engine = self.build_fixture_engine()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "judgments.json")
            with open(path, "w") as f:
                json.dump({"nothing matches this at all": ["cdcl-a"]}, f)
            lines = []
            code = run_eval(engine, path, k=5, out=lines.append)
        self.assertEqual(code, 0)
        data_line = next(l for l in lines if "nothing matches this at all" in l)
        self.assertIn("0.00", data_line)
        self.assertIn("(none)", data_line)

    def test_run_eval_against_bundled_repo_history_judgments_if_index_matches(self):
        # Build the real repo-history index and run the bundled hand
        # judgments end-to-end. This is a genuine ranking-quality
        # regression check, not just a crash test: BM25 over this real
        # corpus is measured to reach mean P@5 ~0.86 / NDCG@5 ~0.96 (a
        # handful of legitimate near-misses — e.g. two same-named
        # "Strata" projects sharing enough vocabulary to rank each other
        # nearby). If a future change tanks that, this test catches it.
        from trove.corpora import build_repo_history_index
        repo_root = os.path.join(os.path.dirname(__file__), "..", "..")
        idx = build_repo_history_index(repo_root)
        engine = Engine(idx)
        judgments = load_judgments()  # bundled default_judgments.json
        rows = [evaluate_query(engine, q, rel, k=5) for q, rel in judgments.items()]
        mean_p = sum(r["precision_at_k"] for r in rows) / len(rows)
        mean_ndcg = sum(r["ndcg_at_k"] for r in rows) / len(rows)
        self.assertGreater(mean_p, 0.7, msg=f"ranking quality regressed: mean P@5={mean_p:.2f}")
        self.assertGreater(mean_ndcg, 0.85, msg=f"ranking quality regressed: mean NDCG@5={mean_ndcg:.2f}")

        lines = []
        code = run_eval(engine, None, k=5, out=lines.append)
        self.assertEqual(code, 0)
        mean_line = next(l for l in lines if l.startswith("MEAN"))
        self.assertIn("queries)", mean_line)


if __name__ == "__main__":
    unittest.main()
