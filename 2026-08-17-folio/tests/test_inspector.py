import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from folio import inspector


def _write(text, suffix=".html"):
    f = tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False)
    f.write(text)
    f.close()
    return f.name


class TestInspector(unittest.TestCase):
    def test_builds_self_contained_html_with_hit_rects(self):
        html_path = _write(
            "<html><body><div style='width:100px;height:50px;background:red'>x</div></body></html>"
        )
        out_path = html_path + ".out.html"
        try:
            inspector.build(html_path, [], 400, out_path, use_oracle=False)
            self.assertTrue(os.path.exists(out_path))
            with open(out_path) as f:
                content = f.read()
            self.assertIn("folio-hit", content)
            self.assertIn("<svg", content)
            self.assertIn("BOXES = ", content)
            self.assertIn("<!doctype html>", content.lower())
        finally:
            os.unlink(html_path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_no_data_t_shows_hint_not_a_crash(self):
        html_path = _write("<html><body><p>no data-t here</p></body></html>")
        out_path = html_path + ".out.html"
        try:
            inspector.build(html_path, [], 400, out_path, use_oracle=False)
            with open(out_path) as f:
                content = f.read()
            self.assertIn("Click any element", content)
        finally:
            os.unlink(html_path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_empty_document_raises_clean_error(self):
        html_path = _write("")
        out_path = html_path + ".out.html"
        try:
            with self.assertRaises(ValueError):
                inspector.build(html_path, [], 400, out_path, use_oracle=False)
        finally:
            os.unlink(html_path)

    def test_box_ids_are_unique_and_json_serializable(self):
        import json

        html_path = _write(
            "<html><body><div><p>a</p><p>b</p></div></body></html>"
        )
        out_path = html_path + ".out.html"
        try:
            inspector.build(html_path, [], 400, out_path, use_oracle=False)
            with open(out_path) as f:
                content = f.read()
            start = content.index("const BOXES = ") + len("const BOXES = ")
            end = content.index(";\n", start)
            boxes = json.loads(content[start:end])
            self.assertGreater(len(boxes), 0)
            ids = [b["id"] for b in boxes.values()]
            self.assertEqual(len(ids), len(set(ids)))
        finally:
            os.unlink(html_path)
            if os.path.exists(out_path):
                os.unlink(out_path)


if __name__ == "__main__":
    unittest.main()
