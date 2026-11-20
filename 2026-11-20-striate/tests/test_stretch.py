import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from striate import encode, scan_image, raster, gs1, bench, gallery
from striate.symbologies.code128 import FNC1


class GS1Tests(unittest.TestCase):
    H = "(01)09501101530003(3103)001234(17)261231(10)LOT 42"

    def test_build_parse_roundtrip(self):
        t = gs1.build(self.H)
        self.assertTrue(t.startswith(FNC1))
        self.assertEqual("".join(str(f) for f in gs1.parse(t)), self.H)

    def test_variable_field_mid_symbol_gets_separator(self):
        t = gs1.build("(10)AB(21)XY")
        self.assertEqual(t, FNC1 + "10AB" + FNC1 + "21XY")

    def test_meanings(self):
        f = {x.ai: x.meaning for x in gs1.parse(gs1.build(self.H))}
        self.assertEqual((f["17"], f["3103"], f["01"]), ("2026-12-31", "1.234 kg", "GTIN-14"))

    def test_validation(self):
        for bad in ["(01)09501101530004", "(17)261332", "(17)260230", "(99)", "01095", "(10)" + "x" * 21, "(77)1"]:
            with self.assertRaises(gs1.GS1Error, msg=bad):
                gs1.build(bad)
        with self.assertRaises(gs1.GS1Error):
            gs1.parse("0109501101530003")      # no FNC1

    def test_scan_image_attaches_fields(self):
        b = encode("code128", gs1.build(self.H))
        d = scan_image(raster.render(b, module=2, height=50))[0]
        self.assertTrue(d.gs1)
        self.assertEqual([f[0] for f in d.extra["gs1_fields"]], ["01", "3103", "17", "10"])

    def test_non_gs1_code128_has_no_fields(self):
        d = scan_image(raster.render(encode("code128", "plain"), module=3))[0]
        self.assertFalse(d.gs1); self.assertNotIn("gs1_fields", d.extra)


class BenchGalleryTests(unittest.TestCase):
    def test_bench_mild_is_perfect_and_never_wrong(self):
        res = bench.run(["blur"], n=2, symbologies=["code128", "ean13", "itf"])
        for kind, row in res["blur"].items():
            self.assertEqual(row[0][0], 1.0, kind)           # blur 0 -> all decode
            self.assertEqual(sum(w for _, w in row), 0, kind)  # never a wrong read at any severity
        self.assertIn("Gaussian blur", bench.format_table(res))
        self.assertTrue(bench.chart_svg("blur", res["blur"]).startswith("<svg"))

    def test_bench_unknown_sweep(self):
        with self.assertRaises(ValueError):
            bench.run(["bogus"])

    def test_gallery_all_scenarios_decode(self):
        for title, _, b, img in gallery.scenarios():
            got = {(d.symbology, d.text) for d in scan_image(img)}
            self.assertEqual(got, {(b.symbology, b.text)}, title)
        html = gallery.build_html()
        self.assertNotIn("not decoded", html); self.assertNotIn("wrong read", html)
        self.assertIn("<svg", html)


class SvgTests(unittest.TestCase):
    def test_svg_wellformed_and_escaped(self):
        import xml.dom.minidom
        from striate import svg
        b = encode("code39", "A$/+%")
        doc = xml.dom.minidom.parseString(svg.to_svg(b))
        self.assertEqual(doc.documentElement.tagName, "svg")
        self.assertEqual(len(doc.getElementsByTagName("rect")) - 1, (len(b.runs()) + 1) // 2)
        xml.dom.minidom.parseString(svg.to_svg(encode("code128", "<&>\x01"), text=True))


if __name__ == "__main__":
    unittest.main()
