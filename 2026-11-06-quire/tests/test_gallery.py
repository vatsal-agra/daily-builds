"""Every gallery case rendered by quire must match poppler within a per-case budget."""
import os, subprocess, sys, tempfile, unittest, shutil
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gallery
from quire import Document
from quire.render import render_page
from quire.compare import diff_stats, load
from quire.raster import read_png_rgb

HAVE = bool(shutil.which("pdftoppm"))
# allowed fraction of pixels that differ by >48 even after 1px neighbourhood forgiveness
BUDGET = {"text_state": 0.03,  # non-embedded fonts: poppler substitutes different outlines
          "strokes": 0.01, "images": 0.01, "annotations": 0.01,  # DRAFT stamp uses a non-embedded font
          "default": 0.005}


@unittest.skipUnless(HAVE, "poppler not installed")
class TestGallery(unittest.TestCase):
    pass


def make(name):
    def t(self):
        try:
            data = gallery.build(name)
        except FileNotFoundError as e:
            self.skipTest(f"font not available: {e}")
        d = Document(data)
        cv = render_page(d, d.pages()[0], 144)
        with tempfile.TemporaryDirectory() as tmp:
            pdf = os.path.join(tmp, "g.pdf")
            open(pdf, "wb").write(data)
            subprocess.check_call(["pdftoppm", "-cropbox", "-r", "144", "-png", "-singlefile", pdf, os.path.join(tmp, "ref")], stderr=subprocess.DEVNULL)
            s = diff_stats(read_png_rgb(cv.to_png()), load(os.path.join(tmp, "ref.png")))
        self.assertLess(s["bad_frac"], BUDGET.get(name, BUDGET["default"]), f"{name}: {s}")
        self.assertEqual(d.warnings, [], f"{name} produced warnings")
    return t


for _n in gallery.CASES:
    setattr(TestGallery, "test_" + _n, make(_n))

if __name__ == "__main__":
    unittest.main(verbosity=2)
