import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from unify.web.server import run_inference, serialize_judgment, EXAMPLES
from unify.parser import parse
from unify.infer import infer_program


class TestRunInference(unittest.TestCase):
    def test_success_shape(self):
        result = run_inference("1 + 2")
        self.assertTrue(result["ok"])
        self.assertEqual(result["type"], "int")
        self.assertEqual(result["value"], "3")
        self.assertIn("label", result["derivation"])

    def test_parse_error_shape(self):
        result = run_inference("let x = in x")
        self.assertFalse(result["ok"])
        self.assertIn("error", result)
        self.assertIn("error:", result["error"])

    def test_type_error_shape(self):
        result = run_inference("1 + true")
        self.assertFalse(result["ok"])
        self.assertIn("expected int, found bool", result["error"])

    def test_eval_error_reported_separately_from_type_error(self):
        result = run_inference("1 / 0")
        self.assertTrue(result["ok"])  # type-checks fine
        self.assertEqual(result["type"], "int")
        self.assertNotIn("value", result)
        self.assertIn("division by zero", result["eval_error"])

    def test_derivation_matches_a_real_judgment_tree(self):
        expr = parse("1 + 2")
        _ty, judgment, _counter = infer_program(expr)
        expected = serialize_judgment(judgment)
        result = run_inference("1 + 2")
        self.assertEqual(result["derivation"], expected)

    def test_all_examples_run_without_crashing(self):
        for ex in EXAMPLES:
            result = run_inference(ex["source"])
            self.assertIn("ok", result, ex["name"])


class TestSerializeJudgment(unittest.TestCase):
    def test_serializes_nested_children(self):
        expr = parse("(1, true)")
        _ty, judgment, _counter = infer_program(expr)
        data = serialize_judgment(judgment)
        self.assertEqual(data["label"], "Tuple")
        self.assertEqual(len(data["children"]), 2)
        self.assertEqual(data["children"][0]["type"], "int")
        self.assertEqual(data["children"][1]["type"], "bool")


if __name__ == "__main__":
    unittest.main()
