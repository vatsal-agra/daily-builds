import io
import os
import subprocess
import sys
import tempfile
import unittest

from sift.index import InvertedIndex, build_index_from_dir
from sift.engine import Engine
from sift.storage import save_index

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS_DIR = os.path.join(PROJECT_ROOT, "corpus")


class TestEngine(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        path_a = os.path.join(self.tmpdir.name, "a.txt")
        path_b = os.path.join(self.tmpdir.name, "b.txt")
        with open(path_a, "w") as fh:
            fh.write("the quick brown fox jumps over the lazy dog")
        with open(path_b, "w") as fh:
            fh.write("a quick fox is not a lazy dog it runs fast")

        self.index = InvertedIndex()
        self.index.add_document(path_a, "Doc A", "the quick brown fox jumps over the lazy dog")
        self.index.add_document(path_b, "Doc B", "a quick fox is not a lazy dog it runs fast")
        self.engine = Engine(self.index)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_search_returns_ranked_results(self):
        results = self.engine.search("fox")
        self.assertEqual(len(results), 2)
        self.assertTrue(all(isinstance(r, tuple) for r in results))

    def test_search_limit_applied(self):
        results = self.engine.search("fox", limit=1)
        self.assertEqual(len(results), 1)

    def test_suggest_finds_close_vocabulary(self):
        hits = self.engine.suggest("qwick")
        words = [w for w, _ in hits]
        self.assertIn("quick", words)

    def test_suggest_empty_vocab_no_crash(self):
        empty_engine = Engine(InvertedIndex())
        self.assertEqual(empty_engine.suggest("anything"), [])

    def test_snippet_for_returns_highlighted_html(self):
        results = self.engine.search("fox")
        doc_id = results[0][0]
        snippet = self.engine.snippet_for(doc_id, "fox")
        self.assertIn("<mark>", snippet)

    def test_snippet_for_does_not_repeat_the_title(self):
        # regression test: the title is already shown as the card heading,
        # so it should not also appear inline at the top of the snippet.
        path = os.path.join(self.tmpdir.name, "titled.txt")
        with open(path, "w") as fh:
            fh.write("A Distinctive Title About Foxes\n\nThe fox ran through the forest quickly.")
        with open(path) as fh:
            text = fh.read()
        index = InvertedIndex()
        index.add_document(path, "A Distinctive Title About Foxes", text)
        engine = Engine(index)
        snippet = engine.snippet_for(0, "fox")
        self.assertNotIn("Distinctive Title", snippet)

    def test_snippet_for_bad_query_returns_empty_not_crash(self):
        results = self.engine.search("fox")
        doc_id = results[0][0]
        snippet = self.engine.snippet_for(doc_id, "fox AND (")
        self.assertEqual(snippet, "")


class TestFullCorpusEndToEnd(unittest.TestCase):
    """Builds the real bundled corpus and checks the whole engine works
    against real, meaningfully-sized data (not a toy 2-document fixture)."""

    @classmethod
    def setUpClass(cls):
        cls.index = build_index_from_dir(CORPUS_DIR)
        cls.engine = Engine(cls.index)

    def test_corpus_has_expected_size(self):
        self.assertEqual(self.index.doc_count, 40)

    def test_topical_query_surfaces_right_topic(self):
        results = self.engine.search("python readability whitespace", limit=3)
        titles = [self.index.documents[d].title for d, _ in results]
        self.assertTrue(any("Python" in t for t in titles))

    def test_phrase_query_on_real_corpus(self):
        results = self.engine.search('"black hole"')
        self.assertTrue(len(results) >= 1)
        top_title = self.index.documents[results[0][0]].title
        self.assertIn("Black Holes", top_title)

    def test_boolean_not_excludes_docs(self):
        with_mars = {d for d, _ in self.engine.search("mars", limit=40)}
        without_rover = {d for d, _ in self.engine.search("mars NOT rover", limit=40)}
        self.assertTrue(without_rover.issubset(with_mars))
        excluded_titles = [self.index.documents[d].title for d in (with_mars - without_rover)]
        self.assertTrue(any("Mars Rovers" in t for t in excluded_titles))

    def test_nonsense_query_returns_no_results_and_offers_suggestion(self):
        results = self.engine.search("quantumm")  # typo for quantum
        self.assertEqual(results, [])
        hits = self.engine.suggest("quantumm")
        self.assertTrue(any(w.startswith("quantum") for w, _ in hits))


class TestCLISmoke(unittest.TestCase):
    """Runs the actual CLI as a subprocess end-to-end."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.index_path = os.path.join(self.tmpdir.name, "cli_test.sift")

    def tearDown(self):
        self.tmpdir.cleanup()

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "sift.cli", *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_index_command(self):
        result = self._run("index", CORPUS_DIR, "-o", self.index_path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("indexed 40 documents", result.stdout)
        self.assertTrue(os.path.exists(self.index_path))

    def test_search_command_after_index(self):
        self._run("index", CORPUS_DIR, "-o", self.index_path)
        result = self._run("search", "mars rover", "-i", self.index_path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Mars Rovers", result.stdout)

    def test_search_missing_index_fails_cleanly(self):
        result = self._run("search", "fox", "-i", "/nonexistent/path.sift")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not found", result.stderr)

    def test_search_no_results_offers_suggestion(self):
        self._run("index", CORPUS_DIR, "-o", self.index_path)
        result = self._run("search", "quantumm", "-i", self.index_path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("did you mean", result.stdout.lower())

    def test_bad_query_syntax_fails_cleanly(self):
        self._run("index", CORPUS_DIR, "-o", self.index_path)
        result = self._run("search", "fox AND (", "-i", self.index_path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("query error", result.stderr.lower())

    def test_suggestions_not_polluted_by_operator_keywords(self):
        # regression test for REVIEW.md #3: "AND"/"OR"/"NOT" used to leak
        # into the "did you mean" suggestion list.
        self._run("index", CORPUS_DIR, "-o", self.index_path)
        result = self._run("search", "quantumm AND nonexistentxyz", "-i", self.index_path)
        self.assertEqual(result.returncode, 0, result.stderr)
        suggestion_line = next(
            (l for l in result.stdout.splitlines() if "did you mean" in l.lower()), ""
        )
        self.assertIn("quantum", suggestion_line)
        for banned in ("ad,", "add,", "hand,", "land,"):
            self.assertNotIn(banned, suggestion_line)

    def test_index_empty_directory_fails_cleanly(self):
        empty_dir = tempfile.mkdtemp()
        result = self._run("index", empty_dir, "-o", self.index_path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no .txt", result.stderr)

    def test_demo_command_runs_clean(self):
        result = self._run("demo")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("search: python", result.stdout)

    def test_negative_k1_rejected(self):
        self._run("index", CORPUS_DIR, "-o", self.index_path)
        result = self._run("search", "fox", "-i", self.index_path, "--k1", "-1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--k1", result.stderr)

    def test_out_of_range_b_rejected(self):
        self._run("index", CORPUS_DIR, "-o", self.index_path)
        result = self._run("search", "fox", "-i", self.index_path, "--b", "1.5")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--b", result.stderr)

    def test_zero_limit_rejected(self):
        self._run("index", CORPUS_DIR, "-o", self.index_path)
        result = self._run("search", "fox", "-i", self.index_path, "-k", "0")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--limit", result.stderr)

    def test_index_nonexistent_directory_fails_cleanly(self):
        result = self._run("index", "/no/such/directory", "-o", self.index_path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not a directory", result.stderr)


if __name__ == "__main__":
    unittest.main()
