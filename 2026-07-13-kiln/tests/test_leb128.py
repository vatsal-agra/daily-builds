import unittest

from .helpers import ROOT  # noqa: F401  (sets sys.path)
from kiln.wasm.leb128 import encode_uleb, encode_sleb, ByteReader


class TestLeb128(unittest.TestCase):
    def test_uleb_known_values(self):
        # Values from the WASM spec's own LEB128 appendix.
        self.assertEqual(encode_uleb(0), b"\x00")
        self.assertEqual(encode_uleb(624485), b"\xe5\x8e\x26")
        self.assertEqual(encode_uleb(127), b"\x7f")
        self.assertEqual(encode_uleb(128), b"\x80\x01")

    def test_sleb_known_values(self):
        self.assertEqual(encode_sleb(0), b"\x00")
        self.assertEqual(encode_sleb(-1), b"\x7f")
        self.assertEqual(encode_sleb(-624485), b"\x9b\xf1\x59")
        self.assertEqual(encode_sleb(127), b"\xff\x00")
        self.assertEqual(encode_sleb(-128), b"\x80\x7f")

    def test_uleb_roundtrip(self):
        for v in [0, 1, 127, 128, 300, 65535, 65536, 2**32 - 1, 2**64 - 1]:
            r = ByteReader(encode_uleb(v))
            self.assertEqual(r.read_uleb(64), v)

    def test_sleb_roundtrip(self):
        for v in [0, -1, 1, -128, 127, -70000, 70000, -(2**33), 2**33]:
            r = ByteReader(encode_sleb(v))
            self.assertEqual(r.read_sleb(64), v)

    def test_uleb_read_eof(self):
        r = ByteReader(b"\x80\x80")  # continuation bit set, no terminator
        with self.assertRaises(EOFError):
            r.read_uleb(32)


if __name__ == "__main__":
    unittest.main()
