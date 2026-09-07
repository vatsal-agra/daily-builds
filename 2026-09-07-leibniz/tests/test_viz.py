import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from leibniz.diff import diff
from leibniz.parser import parse
from leibniz.render import Steps
from viz.generate_viz import build_html


class TestBuildHtml(unittest.TestCase):
    def _steps(self):
        e = parse("x^2*sin(x)")
        steps = Steps()
        steps.add("d/dx", diff(e, "x", steps=None))
        return steps

    def test_produces_valid_html_with_embedded_json(self):
        html = build_html(op="differentiate", expr_text="x^2*sin(x)", var="x", steps=self._steps().to_json())
        self.assertIn("<title>", html)
        self.assertIn("<svg", html)
        start = html.index("const STEPS = ") + len("const STEPS = ")
        end = html.index(";\n", start)
        data = json.loads(html[start:end])
        self.assertEqual(len(data), 1)
        self.assertIn("tree", data[0])

    def test_escapes_expression_text(self):
        html = build_html(op="simplify", expr_text="x < 3 & y > 1", var="x", steps=self._steps().to_json())
        self.assertNotIn("x < 3 & y > 1", html)  # the raw, unescaped form
        self.assertIn("&lt;", html)

    def test_rejects_empty_steps(self):
        with self.assertRaises(ValueError):
            build_html(op="diff", expr_text="x", var="x", steps=[])


if __name__ == "__main__":
    unittest.main()
