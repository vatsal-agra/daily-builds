import json, os, re, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from quire import Document
from quire.report import build_report
from quire.objects import PdfString
from pdfbuilder import PB

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def data_of(html):
    m = re.search(r"const D=(\{.*\});\nconst KC", html, re.S)
    return json.loads(m.group(1).replace("<\\/", "</"))


class TestReport(unittest.TestCase):
    def test_contents(self):
        d = Document(os.path.join(FX, "chrome.pdf"))
        D = data_of(build_report(d, "chrome.pdf", dpi=30))
        self.assertEqual(D["meta"]["pages"], 2)
        self.assertEqual(len(D["pages"]), 2)
        self.assertTrue(D["pages"][0]["png"].startswith("iVBOR"))      # base64 PNG
        self.assertIn("Quire Test Document", D["pages"][0]["text"])
        self.assertTrue(any("DejaVu" in f["name"] for f in D["fonts"]))
        self.assertTrue(all(f["program"] == "TrueType/OpenType" for f in D["fonts"]))
        kinds = {o["kind"] for o in D["objects"]}
        self.assertTrue({"page", "font", "fontfile", "content"} <= kinds, kinds)
        self.assertGreater(len(D["layout"]), 20)

    def test_encrypted_and_repaired_flags(self):
        d = Document(os.path.join(FX, "enc_aes256.pdf"), b"userpw")
        self.assertIn("AES-256", data_of(build_report(d, "x", dpi=20))["meta"]["encryption"])
        raw = open(os.path.join(FX, "chrome.pdf"), "rb").read()
        d = Document(raw[:raw.rindex(b"startxref")])
        self.assertTrue(data_of(build_report(d, "x", dpi=20))["meta"]["repaired"])

    def test_hostile_strings_cannot_break_out_of_the_script(self):
        b = PB()
        c = b.add({}, stream=b"BT ET")
        pages = b.reserve()
        p = b.add({"Type": "Page", "Parent": pages, "MediaBox": [0, 0, 10, 10], "Contents": c})
        b.set(pages.num, {"Type": "Pages", "Kids": [p], "Count": 1})
        info = b.add({"Title": PdfString(b"</script><img src=x onerror=alert(1)>")})
        d = Document(b.finish(pages, trailer_extra={"Info": info}))
        html = build_report(d, "</script><b>evil.pdf", dpi=20)
        self.assertEqual(html.count("</script>"), 1)  # only the template's own closing tag
        self.assertNotIn("<b>evil", html.split("<script>")[0])      # the <title>/markup part is HTML-escaped
        self.assertEqual(data_of(html)["meta"]["file"], "</script><b>evil.pdf")   # …and the data survives intact inside the script


if __name__ == "__main__":
    unittest.main(verbosity=2)
