import itertools
import unittest

from glean.index import InvertedIndex
from glean.query import QuerySyntaxError, parse
from corpus.demo_corpus import load_corpus


def _oracle_eval(node, index, doc_id):
    """Brute-force re-evaluation of a parsed query AST directly against a
    document's token stream — independent of the postings-based match()."""
    tokens = index.documents[doc_id].tokens
    kind = type(node).__name__

    if kind == "TermNode":
        return node.stem in tokens
    if kind == "PhraseNode":
        stems = node.stems
        n = len(stems)
        if n == 0:
            return False
        return any(tokens[i : i + n] == stems for i in range(len(tokens) - n + 1))
    if kind == "NearNode":
        left_terms = set(node.left.terms())
        right_terms = set(node.right.terms())
        pos_left = [i for i, t in enumerate(tokens) if t in left_terms]
        pos_right = [i for i, t in enumerate(tokens) if t in right_terms]
        if not pos_left or not pos_right:
            return False
        return min(abs(a - b) for a in pos_left for b in pos_right) <= node.k
    if kind == "AndNode":
        return _oracle_eval(node.left, index, doc_id) and _oracle_eval(node.right, index, doc_id)
    if kind == "OrNode":
        return _oracle_eval(node.left, index, doc_id) or _oracle_eval(node.right, index, doc_id)
    if kind == "NotNode":
        return not _oracle_eval(node.node, index, doc_id)
    raise AssertionError(f"unhandled node kind: {kind}")


class DifferentialQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = InvertedIndex()
        for article in load_corpus():
            cls.index.add_document(article["title"], article["text"], path=article["topic"])

    def _check(self, query_string):
        ast = parse(query_string)
        actual = ast.match(self.index)
        expected = {doc_id for doc_id in self.index.documents if _oracle_eval(ast, self.index, doc_id)}
        self.assertEqual(actual, expected, f"mismatch for query: {query_string!r}")

    def test_battery(self):
        queries = [
            "photosynthesis",
            "roman AND empire",
            "roman OR chess",
            "roman empire",  # implicit OR
            "football NOT basketball",
            "NOT basketball",
            '"printing press"',
            '"the great wall"',
            "chess AND notation",
            "chess OR notation AND rules",
            "(chess OR tennis) AND rules",
            "onion NEAR/3 cry",
            "onion NEAR/1 cry",
            "cooking AND (pasta OR bread)",
            "history NOT (war OR revolution)",
            "nonexistentwordxyz",
            '"nonexistent phrase entirely"',
        ]
        for q in queries:
            with self.subTest(query=q):
                self._check(q)

    def test_battery_generated_term_pairs(self):
        # Cross every pair from a sample of real vocabulary terms through
        # AND/OR/NOT/NEAR and verify against the brute-force oracle.
        sample_terms = ["water", "energi", "trade", "food", "game", "team", "cell", "wave"]
        connectors = ["AND", "OR", "NOT"]
        for a, b in itertools.combinations(sample_terms, 2):
            for conn in connectors:
                q = f"{a} {conn} {b}"
                with self.subTest(query=q):
                    self._check(q)
            with self.subTest(query=f"{a} NEAR/5 {b}"):
                self._check(f"{a} NEAR/5 {b}")


class ParserErrorTests(unittest.TestCase):
    def test_empty_query(self):
        with self.assertRaises(QuerySyntaxError):
            parse("")

    def test_whitespace_only_query(self):
        with self.assertRaises(QuerySyntaxError):
            parse("   ")

    def test_unbalanced_open_paren(self):
        with self.assertRaises(QuerySyntaxError):
            parse("(cat AND dog")

    def test_unbalanced_close_paren(self):
        with self.assertRaises(QuerySyntaxError):
            parse("cat AND dog)")

    def test_empty_phrase(self):
        with self.assertRaises(QuerySyntaxError):
            parse('""')

    def test_dangling_near(self):
        with self.assertRaises(QuerySyntaxError):
            parse("cat NEAR/3")

    def test_dangling_and(self):
        with self.assertRaises(QuerySyntaxError):
            parse("cat AND")

    def test_leading_and(self):
        with self.assertRaises(QuerySyntaxError):
            parse("AND cat")

    def test_leading_near_is_a_syntax_error(self):
        # NEAR/3 with no left-hand term is not a valid primary.
        with self.assertRaises(QuerySyntaxError):
            parse("NEAR/3")


if __name__ == "__main__":
    unittest.main()
