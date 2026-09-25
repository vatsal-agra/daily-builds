import json
import re
import unittest

from casement.inspector import generate_inspector_html


class TestInspector(unittest.TestCase):
    def test_generates_self_contained_html_with_embedded_data(self):
        html = "<html><body><div class='x' style='width:50px;height:30px;background:red'>hi</div></body></html>"
        out = generate_inspector_html(html, viewport_width=300)
        self.assertIn("<html", out)
        self.assertIn("Casement Inspector", out)
        self.assertIn("data:image/png;base64,", out)
        # No leftover template placeholders.
        self.assertNotIn("__PNG_B64__", out)
        self.assertNotIn("__BOXES_JSON__", out)
        self.assertNotIn("__WIDTH__", out)
        self.assertNotIn("__HEIGHT__", out)
        self.assertNotIn("__BOX_COUNT__", out)

    def test_embedded_boxes_json_is_valid_and_matches_dom(self):
        html = "<html><body><div id='a'>a</div><div id='b'>b</div></body></html>"
        out = generate_inspector_html(html, viewport_width=300)
        m = re.search(r'<script id="boxes-data" type="application/json">(.*?)</script>', out, re.DOTALL)
        self.assertIsNotNone(m)
        boxes = json.loads(m.group(1))
        self.assertGreater(len(boxes), 0)
        ids = {b["id"] for b in boxes if b["id"]}
        self.assertEqual(ids, {"a", "b"})
        for b in boxes:
            self.assertIn("dims", b)
            self.assertIn("margin_box", b["dims"])
            self.assertIn("content", b["dims"])

    def test_no_percent_formatting_collision_with_css_or_json(self):
        # The template is filled via string.replace, not %-formatting --
        # CSS values like `-50%` and JSON content must survive untouched.
        html = "<html><body><div style='width:33%'>hi %s not a format spec</div></body></html>"
        out = generate_inspector_html(html, viewport_width=300)
        self.assertIn("translateX(-50%)", out)


if __name__ == "__main__":
    unittest.main()
