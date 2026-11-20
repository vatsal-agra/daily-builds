"""Regression tests: one per adversarial-review finding."""
import heapq, os, random, struct, subprocess, sys, tempfile, unittest, zlib
ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
from striate import encode, scan_image, raster, png
from striate.symbologies import code128, ean


def found(img, **kw):
    return {(d.symbology, d.text) for d in scan_image(img, **kw)}


class Regressions(unittest.TestCase):
    def test_ean_pair_sum_ambiguity(self):          # finding 1
        # digits whose L patterns are only distinguishable with gain compensation
        for t in ("9638507", "4006381333931", "7392408"):
            b = encode("ean8" if len(t) == 7 else "ean13", t)
            img = raster.render_subpixel(b, module=2.6, height=40, gain=0.4)
            self.assertIn((b.symbology, b.text), found(img, rotate=False))

    def test_blurred_narrow_spaces(self):            # finding 2
        rnd = random.Random(2)
        for kind, t in (("code39", "AB-12"), ("itf", "5625"), ("code128", "Zx9"), ("ean13", "5901234123457")):
            b = encode(kind, t)
            img = raster.render_subpixel(b, module=2.4, height=50, gain=0.35)
            img = raster.noise(raster.blur(img, 0.9), 10, seed=1)
            self.assertIn((b.symbology, b.text), found(img, rotate=False), kind)

    def test_code128_stop_not_confused(self):        # finding 3
        self.assertIn(("Code 128", "PJJ123C"), found(raster.render(encode("code128", "PJJ123C"), module=3)))

    def test_no_false_positive_in_noise(self):       # finding 4
        for seed in range(12):
            rnd = random.Random(seed)
            img = raster.Image(500, 200, rows=[bytearray(rnd.choice((30, 220)) for _ in range(500)) for _ in range(200)])
            self.assertEqual(scan_image(img, rotate=False), [], seed)

    def test_inverted_polarity(self):                # finding 5
        img = raster.render(encode("ean13", "4006381333931"), module=3)
        img.rows = [bytearray(255 - v for v in r) for r in img.rows]
        d = scan_image(img)
        self.assertEqual([x.text for x in d], ["4006381333931"])
        self.assertTrue(d[0].extra.get("inverted"))

    def test_one_pixel_modules(self):                # finding 6
        for kind, t in (("code128", "MOD1"), ("ean13", "4006381333931"), ("code39", "ABC123"), ("itf", "123456")):
            b = encode(kind, t)
            self.assertIn((b.symbology, b.text), found(raster.render(b, module=1, height=40)), kind)

    def test_symbol_touching_border(self):           # finding 7
        b = encode("code128", "TIGHT")
        self.assertIn(("Code 128", "TIGHT"), found(raster.render(b, module=3, quiet=0)))

    def test_uneven_light_and_low_contrast(self):    # findings 7, 11
        base = raster.render_subpixel(encode("ean13", "4006381333931"), module=2.5, height=60, gain=0.2)
        for img in (raster.illumination(base, 0.85), raster.noise(raster.contrast(base, 90, 150), 2, seed=1)):
            self.assertIn(("EAN-13", "4006381333931"), found(img))

    def test_upca_reports_ean13_alias(self):         # finding 9
        d = scan_image(raster.render(encode("upca", "03600029145"), module=3))
        self.assertEqual(d[0].extra["ean13"], "0036000291452")

    def test_streak_corruption_never_yields_wrong_text(self):
        rnd = random.Random(7)
        for kind, gen in (("code128", lambda: "".join(rnd.choice("ABC123") for _ in range(8))),
                          ("ean13", lambda: "".join(rnd.choice("0123456789") for _ in range(12))),
                          ("code39", lambda: "".join(rnd.choice("ABC123") for _ in range(6))),
                          ("itf", lambda: "".join(rnd.choice("0123456789") for _ in range(8)))):
            for _ in range(10):
                b = encode(kind, gen()); img = raster.render(b, module=3, height=50)
                x = rnd.randrange(img.w)
                for y in range(img.h):
                    for xx in range(x, min(img.w, x + rnd.randint(1, 4))):
                        img.rows[y][xx] = rnd.choice((0, 255))
                for d in scan_image(img, rotate=False):
                    ok = d.text == b.text or (d.symbology == "UPC-A" and "0" + d.text == b.text)
                    self.assertTrue(ok, (kind, b.text, d.text))

    def test_rotation(self):
        base = raster.render(encode("code128", "ROTATE-ME"), module=3, height=70)
        for ang in (7, 30, 90, 180, -20):
            self.assertIn(("Code 128", "ROTATE-ME"), found(raster.rotate(base, ang)), ang)

    def test_tiny_and_blank_images_dont_crash(self):
        for w, h in ((1, 1), (2, 2), (5, 300), (300, 1)):
            self.assertEqual(scan_image(raster.Image(w, h)), [])

    def test_code128_optimal_vs_bruteforce(self):
        def inA(c): return c == code128.FNC1 or ord(c) < 96
        def inB(c): return c == code128.FNC1 or 32 <= ord(c) <= 127
        def optimal(text):
            n = len(text); pq = [(1, 0, s) for s in "ABC"]; seen = set()
            while pq:
                c, i, s = heapq.heappop(pq)
                if (i, s) in seen: continue
                seen.add((i, s))
                if i == n: return c
                ch = text[i]
                for t in "ABC":
                    if t != s: heapq.heappush(pq, (c + 1, i, t))
                if s == "C":
                    if ch == code128.FNC1: heapq.heappush(pq, (c + 1, i + 1, s))
                    elif i + 1 < n and ch.isdigit() and text[i + 1].isdigit(): heapq.heappush(pq, (c + 1, i + 2, s))
                else:
                    if (inA(ch) if s == "A" else inB(ch)): heapq.heappush(pq, (c + 1, i + 1, s))
                    elif (inB(ch) if s == "A" else inA(ch)): heapq.heappush(pq, (c + 2, i + 1, s))
        rnd = random.Random(9)
        al = [chr(i) for i in (1, 5, 31, 32, 48, 49, 50, 57, 65, 90, 95, 97, 122, 127)] + ["\xf1"]
        for _ in range(500):
            t = "".join(rnd.choice(al) for _ in range(rnd.randint(1, 12)))
            self.assertEqual(len(code128.encode_values(t)), optimal(t), repr(t))


def _mkpng(ctype, depth, rows, w, h, plte=None, interlace=0):
    raw = b"".join(b"\0" + bytes(r) for r in rows)
    def ch(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    out = png.SIG + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, depth, ctype, 0, 0, interlace))
    if plte: out += ch(b"PLTE", plte)
    return out + ch(b"IDAT", zlib.compress(raw)) + ch(b"IEND", b"")


class PngVariants(unittest.TestCase):
    def test_variants(self):
        g = lambda data: png.decode(data)[2][0].hex()
        self.assertEqual(g(_mkpng(0, 1, [[0b10100000]], 4, 1)), "ff00ff00")
        pal = bytes([0, 0, 0, 255, 255, 255, 255, 0, 0, 0, 255, 0])
        self.assertEqual(g(_mkpng(3, 2, [[0b00011011]], 4, 1, plte=pal)), "00ff4c95")
        self.assertEqual(g(_mkpng(0, 16, [[255, 0, 0, 0]], 2, 1)), "ff00")
        self.assertEqual(g(_mkpng(4, 8, [[10, 255, 20, 255]], 2, 1)), "0a14")
        self.assertEqual(g(_mkpng(6, 8, [[255, 0, 0, 255, 0, 0, 255, 255]], 2, 1)), "4c1d")

    def test_rejects(self):
        for data in (_mkpng(0, 8, [[1, 2]], 2, 1, interlace=1), _mkpng(0, 8, [[1, 2]], 100000, 100000), b"junk"):
            with self.assertRaises(png.PNGError):
                png.decode(data)

    def test_pgm(self):
        w, h, rows = png.decode_pgm(b"P5\n# c\n3 2\n255\n" + bytes([0, 128, 255, 1, 2, 3]))
        self.assertEqual((w, h, bytes(rows[1])), (3, 2, bytes([1, 2, 3])))
        w, h, rows = png.decode_pgm(b"P2\n2 1\n15\n0 15\n")
        self.assertEqual(list(rows[0]), [0, 255])


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        p = subprocess.run([sys.executable, "-m", "striate", *args], capture_output=True, text=True, cwd=ROOT)
        return p.returncode, p.stdout + p.stderr

    def test_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_cli("decode", os.path.join(d, "missing.png"))[0], 2)
            bad = os.path.join(d, "g.png")
            with open(bad, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\nxx")
            self.assertEqual(self.run_cli("decode", bad)[0], 2)
            blank = os.path.join(d, "b.png"); raster.Image(100, 50).save(blank)
            self.assertEqual(self.run_cli("decode", blank)[0], 1)
            ok = os.path.join(d, "o.png")
            self.assertEqual(self.run_cli("encode", "ean13", "4006381333931", "-o", ok)[0], 0)
            rc, out = self.run_cli("decode", ok)
            self.assertEqual(rc, 0); self.assertIn("4006381333931", out)
            self.assertEqual(self.run_cli("encode", "itf", "123", "-o", ok)[0], 2)
            self.assertEqual(self.run_cli("encode", "itf", "12", "-o", os.path.join(d, "x.txt"))[0], 2)
            self.assertEqual(self.run_cli("encode", "qr", "x", "-o", ok)[0], 2)


if __name__ == "__main__":
    unittest.main()
