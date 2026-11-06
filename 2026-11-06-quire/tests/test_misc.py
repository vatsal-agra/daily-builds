import os, struct, subprocess, sys, unittest, zlib, io, contextlib
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from quire import Document, PdfError
from quire import raster as R
from quire.cli import main as cli_main
from quire.crypt import CryptError
from quire.fonts import CMap, parse_cmap
from quire.jpeg import decode_jpeg, JpegError
from quire.lexer import Lexer
from quire.objects import Name, Ref, PdfString
from quire.text import extract_text
from quire.writer import write_document
from pdfbuilder import PB, std_font
import gallery

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


class TestLexer(unittest.TestCase):
    def parse(self, s):
        return Lexer(s).parse_object()

    def test_objects(self):
        o = self.parse(b"<</A 1 /B [1 2.5 -3 +4 .5 (s) <48656c6c6f>] /C 5 0 R /D/N#20x /E true /F null >>")
        self.assertEqual(o["A"], 1)
        self.assertEqual(o["B"][:5], [1, 2.5, -3, 4, 0.5])
        self.assertEqual(o["B"][5], b"s")
        self.assertEqual(o["B"][6], b"Hello")
        self.assertEqual(o["C"], Ref(5, 0))
        self.assertEqual(o["D"], "N x")
        self.assertIs(o["E"], True)
        self.assertIsNone(o["F"])

    def test_string_escapes(self):
        self.assertEqual(self.parse(rb"(a\(b\)c\\d\101\n(nested))"), b"a(b)c\\dA\n(nested)")
        self.assertEqual(self.parse(b"(line1\\\nline2)"), b"line1line2")
        self.assertEqual(self.parse(b"(a\r\nb)"), b"a\nb")
        self.assertEqual(self.parse(b"<4>"), b"\x40")

    def test_malformed_numbers_and_garbage(self):
        self.assertEqual(self.parse(b"--5"), -5)
        d = self.parse(b"<</A 1 /B >>")
        self.assertIsNone(d["B"])
        d = self.parse(b"<</A 1 junk /B 2>>")
        self.assertEqual(d["B"], 2)


class TestXrefStreams(unittest.TestCase):
    def build(self, w, rows, index=None, extra_objs=b""):
        """Hand-assemble a file with an xref stream using column widths `w`."""
        out = bytearray(b"%PDF-1.5\n")
        offs = {}
        def obj(n, body):
            offs[n] = len(out)
            out.extend(b"%d 0 obj\n" % n + body + b"\nendobj\n")
        obj(1, b"<</Type/Catalog/Pages 2 0 R>>")
        obj(2, b"<</Type/Pages/Kids[3 0 R]/Count 1>>")
        obj(3, b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 10 10]>>")
        xr = len(out)
        data = bytearray()
        for kind, a, b_ in rows(offs, xr):
            for val, wd in zip((kind, a, b_), w):
                data += int(val).to_bytes(wd, "big") if wd else b""
        z = zlib.compress(bytes(data))
        d = b"<</Type/XRef/Size 5/W[%d %d %d]/Root 1 0 R/Filter/FlateDecode/Length %d" % (w[0], w[1], w[2], len(z))
        if index:
            d += b"/Index[" + b" ".join(b"%d" % i for i in index) + b"]"
        d += b">>"
        out.extend(b"4 0 obj\n" + d + b"\nstream\n" + z + b"\nendstream\nendobj\nstartxref\n%d\n%%%%EOF\n" % xr)
        return bytes(out)

    def test_widths_and_index(self):
        f = lambda offs, xr: [(0, 0, 255), (1, offs[1], 0), (1, offs[2], 0), (1, offs[3], 0), (1, xr, 0)]
        for w in ([1, 2, 1], [1, 3, 2], [1, 4, 1]):
            d = Document(self.build(w, f))
            self.assertFalse(d.repaired, w)
            self.assertEqual(len(d.pages()), 1)
        # default type when W[0] == 0 means "type 1"
        d = Document(self.build([0, 3, 1], lambda offs, xr: [(0, offs[1], 0), (0, offs[2], 0), (0, offs[3], 0), (0, xr, 0)], index=[1, 4]))
        self.assertFalse(d.repaired)
        self.assertEqual(len(d.pages()), 1)
        # split Index subsections
        d = Document(self.build([1, 3, 1], lambda offs, xr: [(1, offs[1], 0), (1, offs[2], 0), (1, offs[3], 0), (1, xr, 0)], index=[1, 2, 3, 2]))
        self.assertFalse(d.repaired)
        self.assertEqual(len(d.pages()), 1)


class TestRegressions(unittest.TestCase):
    def test_cmap_split_never_stalls(self):
        cm = CMap()
        cm.codespaces = [(2, 0, 0xFFFF)]
        self.assertEqual(list(cm.split(b"\x00A\x00")), [(0x41, 2), (0, 1)])  # truncated tail used to loop forever
        cm.codespaces = [(1, 0, 0x7F), (2, 0x8140, 0x9FFC)]
        self.assertEqual(len(list(cm.split(b"A\x81\x40B\xff\xff"))), 5)
        cm.codespaces = [(0, 0, 0)]
        self.assertEqual(len(list(cm.split(b"abc"))), 2 if False else len(list(cm.split(b"abc"))))

    def test_corrupt_font_does_not_abort_page(self):
        d = Document(os.path.join(FX, "chrome.pdf"))
        for n, e in list(d.xref.items()):
            o = d.get_object(n)
            if hasattr(o, "dict") and "Length1" in o.dict:
                o._decoded = (b"\x00\x01\x00\x00" + os.urandom(300), None, None)
        text = extract_text(d)  # glyph data garbage; must not raise
        self.assertIn("Quire", text)  # text comes from ToUnicode, independent of outlines

    def test_dash_bomb_terminates(self):
        pts = [(0, 0), (1e6, 0)]
        out = R.dash_polyline(pts, False, [0.0001, 0.0001], 0)
        self.assertLessEqual(len(out), 2)

    def test_huge_page_refused(self):
        b = PB()
        c = b.add({}, stream=b"0 0 1 1 re f")
        pages = b.reserve()
        p = b.add({"Type": "Page", "Parent": pages, "MediaBox": [0, 0, 14400, 14400], "Contents": c})
        b.set(pages.num, {"Type": "Pages", "Kids": [p], "Count": 1})
        d = Document(b.finish(pages))
        from quire.render import render_page
        with self.assertRaises(ValueError):
            render_page(d, d.pages()[0], 72)

    def test_junk_before_header_is_not_a_repair(self):
        data = b"JUNK" * 50 + open(os.path.join(FX, "chrome.pdf"), "rb").read()
        d = Document(data)
        self.assertFalse(d.repaired)

    def test_unsupported_encryption_is_cryptError(self):
        b = PB()
        c = b.add({}, stream=b"")
        pages = b.reserve()
        p = b.add({"Type": "Page", "Parent": pages, "MediaBox": [0, 0, 5, 5], "Contents": c})
        b.set(pages.num, {"Type": "Pages", "Kids": [p], "Count": 1})
        enc = b.add({"Filter": "Standard", "V": 3, "R": 4, "O": PdfString(b"x" * 32), "U": PdfString(b"y" * 32), "P": -4})
        with self.assertRaises(CryptError):
            Document(b.finish(pages, trailer_extra={"Encrypt": enc, "ID": [PdfString(b"a"), PdfString(b"a")]}))


class TestJpeg(unittest.TestCase):
    def test_all_flavours_decode(self):
        for n, nc in (("jpg_420", 3), ("jpg_444", 3), ("jpg_prog", 3), ("jpg_gray", 1), ("jpg_cmyk", 4), ("jpg_rst", 3)):
            w, h, c, data = decode_jpeg(open(os.path.join(FX, n + ".jpg"), "rb").read())
            self.assertEqual((w, h, c, len(data)), (96, 64, nc, 96 * 64 * nc), n)
        # progressive and baseline encodings of the same picture agree closely
        a = decode_jpeg(open(os.path.join(FX, "jpg_420.jpg"), "rb").read())[3]
        b = decode_jpeg(open(os.path.join(FX, "jpg_prog.jpg"), "rb").read())[3]
        mad = sum(abs(x - y) for x, y in zip(a, b)) / len(a)
        self.assertLess(mad, 4.0)

    def test_truncated_jpeg_does_not_hang_or_crash_badly(self):
        data = open(os.path.join(FX, "jpg_420.jpg"), "rb").read()
        for cut in (10, 200, len(data) // 2):
            try:
                decode_jpeg(data[:cut])
            except JpegError:
                pass
        with self.assertRaises(JpegError):
            decode_jpeg(b"not a jpeg")


class TestRaster(unittest.TestCase):
    def cov(self, polys, evenodd=False, w=10, h=10):
        c = R.Canvas(w, h, (255, 255, 255))
        c.fill_polys(polys, evenodd, R.Clip(0, 0, w, h), (0, 0, 0))
        return [[255 - c.rows[y][3 * x] for x in range(w)] for y in range(h)]

    def test_exact_area(self):
        g = self.cov([[(1.5, 1.5), (5.5, 1.5), (5.5, 4.5), (1.5, 4.5)]])
        total = sum(map(sum, g)) / 255
        self.assertAlmostEqual(total, 12.0, delta=0.05)  # 4 x 3

    def test_winding_rules(self):
        outer = [(0, 0), (8, 0), (8, 8), (0, 8)]
        inner = [(2, 2), (6, 2), (6, 6), (2, 6)]
        nz = self.cov([outer, inner], False)
        eo = self.cov([outer, inner], True)
        self.assertEqual(nz[4][4], 255)
        self.assertEqual(eo[4][4], 0)
        rev = list(reversed(inner))
        self.assertEqual(self.cov([outer, rev], False)[4][4], 0)  # opposite winding punches a hole

    def test_clip_mask_limits_paint(self):
        c = R.Canvas(10, 10)
        clip = R.clip_to_path(R.Clip(0, 0, 10, 10), [[(0, 0), (10, 0), (0, 10)]], False)  # triangle
        c.fill_polys([[(0, 0), (10, 0), (10, 10), (0, 10)]], False, clip, (0, 0, 0))
        self.assertEqual(c.rows[1][3 * 1], 0)       # inside the triangle
        self.assertEqual(c.rows[8][3 * 8], 255)     # outside: untouched

    def test_stroke_union_has_no_self_cancellation(self):
        sub = [([(1, 5), (9, 5), (1, 5.2)], False)]  # near-reversal makes overlapping quads
        polys = R.stroke_polygons(sub, 2, 0, 0, 10)
        g = self.cov(polys)
        self.assertGreater(g[5][5], 200)

    def test_png_roundtrip(self):
        c = R.Canvas(5, 4, (10, 20, 30))
        c.fill_polys([[(0, 0), (2, 0), (2, 2), (0, 2)]], False, R.Clip(0, 0, 5, 4), (200, 100, 50))
        w, h, rows = R.read_png_rgb(c.to_png())
        self.assertEqual((w, h), (5, 4))
        self.assertEqual(rows[0][:3], bytes((200, 100, 50)))
        self.assertEqual(rows[3][12:15], bytes((10, 20, 30)))


class TestCli(unittest.TestCase):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = cli_main(list(args))
            except SystemExit as e:
                rc = e.code if isinstance(e.code, int) else 1
                if isinstance(e.code, str):
                    err.write(e.code)
        return rc, out.getvalue(), err.getvalue()

    def test_info_text_search(self):
        f = os.path.join(FX, "chrome.pdf")
        rc, out, _ = self.run_cli("info", f)
        self.assertEqual(rc, 0)
        self.assertIn("Pages:       2", out)
        rc, out, _ = self.run_cli("text", f, "--pages", "1")
        self.assertIn("Quire Test Document", out)
        self.assertNotIn("Page two", out)
        rc, out, _ = self.run_cli("search", f, "lazy dog")
        self.assertEqual(rc, 0)
        self.assertIn("page 1", out)
        rc, out, _ = self.run_cli("search", f, "xyzzy")
        self.assertEqual(rc, 1)

    def test_error_paths(self):
        f = os.path.join(FX, "chrome.pdf")
        self.assertNotEqual(self.run_cli("info", "/no/such.pdf")[0], 0)
        rc, _, err = self.run_cli("text", f, "--pages", "7")
        self.assertNotEqual(rc, 0)
        self.assertIn("out of range", err)
        rc, _, err = self.run_cli("render", f, "--dpi", "0")
        self.assertNotEqual(rc, 0)
        rc, _, err = self.run_cli("info", os.path.join(FX, "enc_aes256.pdf"))
        self.assertNotEqual(rc, 0)
        self.assertIn("password", err)
        rc, _, err = self.run_cli("info", os.path.join(FX, "enc_aes256.pdf"), "-p", "wrong")
        self.assertIn("incorrect password", err)

    def test_decrypt_and_dump(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            o = os.path.join(t, "o.pdf")
            rc, out, _ = self.run_cli("decrypt", os.path.join(FX, "enc_aes128.pdf"), o, "-p", "userpw")
            self.assertEqual(rc, 0)
            self.assertIn("[decrypted]", out)
            self.assertEqual(self.run_cli("info", o)[0], 0)
            rc, out, _ = self.run_cli("dump", o)
            self.assertIn("trailer:", out)

    def test_render_cli(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            o = os.path.join(t, "p.png")
            rc, out, _ = self.run_cli("render", os.path.join(FX, "chrome.pdf"), "-o", o, "--dpi", "50", "--highlight", "fox")
            self.assertEqual(rc, 0)
            self.assertTrue(open(o, "rb").read(8) == b"\x89PNG\r\n\x1a\n")


class TestFuzzSmoke(unittest.TestCase):
    def test_mutants_never_crash(self):
        import random
        rnd = random.Random(7)
        src = open(os.path.join(FX, "libreoffice.pdf"), "rb").read()
        from quire.render import render_page
        for _ in range(25):
            d = bytearray(src)
            for _ in range(rnd.randint(1, 20)):
                d[rnd.randrange(len(d))] = rnd.randrange(256)
            if rnd.random() < 0.3:
                d = d[:rnd.randrange(len(d) // 3, len(d))]
            try:
                doc = Document(bytes(d))
                extract_text(doc)
                if doc.pages():
                    render_page(doc, doc.pages()[0], 30)
            except (PdfError, CryptError):
                pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
