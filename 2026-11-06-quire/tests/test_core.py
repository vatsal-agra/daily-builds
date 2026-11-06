import os, subprocess, sys, tempfile, unittest, zlib, difflib, shutil
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from quire import Document, PdfError
from quire.crypt import WrongPassword, aes_cbc_decrypt, aes_cbc_encrypt, aes_ecb_encrypt, rc4
from quire.text import extract_text, search_page
from quire.render import render_page
from quire.compare import diff_stats, load
from quire.raster import read_png_rgb
from quire.writer import write_document
from pdfbuilder import PB, std_font

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
HAVE_POPPLER = bool(shutil.which("pdftotext") and shutil.which("pdftoppm"))


def fx(n):
    return os.path.join(FX, n)


def poppler_text(path, pw=None):
    cmd = ["pdftotext"] + (["-upw", pw] if pw else []) + [path, "-"]
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def token_ratio(a, b):
    return difflib.SequenceMatcher(None, a.split(), b.split(), autojunk=False).ratio()


class TestParser(unittest.TestCase):
    def test_fixtures_open(self):
        for n in ("chrome.pdf", "libreoffice.pdf"):
            d = Document(fx(n))
            self.assertEqual(len(d.pages()), 2, n)
            self.assertFalse(d.repaired, n)

    def test_xref_stream_and_objstm_roundtrip(self):
        d = Document(fx("chrome.pdf"))
        data = write_document(d, compress=True)
        d2 = Document(data)
        self.assertFalse(d2.repaired)
        self.assertTrue(any(e[0] == "c" for e in d2.xref.values()), "no compressed objects")
        self.assertEqual(extract_text(d), extract_text(d2))

    def test_reconstruct_missing_startxref(self):
        data = open(fx("chrome.pdf"), "rb").read()
        d = Document(data[:data.rindex(b"startxref")])
        self.assertTrue(d.repaired)
        self.assertEqual(extract_text(d), extract_text(Document(fx("chrome.pdf"))))

    def test_reconstruct_bad_offsets(self):
        data = bytearray(open(fx("libreoffice.pdf"), "rb").read())
        i = data.index(b"xref\n0 ") if b"xref\n0 " in data else data.index(b"xref")
        j = data.index(b"trailer", i)
        for k in range(i + 20, j - 20, 20):  # smash entries
            data[k:k + 4] = b"9999"
        d = Document(bytes(data))
        self.assertTrue(d.repaired)
        self.assertEqual(len(d.pages()), 2)

    def test_reconstruct_truncated_file(self):
        data = open(fx("chrome.pdf"), "rb").read()
        d = Document(data[:len(data) * 9 // 10])  # xref+trailer lost; catalog should survive
        self.assertTrue(d.repaired)
        self.assertGreaterEqual(len(d.pages()), 1)

    def test_incremental_update_wins(self):
        b = PB()
        f = b.add(std_font())
        c = b.add({}, stream=b"BT /F1 20 Tf 10 100 Td (OLD) Tj ET")
        pg = b.reserve()
        pages = b.add({"Type": "Pages", "Kids": [pg], "Count": 1})
        b.set(pg.num, {"Type": "Page", "Parent": pages, "MediaBox": [0, 0, 200, 200], "Contents": c, "Resources": {"Font": {"F1": f}}})
        base = b.finish(pages)
        # append an update replacing the content stream (object 2) and a new xref section
        body = b"BT /F1 20 Tf 10 100 Td (NEW) Tj ET"
        off = len(base)
        upd = b"2 0 obj\n<</Length %d>>\nstream\n" % len(body) + body + b"\nendstream\nendobj\n"
        xr = off + len(upd)
        prev = int(base[base.rindex(b"startxref") + 10:].split()[0])
        upd += b"xref\n2 1\n%010d 00000 n \ntrailer\n<</Size 6 /Root 5 0 R /Prev %d>>\nstartxref\n%d\n%%%%EOF\n" % (off, prev, xr)
        d = Document(base + upd)
        self.assertFalse(d.repaired)
        self.assertIn("NEW", extract_text(d))
        self.assertNotIn("OLD", extract_text(d))

    def test_page_tree_inheritance_and_cycle(self):
        b = PB()
        c = b.add({}, stream=b"0 0 10 10 re f")
        pages = b.reserve()
        p1 = b.add({"Type": "Page", "Parent": pages, "Contents": c})
        p2 = b.add({"Type": "Page", "Parent": pages, "Contents": c, "Rotate": 90})
        b.set(pages.num, {"Type": "Pages", "Kids": [p1, p2, pages], "Count": 2, "MediaBox": [0, 0, 300, 100], "Rotate": 180})
        d = Document(b.finish(pages))
        pl = d.pages()
        self.assertEqual(len(pl), 2)
        self.assertEqual(d.page_box(pl[0]), [0, 0, 300, 100])
        self.assertEqual((d.page_rotate(pl[0]), d.page_rotate(pl[1])), (180, 90))

    def test_garbage_input_raises_cleanly(self):
        for junk in (b"", b"hello world", b"%PDF-1.4\n", os.urandom(500)):
            with self.assertRaises(PdfError):
                Document(junk)


class TestFilters(unittest.TestCase):
    def _stream_doc(self, data, filt, parms=None):
        b = PB()
        d = {"Filter": filt}
        if parms:
            d["DecodeParms"] = parms
        s = b.add(d, stream=data)
        c = b.add({}, stream=b"")
        pages = b.reserve()
        p = b.add({"Type": "Page", "Parent": pages, "MediaBox": [0, 0, 10, 10], "Contents": c})
        b.set(pages.num, {"Type": "Pages", "Kids": [p], "Count": 1})
        doc = Document(b.finish(pages))
        return doc, doc.get_object(s.num)

    def test_chain(self):
        import base64
        payload = b"The quick brown fox " * 50
        a85 = base64.a85encode(zlib.compress(payload), adobe=True)
        doc, s = self._stream_doc(a85, ["ASCII85Decode", "FlateDecode"])
        self.assertEqual(doc.decode_stream(s), payload)
        hexed = zlib.compress(payload).hex().encode() + b">"
        doc, s = self._stream_doc(hexed, ["ASCIIHexDecode", "FlateDecode"])
        self.assertEqual(doc.decode_stream(s), payload)

    def test_runlength_lzw(self):
        rl = bytes([2]) + b"abc" + bytes([254]) + b"x" + bytes([128])
        doc, s = self._stream_doc(rl, "RunLengthDecode")
        self.assertEqual(doc.decode_stream(s), b"abcxxx")
        # LZW example from the PDF spec
        lzw = bytes([0x80, 0x0B, 0x60, 0x50, 0x22, 0x0C, 0x0C, 0x85, 0x01])
        doc, s = self._stream_doc(lzw, "LZWDecode")
        self.assertEqual(doc.decode_stream(s), bytes([45, 45, 45, 45, 45, 65, 45, 45, 45, 66]))

    def test_png_predictor(self):
        rows = [bytes([i * 10 + j for j in range(6)]) for i in range(4)]
        enc = bytearray()
        prev = bytes(6)
        for ft, row in zip((0, 1, 2, 4), rows):
            enc.append(ft)
            for i, v in enumerate(row):
                a = row[i - 3] if i >= 3 else 0
                bb = prev[i]
                c = prev[i - 3] if i >= 3 else 0
                if ft == 0: pr = 0
                elif ft == 1: pr = a
                elif ft == 2: pr = bb
                else:
                    p = a + bb - c
                    pa, pb, pc = abs(p - a), abs(p - bb), abs(p - c)
                    pr = a if pa <= pb and pa <= pc else bb if pb <= pc else c
                enc.append((v - pr) & 255)
            prev = row
        doc, s = self._stream_doc(zlib.compress(bytes(enc)), "FlateDecode", {"Predictor": 15, "Columns": 2, "Colors": 3})
        self.assertEqual(doc.decode_stream(s), b"".join(rows))

    def test_corrupt_flate_tail_recovers_prefix(self):
        payload = os.urandom(0) + b"A" * 5000
        z = zlib.compress(payload)
        doc, s = self._stream_doc(z[:len(z) - 6] + b"\x00\x00\x00\x00\x00\x00", "FlateDecode")
        out = doc.decode_stream(s)
        self.assertTrue(out.startswith(b"AAAA") and len(out) > 100)


class TestCrypt(unittest.TestCase):
    def test_primitives(self):
        k = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
        p = bytes.fromhex("00112233445566778899aabbccddeeff")
        self.assertEqual(aes_ecb_encrypt(k, p).hex(), "69c4e0d86a7b0430d8cdb78070b4c55a")
        self.assertEqual(aes_ecb_encrypt(bytes(range(32)), p).hex(), "8ea2b7ca516745bfeafc49904b496089")
        self.assertEqual(aes_ecb_encrypt(bytes(range(24)), p).hex(), "dda97ca4864cdfe06eaf70a0ec0d7191")
        self.assertEqual(rc4(b"Key", b"Plaintext").hex(), "bbf316e8d940af0ad3")
        iv = os.urandom(16)
        msg = os.urandom(77)
        self.assertEqual(aes_cbc_decrypt(k, iv, aes_cbc_encrypt(k, iv, msg, pad=True), unpad=True), msg)

    def test_all_variants_match_plain_text(self):
        ref = extract_text(Document(fx("chrome.pdf")))
        for n in ("rc4_40", "rc4_128", "aes128", "aes256", "aes256_r5"):
            for pw in (b"userpw", b"ownerpw"):
                d = Document(fx(f"enc_{n}.pdf"), pw)
                self.assertEqual(extract_text(d), ref, f"{n} with {pw}")
                self.assertEqual(d.dec.who, "user" if pw == b"userpw" else "owner", n)

    def test_wrong_and_missing_password(self):
        for n in ("rc4_40", "rc4_128", "aes128", "aes256", "aes256_r5"):
            for pw in (b"", b"nope", b"USERPW"):
                with self.assertRaises(WrongPassword, msg=f"{n} {pw}"):
                    Document(fx(f"enc_{n}.pdf"), pw)

    def test_empty_user_password_autoopens(self):
        d = Document(fx("enc_aes128_openuser.pdf"))
        self.assertEqual(d.dec.who, "user")
        self.assertIn("quick brown fox", extract_text(d))

    def test_decrypt_roundtrip_is_plain(self):
        d = Document(fx("enc_aes256.pdf"), b"userpw")
        out = write_document(d)
        d2 = Document(out)
        self.assertIsNone(d2.dec)
        self.assertEqual(extract_text(d2), extract_text(Document(fx("chrome.pdf"))))
        self.assertNotIn(b"/Encrypt", out)

    def test_permissions_reported(self):
        d = Document(fx("enc_aes128_openuser.pdf"))
        self.assertIn("print", d.dec.permissions())


@unittest.skipUnless(HAVE_POPPLER, "poppler not installed")
class TestText(unittest.TestCase):
    def test_vs_pdftotext(self):
        for n in ("chrome.pdf", "libreoffice.pdf"):
            ours = extract_text(Document(fx(n)))
            self.assertGreater(token_ratio(ours, poppler_text(fx(n))), 0.95, n)

    def test_encrypted_vs_pdftotext(self):
        d = Document(fx("enc_aes256.pdf"), b"userpw")
        self.assertGreater(token_ratio(extract_text(d), poppler_text(fx("enc_aes256.pdf"), "userpw")), 0.95)

    def test_two_column_reading_order(self):
        t = extract_text(Document(fx("chrome.pdf")))
        self.assertLess(t.index("consectetur adipiscing"), t.index("fugiat nulla"))
        self.assertLess(t.index("laudantium, totam rem"), t.index("Boxed callout")) if "laudantium, totam rem" in t else None
        self.assertLess(t.index("Quire Test Document"), t.index("Lorem"))

    def test_search(self):
        d = Document(fx("chrome.pdf"))
        ms = search_page(d, 0, d.pages()[0], "brown fox")
        self.assertEqual(len(ms), 1)
        x0, y0, x1, y1 = ms[0].boxes[0]
        self.assertTrue(0 < x0 < x1 < 595 and 0 < y0 < y1 < 842)
        self.assertEqual(search_page(d, 0, d.pages()[0], "zzzz-not-there"), [])


@unittest.skipUnless(HAVE_POPPLER, "poppler not installed")
class TestRender(unittest.TestCase):
    def _cmp(self, path, page=1, dpi=72, pw=""):
        d = Document(path, pw.encode())
        cv = render_page(d, d.pages()[page - 1], dpi)
        with tempfile.TemporaryDirectory() as t:
            subprocess.check_call(["pdftoppm", "-r", str(dpi), "-png", "-f", str(page), "-l", str(page)] + (["-upw", pw] if pw else []) + [path, t + "/r"])
            ref = load(os.path.join(t, os.listdir(t)[0]))
        return diff_stats(read_png_rgb(cv.to_png()), ref)

    def test_chrome_pages(self):
        for pg in (1, 2):
            s = self._cmp(fx("chrome.pdf"), pg)
            self.assertLess(s["bad_frac"], 0.01, s)
            self.assertLess(s["mad"], 6, s)

    def test_libreoffice_pages(self):
        for pg in (1, 2):
            s = self._cmp(fx("libreoffice.pdf"), pg)
            self.assertLess(s["bad_frac"], 0.01, s)

    def test_hidpi(self):
        s = self._cmp(fx("chrome.pdf"), 1, 144)
        self.assertLess(s["bad_frac"], 0.01, s)

    def test_encrypted_renders_same(self):
        s = self._cmp(fx("enc_rc4_128.pdf"), 1, 72, "userpw")
        self.assertLess(s["bad_frac"], 0.01, s)


if __name__ == "__main__":
    unittest.main(verbosity=2)
