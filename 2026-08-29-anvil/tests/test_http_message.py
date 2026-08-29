import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anvil.http_message import HeaderDict, Response  # noqa: E402


class TestHeaderInjectionGuard(unittest.TestCase):
    """Regression tests for a Phase 3 review finding: a handler that
    interpolates untrusted input into a header value (e.g. a redirect
    Location built from a query parameter) must not be able to smuggle a
    literal CRLF and inject extra headers or a second response."""

    def test_set_rejects_crlf_in_value(self):
        h = HeaderDict()
        with self.assertRaises(ValueError):
            h.set("Location", "/ok\r\nSet-Cookie: evil=1")

    def test_add_rejects_crlf_in_value(self):
        h = HeaderDict()
        with self.assertRaises(ValueError):
            h.add("X-Custom", "line1\nline2")

    def test_constructor_rejects_crlf(self):
        with self.assertRaises(ValueError):
            HeaderDict([("Location", "/a\r\nX-Injected: yes")])

    def test_response_construction_rejects_crlf(self):
        with self.assertRaises(ValueError):
            Response(302, headers=[("Location", "/x\r\n\r\n<script>evil</script>")])

    def test_ordinary_values_still_work(self):
        h = HeaderDict()
        h.set("Content-Type", "text/plain; charset=utf-8")
        self.assertEqual(h.get("Content-Type"), "text/plain; charset=utf-8")


if __name__ == "__main__":
    unittest.main()
