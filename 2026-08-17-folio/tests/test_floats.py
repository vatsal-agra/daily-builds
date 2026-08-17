"""Float layout (CSS2.1 9.5) -- the stretch feature. Packing/wrapping
geometry is covered by the Chromium oracle in test_layout_block.py; this
file covers text-wrap-around-a-float and the specific bug (float
margin-box silently absorbing the rest of the container width) caught in
Phase 4 -- see REVIEW.md."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.helpers import render


class TestFloats(unittest.TestCase):
    def test_float_width_is_not_silently_expanded(self):
        # Regression: resolve_box_width's over-constrained-margin logic
        # (correct for normal blocks) must NOT apply to floats -- a
        # width:150px float must stay 150px, not grow a phantom margin to
        # fill the rest of a 600px container.
        _, _, root, t = render(
            '<div style="width:600px">'
            '<div data-t="f" style="float:left;width:150px;height:50px">x</div>'
            "</div>",
            css="body{margin:0}",
        )
        x, y, w, h = t["f"].rect()
        self.assertAlmostEqual(w, 150.0, delta=0.01)
        self.assertAlmostEqual(x, 0.0, delta=0.01)

    def test_text_wraps_around_left_float(self):
        text = " ".join("word%d" % i for i in range(40))
        _, _, root, t = render(
            '<div style="width:400px">'
            '<div style="float:left;width:100px;height:60px">img</div>'
            '<p data-t="p" style="margin:0">%s</p>'
            "</div>" % text,
            css="body{margin:0}",
        )
        box = t["p"]
        # lines overlapping the float's [0,60) vertical band must be
        # narrower than the full 400px container...
        narrowed = [l for l in box.lines if l.y < 60]
        widened = [l for l in box.lines if l.y >= 60]
        self.assertTrue(narrowed)
        self.assertTrue(widened, "paragraph should be long enough to clear past the float")
        for line in narrowed:
            self.assertAlmostEqual(line.avail_width, 300.0, delta=0.01)
            self.assertAlmostEqual(line.left_edge, 100.0, delta=0.01)
        # ...and lines entirely below it get the full width back.
        for line in widened:
            self.assertAlmostEqual(line.avail_width, 400.0, delta=0.01)
            self.assertAlmostEqual(line.left_edge, 0.0, delta=0.01)

    def test_text_wraps_around_right_float(self):
        text = " ".join("word%d" % i for i in range(20))
        _, _, root, t = render(
            '<div style="width:400px">'
            '<div style="float:right;width:100px;height:40px">img</div>'
            '<p data-t="p" style="margin:0">%s</p>'
            "</div>" % text,
            css="body{margin:0}",
        )
        box = t["p"]
        first_line = box.lines[0]
        self.assertAlmostEqual(first_line.left_edge, 0.0, delta=0.01)
        self.assertAlmostEqual(first_line.avail_width, 300.0, delta=0.01)

    def test_second_float_wraps_to_next_line_when_it_does_not_fit(self):
        _, _, root, t = render(
            '<div style="width:250px">'
            '<div data-t="a" style="float:left;width:150px;height:40px">a</div>'
            '<div data-t="b" style="float:left;width:150px;height:40px">b</div>'
            "</div>",
            css="body{margin:0}",
        )
        ax, ay, aw, ah = t["a"].rect()
        bx, by, bw, bh = t["b"].rect()
        self.assertAlmostEqual(ay, 0.0, delta=0.01)
        self.assertAlmostEqual(by, 40.0, delta=0.01)  # pushed below `a`, doesn't fit beside it
        self.assertAlmostEqual(bx, 0.0, delta=0.01)

    def test_clear_pushes_below_float(self):
        _, _, root, t = render(
            '<div style="width:300px">'
            '<div style="float:left;width:150px;height:80px">f</div>'
            '<div data-t="cleared" style="clear:left;height:10px">x</div>'
            "</div>",
            css="body{margin:0}",
        )
        x, y, w, h = t["cleared"].rect()
        self.assertAlmostEqual(y, 80.0, delta=0.01)
        self.assertAlmostEqual(w, 300.0, delta=0.01)  # clear doesn't narrow the box, only its position

    def test_no_floats_means_full_width_unaffected(self):
        # A non-regression check: with no floats at all, float_ctx must be
        # a pure no-op (this is what the rest of the suite already
        # exercises implicitly, but make it explicit here).
        _, _, root, t = render('<p data-t="p" style="width:300px;margin:0">hi there</p>')
        line = t["p"].lines[0]
        self.assertAlmostEqual(line.avail_width, 300.0, delta=0.01)

    def test_floated_img_element_is_blockified(self):
        # <img> defaults to display:inline; floating it must "blockify" it
        # (CSS2.1 9.7) rather than leaving it flattened into the text run.
        _, _, root, t = render(
            '<div style="width:300px">'
            '<img data-t="im" style="float:left;width:50px;height:50px">'
            "<p>text beside the image</p>"
            "</div>",
            css="body{margin:0}",
        )
        img_box = t["im"]
        self.assertEqual(img_box.float_type, "left")
        x, y, w, h = img_box.rect()
        self.assertAlmostEqual(w, 50.0, delta=0.01)


if __name__ == "__main__":
    unittest.main()
