import os
import tempfile
import unittest

from casement.cli import main


class TestCLIErrorHandling(unittest.TestCase):
    def test_missing_input_file_is_a_clean_error_not_a_traceback(self):
        code = main(["render", "/nonexistent/path/does-not-exist.html", "-o", os.devnull])
        self.assertEqual(code, 1)

    def test_zero_width_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            html_path = os.path.join(d, "a.html")
            with open(html_path, "w") as f:
                f.write("<p>hi</p>")
            code = main(["render", html_path, "--width", "0", "-o", os.path.join(d, "o.png")])
            self.assertEqual(code, 1)

    def test_negative_width_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            html_path = os.path.join(d, "a.html")
            with open(html_path, "w") as f:
                f.write("<p>hi</p>")
            code = main(["render", html_path, "--width", "-10", "-o", os.path.join(d, "o.png")])
            self.assertEqual(code, 1)

    def test_successful_render_writes_png(self):
        with tempfile.TemporaryDirectory() as d:
            html_path = os.path.join(d, "a.html")
            out_path = os.path.join(d, "o.png")
            with open(html_path, "w") as f:
                f.write("<p>hi</p>")
            code = main(["render", html_path, "-o", out_path, "--width", "300"])
            self.assertEqual(code, 0)
            self.assertTrue(os.path.exists(out_path))
            self.assertGreater(os.path.getsize(out_path), 0)


if __name__ == "__main__":
    unittest.main()
