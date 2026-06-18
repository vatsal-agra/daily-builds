#!/usr/bin/env python3
"""Cinch test suite — unit, property, differential, and fuzz tests.

Run:  python3 tests.py          (default fuzz volume)
      CINCH_FUZZ=20000 python3 tests.py   (heavy fuzz)
"""
from __future__ import annotations

import heapq
import os
import random
import unittest
import zlib

import container as C
import corpus
import deflate
import huffman
import lz77
import rangecoder as rc
from bitio import BitReader, BitWriter
from util import crc32, read_uvarint, write_uvarint

FUZZ = int(os.environ.get("CINCH_FUZZ", "4000"))


def rand_bytes(rng: random.Random, max_len: int = 512) -> bytes:
    n = rng.randint(0, max_len)
    mode = rng.random()
    if mode < 0.25:                       # full-range random
        return bytes(rng.randrange(256) for _ in range(n))
    if mode < 0.5:                        # skewed small alphabet
        alpha = [rng.randrange(256) for _ in range(rng.randint(1, 4))]
        return bytes(rng.choice(alpha) for _ in range(n))
    if mode < 0.7:                        # single value (runs)
        return bytes([rng.randrange(256)]) * n
    if mode < 0.85:                       # repeated chunk
        clen = rng.randint(1, 16)
        chunk = bytes(rng.randrange(256) for _ in range(clen))
        return (chunk * (n // clen + 1))[:n]
    return bytes(rng.choice(b"abcdefg \n") for _ in range(n))  # texty


class TestBitIO(unittest.TestCase):
    def test_roundtrip(self):
        rng = random.Random(1)
        for _ in range(500):
            bits = [rng.randint(0, 1) for _ in range(rng.randint(0, 200))]
            bw = BitWriter()
            for b in bits:
                bw.write_bit(b)
            br = BitReader(bw.getvalue())
            for b in bits:
                self.assertEqual(br.read_bit(), b)

    def test_multibit_msb_lsb(self):
        rng = random.Random(2)
        for _ in range(500):
            vals = [(rng.randrange(1 << 16), rng.randint(0, 16)) for _ in range(20)]
            bw = BitWriter()
            for v, c in vals:
                bw.write_bits(v & ((1 << c) - 1), c)
            br = BitReader(bw.getvalue())
            for v, c in vals:
                self.assertEqual(br.read_bits(c), v & ((1 << c) - 1))
            bw = BitWriter()
            for v, c in vals:
                bw.write_bits_lsb(v & ((1 << c) - 1), c)
            br = BitReader(bw.getvalue())
            for v, c in vals:
                self.assertEqual(br.read_bits_lsb(c), v & ((1 << c) - 1))


class TestUtil(unittest.TestCase):
    def test_varint(self):
        rng = random.Random(3)
        for _ in range(2000):
            v = rng.randrange(0, 1 << rng.randint(0, 60))
            out = bytearray()
            write_uvarint(out, v)
            got, pos = read_uvarint(bytes(out), 0)
            self.assertEqual(got, v)
            self.assertEqual(pos, len(out))

    def test_crc32_matches_zlib(self):
        rng = random.Random(4)
        for _ in range(500):
            d = rand_bytes(rng)
            self.assertEqual(crc32(d), zlib.crc32(d))


def _standard_huffman_cost(freqs):
    syms = list(freqs)
    if len(syms) == 1:
        return freqs[syms[0]]
    h = []
    cnt = 0
    for s in syms:
        heapq.heappush(h, (freqs[s], cnt, [s]))
        cnt += 1
    lengths = {s: 0 for s in syms}
    while len(h) > 1:
        w1, _, m1 = heapq.heappop(h)
        w2, _, m2 = heapq.heappop(h)
        for s in m1 + m2:
            lengths[s] += 1
        heapq.heappush(h, (w1 + w2, cnt, m1 + m2))
        cnt += 1
    return sum(freqs[s] * lengths[s] for s in syms)


class TestHuffman(unittest.TestCase):
    def test_package_merge_optimal_and_valid(self):
        rng = random.Random(5)
        for _ in range(2000):
            n = rng.randint(1, 60)
            freqs = {i: rng.randint(1, 5000) for i in range(n)}
            lengths = huffman.length_limited_lengths(freqs, limit=60)
            # optimal cost vs textbook Huffman
            cost = sum(freqs[s] * lengths[s] for s in freqs)
            self.assertEqual(cost, _standard_huffman_cost(freqs))
            if n > 1:
                kraft = sum(2.0 ** -lengths[s] for s in freqs)
                self.assertAlmostEqual(kraft, 1.0, places=9)

    def test_length_limit_respected(self):
        rng = random.Random(6)
        for _ in range(1000):
            n = rng.randint(2, 286)
            freqs = {i: rng.randint(1, 100000) for i in range(n)}
            lengths = huffman.length_limited_lengths(freqs, limit=15)
            self.assertTrue(all(1 <= ln <= 15 for ln in lengths.values()))
            kraft = sum(2.0 ** -ln for ln in lengths.values())
            self.assertLessEqual(kraft, 1.0 + 1e-9)

    def test_canonical_prefix_free(self):
        rng = random.Random(7)
        for _ in range(500):
            n = rng.randint(2, 286)
            freqs = {i: rng.randint(1, 1000) for i in range(n)}
            codes, _ = huffman.build_codes(freqs, limit=15)
            seen = []
            for sym, (code, ln) in codes.items():
                seen.append((code, ln))
            # prefix-free: no code is a prefix of another
            for i in range(len(seen)):
                ci, li = seen[i]
                for j in range(len(seen)):
                    if i == j:
                        continue
                    cj, lj = seen[j]
                    if li <= lj and (cj >> (lj - li)) == ci:
                        self.fail("not prefix-free")

    def test_roundtrip(self):
        rng = random.Random(8)
        for _ in range(800):
            d = rand_bytes(rng)
            self.assertEqual(huffman.decode(huffman.encode(d)), d)


class TestLZ77(unittest.TestCase):
    def test_roundtrip_and_detokenize(self):
        rng = random.Random(9)
        for _ in range(1500):
            d = rand_bytes(rng)
            toks = lz77.tokenize(d)
            self.assertEqual(lz77.detokenize(toks), d)
            self.assertEqual(lz77.decode(lz77.encode(d)), d)

    def test_overlap_run(self):
        for d in [b"a" * 300, b"ab" * 200, b"abc" * 100, b"xabababy"]:
            self.assertEqual(lz77.decode(lz77.encode(d)), d)

    def test_match_distance_window_bounded(self):
        rng = random.Random(10)
        d = bytes(rng.randrange(256) for _ in range(50000))
        d = d + d[:1000]  # force a far-back match opportunity
        for tok in lz77.tokenize(d):
            if not isinstance(tok, int):
                length, dist = tok
                self.assertTrue(lz77.MIN_MATCH <= length <= lz77.MAX_MATCH)
                self.assertTrue(1 <= dist <= lz77.WINDOW)


class TestDeflate(unittest.TestCase):
    def test_roundtrip(self):
        rng = random.Random(11)
        for _ in range(1500):
            d = rand_bytes(rng)
            self.assertEqual(deflate.decode(deflate.encode(d)), d)

    def test_single_symbol_streams(self):
        # B1 regression: runs of one byte produce a single-symbol dist tree.
        for d in [b"a", b"a" * 5000, b"a" * 258, b"a" * 259, b"z" * 99999]:
            self.assertEqual(deflate.decode(deflate.encode(d)), d)


class TestRangeCoder(unittest.TestCase):
    def test_roundtrip(self):
        rng = random.Random(12)
        for _ in range(1500):
            d = rand_bytes(rng)
            self.assertEqual(rc.decode_order0(rc.encode_order0(d)), d)
            self.assertEqual(rc.decode_order1(rc.encode_order1(d)), d)

    def test_order1_beats_huffman_on_text(self):
        text = corpus.english(3000)
        self.assertLess(len(rc.encode_order1(text)), len(huffman.encode(text)))


class TestContainer(unittest.TestCase):
    METHODS = ["store", "huffman", "lz77", "deflate", "range0", "range1", "auto"]

    def test_all_methods_roundtrip(self):
        rng = random.Random(13)
        for _ in range(300):
            d = rand_bytes(rng, max_len=400)
            for m in self.METHODS:
                self.assertEqual(C.decompress(C.compress(d, m)), d)

    def test_empty_everywhere(self):  # B4
        for m in self.METHODS:
            blob = C.compress(b"", m)
            self.assertEqual(C.decompress(blob), b"")
            info = C.inspect(blob)
            self.assertEqual(info["original_size"], 0)

    def test_malformed_containers(self):  # B3
        bad = [b"", b"CINCH", C.MAGIC + bytes([1, 3, 0, 0, 0, 0]),
               b"NOTCINCH___", C.compress(b"hello world " * 50, "deflate")[:14]]
        for blob in bad:
            with self.assertRaises(C.CinchError):
                C.decompress(blob)

    def test_corruption_detected(self):
        rng = random.Random(14)
        data = corpus.english(800)
        silent_wrong = 0
        for m in ["huffman", "lz77", "deflate", "range0", "range1"]:
            base = C.compress(data, m)
            for _ in range(60):
                pos = rng.randint(11, len(base) - 1)
                b = bytearray(base)
                b[pos] ^= 1 << rng.randint(0, 7)
                try:
                    if C.decompress(bytes(b)) != data:
                        silent_wrong += 1
                except C.CinchError:
                    pass
        self.assertEqual(silent_wrong, 0)

    def test_corrupt_length_field_no_hang(self):
        # B5 regression: a corrupted length/EOF must fail fast, never hang.
        # Stomp bytes right after the header (the codec's length varint) with
        # large values and confirm we always get a clean CinchError quickly.
        data = corpus.english(400)
        for m in ["huffman", "lz77", "deflate", "range0", "range1"]:
            base = bytearray(C.compress(data, m))
            for pos in range(11, min(len(base), 20)):
                for val in (0xFF, 0x80, 0x00):
                    b = bytearray(base)
                    b[pos] = val
                    try:
                        out = C.decompress(bytes(b))
                        # If it decoded, it must equal the original (CRC-guarded).
                        self.assertEqual(out, data)
                    except C.CinchError:
                        pass

    def test_auto_never_worse(self):
        rng = random.Random(15)
        for _ in range(200):
            d = rand_bytes(rng, max_len=600)
            auto = C.compress(d, "auto")
            store = C.compress(d, "store")
            self.assertLessEqual(len(auto), len(store))
            self.assertEqual(C.decompress(auto), d)


class TestCorpusDifferential(unittest.TestCase):
    def test_corpus_roundtrip_all_methods(self):
        for name, data in corpus.all_corpus().items():
            for m in TestContainer.METHODS:
                self.assertEqual(C.decompress(C.compress(data, m)), data,
                                 f"{name}/{m}")

    def test_deflate_in_neighbourhood_of_zlib(self):
        # Not required to win, but must be within 2x of zlib on compressible text.
        data = corpus.english(4000)
        ours = len(deflate.encode(data))
        ref = len(zlib.compress(data, 9))
        self.assertLess(ours, ref * 2.0)


class TestFuzz(unittest.TestCase):
    def test_fuzz_all_methods(self):
        rng = random.Random(999)
        for _ in range(FUZZ):
            d = rand_bytes(rng, max_len=300)
            m = rng.choice(["store", "huffman", "lz77", "deflate", "range0", "range1"])
            self.assertEqual(C.decompress(C.compress(d, m)), d)


if __name__ == "__main__":
    print(f"running with FUZZ={FUZZ} (set CINCH_FUZZ to change)")
    unittest.main(verbosity=2)
