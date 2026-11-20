import os, random, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from striate import encode, scan_image, raster, png

CASES = [("code128", "Hello, World 123"), ("code128", "0123456789"), ("code128", "PJJ123C"),
         ("ean13", "4006381333931"), ("upca", "036000291452"), ("ean8", "96385074"),
         ("code39", "HELLO-39 $/+%"), ("itf", "1234567890")]


def texts(dets):
    return {(d.symbology, d.text) for d in dets}


class EndToEnd(unittest.TestCase):
    def test_clean_roundtrip_all_symbologies(self):
        for kind, t in CASES:
            b = encode(kind, t)
            for module in (2, 3, 5):
                d = scan_image(raster.render(b, module=module))
                self.assertIn((b.symbology, b.text), texts(d), (kind, module))
                self.assertEqual(len(d), 1)

    def test_upside_down_and_mirrored_row(self):
        for kind, t in CASES:
            b = encode(kind, t)
            img = raster.flip_h(raster.render(b, module=3))
            self.assertIn((b.symbology, b.text), texts(scan_image(img)), kind)

    def test_png_file_roundtrip(self):
        b = encode("code128", "FILE-TEST")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.png")
            raster.render(b, module=3).save(p)
            img = raster.Image.load(p)
            self.assertIn(("Code 128", "FILE-TEST"), texts(scan_image(img)))

    def test_degraded(self):
        rnd = random.Random(3)
        for kind, t in CASES:
            b = encode(kind, t)
            img = raster.render_subpixel(b, module=2.8 + rnd.random() * .4, height=60, gain=0.3)
            img = raster.noise(raster.blur(img, 0.8), 9, seed=4)
            self.assertIn((b.symbology, b.text), texts(scan_image(img, rotate=False)), kind)

    def test_two_barcodes_one_image(self):
        a, b = encode("code128", "TOP"), encode("ean13", "4006381333931")
        ia, ib = raster.render(a, module=3, height=50), raster.render(b, module=3, height=50)
        canvas = raster.Image(max(ia.w, ib.w) + 20, ia.h + ib.h + 20)
        raster.paste(canvas, ia, 5, 0); raster.paste(canvas, ib, 5, ia.h + 20)
        self.assertEqual(texts(scan_image(canvas, rotate=False)), {("Code 128", "TOP"), ("EAN-13", "4006381333931")})

    def test_no_barcode_in_blank_or_noise(self):
        self.assertEqual(scan_image(raster.Image(200, 100)), [])
        rnd = random.Random(0)
        img = raster.Image(300, 120, rows=[bytearray(rnd.randrange(256) for _ in range(300)) for _ in range(120)])
        self.assertEqual(scan_image(img), [])


class PngTests(unittest.TestCase):
    def test_roundtrip_gray(self):
        rows = [bytearray((x * 7 + y * 13) & 255 for x in range(37)) for y in range(11)]
        w, h, out = png.decode(png.encode_gray(rows, 37, 11))
        self.assertEqual((w, h, [bytes(r) for r in out]), (37, 11, [bytes(r) for r in rows]))

    def test_rgb_to_luma_and_errors(self):
        data = png.encode_rgb([bytes([255, 0, 0, 0, 255, 0])], 2, 1)
        w, h, rows = png.decode(data)
        self.assertEqual(list(rows[0]), [76, 149])
        with self.assertRaises(png.PNGError):
            png.decode(b"not a png")
        with self.assertRaises(png.PNGError):
            png.decode(data[:-30])


if __name__ == "__main__":
    unittest.main()
