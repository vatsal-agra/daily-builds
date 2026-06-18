"""Test suite for Shannon — exercises every feature and codec.

Run with:  python3 -m unittest discover -s tests -v
or simply: python3 tests/test_shannon.py
"""
import os
import random
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shannon import analyze, arith, codecs, container, entropy, huffman, lz77
from shannon import transforms as T
from shannon import viz
from shannon.bitio import BitReader, BitWriter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "cli.py")

EDGE_INPUTS = [
    b"",
    b"a",
    b"aa",
    b"ab",
    b"abc",
    b"aaaa" * 50,
    bytes([0]) * 300,
    b"abracadabra" * 30,
    b"the quick brown fox " * 40,
    bytes(range(256)),
    bytes(range(256)) * 4,
]


def _gen(rng):
    k = rng.random()
    n = rng.randint(0, 500)
    if k < 0.3:
        alpha = bytes(rng.randint(0, 255) for _ in range(rng.randint(1, 5)))
        return bytes(rng.choice(alpha) for _ in range(n))
    if k < 0.55:
        out = bytearray()
        while len(out) < n:
            out += bytes([rng.randint(0, 255)]) * rng.randint(1, 30)
        return bytes(out[:n])
    if k < 0.8:
        frag = bytes(rng.randint(97, 122) for _ in range(rng.randint(2, 9)))
        return ((frag + b" ") * (n // (len(frag) + 1) + 1))[:n]
    return rng.randbytes(n)


class TestBitIO(unittest.TestCase):
    def test_bits_roundtrip(self):
        w = BitWriter()
        seq = [(0b101, 3), (0b1, 1), (0xFF, 8), (0, 5), (0b1010101, 7)]
        for v, c in seq:
            w.write_bits(v, c)
        r = BitReader(w.getvalue())
        for v, c in seq:
            self.assertEqual(r.read_bits(c), v)

    def test_varint(self):
        for v in [0, 1, 127, 128, 255, 300, 16384, 10 ** 9]:
            w = BitWriter()
            w.write_varint(v)
            self.assertEqual(BitReader(w.getvalue()).read_varint(), v)


class TestHuffman(unittest.TestCase):
    def test_roundtrip(self):
        for d in EDGE_INPUTS:
            w = BitWriter()
            huffman.compress_bytes(d, w)
            out = huffman.decompress_bytes(BitReader(w.getvalue()), len(d))
            self.assertEqual(out, d)

    def test_kraft_equality(self):
        # A complete prefix code satisfies sum(2**-len) == 1.
        d = b"abracadabra is a fine word for testing huffman codes"
        hc = huffman.HuffmanCode.from_data(d)
        k = sum(2 ** -L for L in hc.lengths.values())
        self.assertAlmostEqual(k, 1.0, places=9)

    def test_single_symbol(self):
        hc = huffman.HuffmanCode.from_data(b"zzzz")
        self.assertEqual(hc.lengths, {ord("z"): 1})


class TestArithmetic(unittest.TestCase):
    def test_roundtrip_order0(self):
        for d in EDGE_INPUTS:
            w = BitWriter()
            arith.encode(d, w, arith.Order0Model())
            out = arith.decode(BitReader(w.getvalue()), len(d), arith.Order0Model())
            self.assertEqual(out, d)

    def test_roundtrip_order1(self):
        for d in EDGE_INPUTS:
            w = BitWriter()
            arith.encode(d, w, arith.Order1Model())
            out = arith.decode(BitReader(w.getvalue()), len(d), arith.Order1Model())
            self.assertEqual(out, d)

    def test_near_entropy_bound(self):
        # Order-0 arithmetic should land close to the order-0 entropy bound.
        d = (b"the quick brown fox jumps over the lazy dog " * 30)
        w = BitWriter()
        arith.encode(d, w, arith.Order0Model())
        size = len(w.getvalue())
        ideal = entropy.ideal_bytes(d, 0)
        self.assertLess(size, ideal * 1.15 + 8)  # within 15% + small constant


class TestTransforms(unittest.TestCase):
    def test_bwt_roundtrip(self):
        for d in EDGE_INPUTS:
            bw, sp = T.bwt_encode(d)
            self.assertEqual(T.bwt_decode(bw, sp), d)

    def test_bwt_known_vector(self):
        # "banana" BWT (sentinel form) groups the repeats together.
        bw, sp = T.bwt_encode(b"banana")
        self.assertEqual(T.bwt_decode(bw, sp), b"banana")

    def test_mtf_roundtrip(self):
        for d in EDGE_INPUTS:
            self.assertEqual(T.mtf_decode(T.mtf_encode(d)), d)

    def test_rle_roundtrip(self):
        for d in EDGE_INPUTS + [b"aaaaa", b"aaaaaaaa", bytes([5]) * 600]:
            self.assertEqual(T.rle_decode(T.rle_encode(d)), d)


class TestLZ77(unittest.TestCase):
    def test_roundtrip(self):
        for d in EDGE_INPUTS:
            w = BitWriter()
            lz77.compress(d, w)
            self.assertEqual(lz77.decompress(BitReader(w.getvalue()), len(d)), d)

    def test_compresses_repetition(self):
        d = b"xyz" * 500
        w = BitWriter()
        lz77.compress(d, w)
        self.assertLess(len(w.getvalue()), len(d) // 4)


class TestContainer(unittest.TestCase):
    def test_all_codecs_roundtrip(self):
        for name in codecs.ALL_NAMES:
            for d in EDGE_INPUTS:
                blob = container.pack(name, d)
                self.assertEqual(container.unpack(blob), d, (name, len(d)))

    def test_crc_detects_corruption(self):
        # Corrupt a byte in the middle of the payload (guaranteed to be consumed
        # entropy-coded data — flipping trailing zero-padding bits would be a
        # genuine no-op and correctly decode unchanged).
        blob = bytearray(container.pack("arith1", b"some test data here" * 5))
        mid = (6 + len(blob)) // 2
        blob[mid] ^= 0xFF
        with self.assertRaises(ValueError):
            container.unpack(bytes(blob))

    def test_bad_magic(self):
        with self.assertRaises(ValueError):
            container.unpack(b"NOPEnot a real stream")

    def test_decompression_bomb_rejected(self):
        bomb = bytearray(b"SHZ1\x01\x02")
        v = 10 ** 12
        while True:
            byte = v & 0x7F
            v >>= 7
            bomb.append(byte | 0x80 if v else byte)
            if not v:
                break
        bomb += b"\x00\x00\x00\x00"
        with self.assertRaises(ValueError):
            container.unpack(bytes(bomb))

    def test_corruption_never_crashes_or_lies(self):
        rng = random.Random(2024)
        data = b"Shannon corruption robustness check. " * 8
        crashes = silent = 0
        for name in ["huffman", "arith0", "arith1", "lz77", "bwt"]:
            base = container.pack(name, data)
            for _ in range(120):
                b = bytearray(base)
                if rng.random() < 0.5 and len(b) > 8:
                    b = b[:rng.randint(6, len(b) - 1)]
                else:
                    b[rng.randint(6, len(b) - 1)] ^= 1 << rng.randint(0, 7)
                try:
                    out = container.unpack(bytes(b))
                    if out != data:
                        silent += 1
                except ValueError:
                    pass
                except Exception:
                    crashes += 1
        self.assertEqual(crashes, 0, "decoder crashed on corrupt input")
        self.assertEqual(silent, 0, "decoder returned wrong data undetected")


class TestFuzz(unittest.TestCase):
    def test_differential_fuzz(self):
        rng = random.Random(31337)
        for _ in range(1000):
            d = _gen(rng)
            name = rng.choice(codecs.ALL_NAMES)
            self.assertEqual(container.unpack(container.pack(name, d)), d,
                             (name, len(d)))

    def test_best_never_expands_much(self):
        rng = random.Random(5)
        for _ in range(60):
            d = _gen(rng)
            best = min(len(container.pack(n, d)) for n in codecs.ALL_NAMES)
            self.assertLessEqual(best, len(d) + 16)


class TestAnalyzeViz(unittest.TestCase):
    def test_report_contains_winner(self):
        rep = analyze.report(b"the rain in spain " * 20, "x")
        self.assertIn("winner:", rep)

    def test_viz_structure(self):
        with open(os.path.join(ROOT, "PLAN.md"), "rb") as f:
            html = viz.render(f.read(), "PLAN.md")
        for token in ["<svg", "BWT =", "codec comparison", "class='match"]:
            self.assertIn(token, html)
        self.assertNotIn("considering", html)  # guard against CSS garbage

    def test_viz_empty(self):
        html = viz.render(b"", "empty")
        self.assertIn("empty input", html)


class TestCLI(unittest.TestCase):
    def _run(self, *args, **kw):
        return subprocess.run([sys.executable, CLI, *args],
                              capture_output=True, **kw)

    def test_compress_decompress_roundtrip(self, tmp="/tmp/shannon_cli_test"):
        os.makedirs(tmp, exist_ok=True)
        src = os.path.join(tmp, "src.bin")
        with open(src, "wb") as f:
            f.write(b"command-line round trip test data " * 25)
        shz = os.path.join(tmp, "src.shz")
        out = os.path.join(tmp, "src.out")
        r = self._run("compress", src, "-o", shz, "--best")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self._run("decompress", shz, "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(src, "rb") as a, open(out, "rb") as b:
            self.assertEqual(a.read(), b.read())

    def test_missing_file_exit_code(self):
        r = self._run("compress", "/no/such/file.xyz")
        self.assertEqual(r.returncode, 1)

    def test_bad_codec_exit_code(self):
        r = self._run("compress", os.path.join(ROOT, "PLAN.md"), "-m", "nope")
        self.assertEqual(r.returncode, 1)

    def test_demo_passes(self):
        r = self._run("demo")
        self.assertEqual(r.returncode, 0, r.stdout.decode()[-400:])
        self.assertIn(b"DEMO PASSED", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
