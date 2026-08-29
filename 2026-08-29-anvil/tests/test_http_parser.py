import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anvil.http_parser import ParseError, RequestParser  # noqa: E402


class TestRequestLine(unittest.TestCase):
    def test_simple_get(self):
        p = RequestParser()
        reqs = p.feed(b"GET /hello?x=1 HTTP/1.1\r\nHost: a\r\n\r\n")
        self.assertEqual(len(reqs), 1)
        r = reqs[0]
        self.assertEqual(r.method, "GET")
        self.assertEqual(r.path, "/hello")
        self.assertEqual(r.query, {"x": ["1"]})
        self.assertEqual(r.header("Host"), "a")
        self.assertEqual(r.body, b"")

    def test_percent_decoded_path(self):
        p = RequestParser()
        reqs = p.feed(b"GET /a%20b/%2e%2e HTTP/1.1\r\nHost: a\r\n\r\n")
        self.assertEqual(reqs[0].path, "/a b/..")

    def test_rejects_bad_version(self):
        p = RequestParser()
        with self.assertRaises(ParseError):
            p.feed(b"GET / HTTP/2.0\r\nHost: a\r\n\r\n")

    def test_rejects_malformed_line(self):
        p = RequestParser()
        with self.assertRaises(ParseError):
            p.feed(b"GET /\r\nHost: a\r\n\r\n")

    def test_leading_blank_lines_ignored(self):
        p = RequestParser()
        reqs = p.feed(b"\r\n\r\nGET / HTTP/1.1\r\nHost: a\r\n\r\n")
        self.assertEqual(len(reqs), 1)


class TestSplitFeeds(unittest.TestCase):
    def test_split_mid_header(self):
        p = RequestParser()
        raw = b"GET / HTTP/1.1\r\nHost: exam"
        rest = b"ple.com\r\n\r\n"
        self.assertEqual(p.feed(raw), [])
        reqs = p.feed(rest)
        self.assertEqual(len(reqs), 1)
        self.assertEqual(reqs[0].header("Host"), "example.com")

    def test_split_byte_by_byte(self):
        p = RequestParser()
        raw = b"GET / HTTP/1.1\r\nHost: a\r\nContent-Length: 5\r\n\r\nhello"
        reqs = []
        for i in range(len(raw)):
            reqs.extend(p.feed(raw[i:i + 1]))
        self.assertEqual(len(reqs), 1)
        self.assertEqual(reqs[0].body, b"hello")

    def test_split_mid_body(self):
        p = RequestParser()
        head = b"POST / HTTP/1.1\r\nHost: a\r\nContent-Length: 10\r\n\r\n"
        self.assertEqual(p.feed(head + b"12345"), [])
        reqs = p.feed(b"67890")
        self.assertEqual(reqs[0].body, b"1234567890")


class TestPipelining(unittest.TestCase):
    def test_two_requests_one_feed(self):
        p = RequestParser()
        raw = (
            b"GET /a HTTP/1.1\r\nHost: h\r\n\r\n"
            b"GET /b HTTP/1.1\r\nHost: h\r\n\r\n"
        )
        reqs = p.feed(raw)
        self.assertEqual([r.path for r in reqs], ["/a", "/b"])

    def test_request_plus_partial_next(self):
        p = RequestParser()
        raw = b"GET /a HTTP/1.1\r\nHost: h\r\n\r\nGET /b HTTP/1.1\r\nHost: h\r\n"
        reqs = p.feed(raw)
        self.assertEqual([r.path for r in reqs], ["/a"])
        reqs2 = p.feed(b"\r\n")
        self.assertEqual([r.path for r in reqs2], ["/b"])


class TestContentLength(unittest.TestCase):
    def test_exact_body(self):
        p = RequestParser()
        raw = b"POST / HTTP/1.1\r\nHost: h\r\nContent-Length: 3\r\n\r\nabc"
        reqs = p.feed(raw)
        self.assertEqual(reqs[0].body, b"abc")

    def test_zero_length_body(self):
        p = RequestParser()
        raw = b"POST / HTTP/1.1\r\nHost: h\r\nContent-Length: 0\r\n\r\n"
        reqs = p.feed(raw)
        self.assertEqual(reqs[0].body, b"")

    def test_negative_length_rejected(self):
        p = RequestParser()
        with self.assertRaises(ParseError):
            p.feed(b"POST / HTTP/1.1\r\nHost: h\r\nContent-Length: -1\r\n\r\n")

    def test_conflicting_lengths_rejected(self):
        p = RequestParser()
        with self.assertRaises(ParseError):
            p.feed(
                b"POST / HTTP/1.1\r\nHost: h\r\n"
                b"Content-Length: 3\r\nContent-Length: 4\r\n\r\nabc"
            )

    def test_body_too_large_rejected(self):
        p = RequestParser(max_body_bytes=10)
        with self.assertRaises(ParseError):
            p.feed(b"POST / HTTP/1.1\r\nHost: h\r\nContent-Length: 1000\r\n\r\n")

    def test_layered_transfer_encoding_rejected(self):
        # gzip-then-chunked would decode the chunk *framing* correctly
        # while handing the caller still-gzipped bytes as if they were the
        # real body -- regression test for a Phase 3 review finding.
        p = RequestParser()
        with self.assertRaises(ParseError):
            p.feed(
                b"POST / HTTP/1.1\r\nHost: h\r\nTransfer-Encoding: gzip, chunked\r\n\r\n"
                b"3\r\nabc\r\n0\r\n\r\n"
            )

    def test_smuggling_both_headers_rejected(self):
        p = RequestParser()
        with self.assertRaises(ParseError):
            p.feed(
                b"POST / HTTP/1.1\r\nHost: h\r\nContent-Length: 3\r\n"
                b"Transfer-Encoding: chunked\r\n\r\n3\r\nabc\r\n0\r\n\r\n"
            )


class TestChunked(unittest.TestCase):
    def test_basic_chunked(self):
        p = RequestParser()
        raw = (
            b"POST / HTTP/1.1\r\nHost: h\r\nTransfer-Encoding: chunked\r\n\r\n"
            b"5\r\nhello\r\n6\r\n world\r\n0\r\n\r\n"
        )
        reqs = p.feed(raw)
        self.assertEqual(reqs[0].body, b"hello world")

    def test_chunked_with_trailer(self):
        p = RequestParser()
        raw = (
            b"POST / HTTP/1.1\r\nHost: h\r\nTransfer-Encoding: chunked\r\n\r\n"
            b"3\r\nabc\r\n0\r\nX-Trailer: yes\r\n\r\n"
        )
        reqs = p.feed(raw)
        self.assertEqual(reqs[0].body, b"abc")
        self.assertEqual(reqs[0].trailers.get("X-Trailer"), "yes")

    def test_chunked_split_mid_size_line(self):
        p = RequestParser()
        head = b"POST / HTTP/1.1\r\nHost: h\r\nTransfer-Encoding: chunked\r\n\r\n"
        self.assertEqual(p.feed(head + b"5\r\nhel"), [])
        reqs = p.feed(b"lo\r\n0\r\n\r\n")
        self.assertEqual(reqs[0].body, b"hello")

    def test_chunked_bad_terminator_rejected(self):
        p = RequestParser()
        raw = (
            b"POST / HTTP/1.1\r\nHost: h\r\nTransfer-Encoding: chunked\r\n\r\n"
            b"3\r\nabcXX0\r\n\r\n"
        )
        with self.assertRaises(ParseError):
            p.feed(raw)

    def test_chunked_bad_size_rejected(self):
        p = RequestParser()
        raw = (
            b"POST / HTTP/1.1\r\nHost: h\r\nTransfer-Encoding: chunked\r\n\r\n"
            b"zz\r\n\r\n"
        )
        with self.assertRaises(ParseError):
            p.feed(raw)


class TestHeaderEdgeCases(unittest.TestCase):
    def test_obsolete_folding_rejected(self):
        p = RequestParser()
        raw = b"GET / HTTP/1.1\r\nHost: h\r\nX-Foo: a\r\n b\r\n\r\n"
        with self.assertRaises(ParseError):
            p.feed(raw)

    def test_missing_colon_rejected(self):
        p = RequestParser()
        with self.assertRaises(ParseError):
            p.feed(b"GET / HTTP/1.1\r\nHost h\r\n\r\n")

    def test_huge_header_line_rejected(self):
        p = RequestParser()
        raw = b"GET / HTTP/1.1\r\nX-Big: " + b"a" * 100_000 + b"\r\n\r\n"
        with self.assertRaises(ParseError):
            p.feed(raw)

    def test_case_insensitive_headers(self):
        p = RequestParser()
        reqs = p.feed(b"GET / HTTP/1.1\r\nhOsT: example\r\n\r\n")
        self.assertEqual(reqs[0].header("HOST"), "example")


class TestExpectContinue(unittest.TestCase):
    def test_callback_fires_before_body_arrives(self):
        fired = []
        p = RequestParser(on_expect_continue=lambda: fired.append(True))
        head = (
            b"POST / HTTP/1.1\r\nHost: h\r\nExpect: 100-continue\r\n"
            b"Content-Length: 5\r\n\r\n"
        )
        reqs = p.feed(head)
        self.assertEqual(reqs, [])
        self.assertEqual(fired, [True])  # fired even though body hasn't arrived yet
        reqs = p.feed(b"hello")
        self.assertEqual(reqs[0].body, b"hello")

    def test_no_callback_without_expect_header(self):
        fired = []
        p = RequestParser(on_expect_continue=lambda: fired.append(True))
        p.feed(b"GET / HTTP/1.1\r\nHost: h\r\n\r\n")
        self.assertEqual(fired, [])


if __name__ == "__main__":
    unittest.main()
