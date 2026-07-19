import unittest
import tempfile
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from loom.attn_viz import render


class TestAttnViz(unittest.TestCase):
    def test_render_produces_valid_looking_html(self):
        frames = [{"tokens": ["a", "b"], "layers": [[[[0.9, 0.1], [0.2, 0.8]]]]}]
        with tempfile.TemporaryDirectory() as d:
            out_path = os.path.join(d, "attn.html")
            render(frames, "ab", out_path)
            with open(out_path) as f:
                html = f.read()
        self.assertIn("<html", html)
        self.assertIn("Loom", html)
        self.assertNotIn("__LOOM_DATA__", html)

    def test_render_creates_missing_directories(self):
        frames = [{"tokens": ["a"], "layers": [[[[1.0]]]]}]
        with tempfile.TemporaryDirectory() as d:
            out_path = os.path.join(d, "nested", "sub", "attn.html")
            render(frames, "a", out_path)
            self.assertTrue(os.path.exists(out_path))

    def test_render_escapes_closing_script_tag_in_generated_text(self):
        """A generated string containing </script> must not be able to break
        out of the embedding <script> block into the surrounding page."""
        frames = [{"tokens": ["<", "/", "s"], "layers": [[[[1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]]]]}]
        malicious_text = "</script><img src=x onerror=alert(1)>"
        with tempfile.TemporaryDirectory() as d:
            out_path = os.path.join(d, "attn.html")
            render(frames, malicious_text, out_path)
            with open(out_path) as f:
                html = f.read()
        self.assertNotIn("</script><img", html)
        # the raw payload must still round-trip correctly for the JS to read
        self.assertIn("img src=x onerror=alert(1)", html)


if __name__ == "__main__":
    unittest.main()
