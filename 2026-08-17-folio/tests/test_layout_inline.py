"""Inline layout / line-breaking tests, independently verified against a
brute-force reference line-breaker (see `_reference_wrap`) rather than
against Chromium -- Folio's fixed-advance font model is deliberately not
trying to match a real rasterizer (see fontmetrics.py), so the correct
oracle here is "does the greedy algorithm pack words the way a from-scratch
brute-force check over the same width function says it should," not
"does it match Chrome's font."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.helpers import render
from folio import fontmetrics


def _reference_wrap(text, font_size, max_width):
    """A deliberately separate implementation: split on whitespace, then
    greedily accumulate words onto the current line using plain string
    lengths and fontmetrics.measure_text -- structured completely
    differently from layout_inline_content's fragment-list/state-machine
    implementation, so a shared bug is unlikely to slip through both."""
    words = text.split()
    lines = []
    cur = []
    cur_width = 0.0
    space_w = fontmetrics.char_width(font_size)
    for w in words:
        ww = fontmetrics.measure_text(w, font_size)
        extra = (space_w if cur else 0.0) + ww
        if cur and cur_width + extra > max_width + 1e-6:
            lines.append(cur)
            cur = [w]
            cur_width = ww
        else:
            cur.append(w)
            cur_width += extra
    if cur:
        lines.append(cur)
    return lines


class TestLineBreaking(unittest.TestCase):
    def _lines_text(self, box):
        return [" ".join(f[1] for f in line.fragments) for line in box.lines]

    def test_matches_brute_force_reference_short(self):
        text = "the quick brown fox jumps over the lazy dog again and again"
        _, _, root, t = render('<p data-t="p" style="width:220px;margin:0">%s</p>' % text)
        got = self._lines_text(t["p"])
        want = [" ".join(w) for w in _reference_wrap(text, 16.0, 220.0)]
        self.assertEqual(got, want)

    def test_matches_brute_force_reference_varied_widths(self):
        text = (
            "Folio is a browser rendering engine built entirely from scratch "
            "implementing the real CSS2.1 box model and a greedy line breaker"
        )
        for width in (100, 150, 200, 300, 500, 800):
            _, _, root, t = render(
                '<p data-t="p" style="width:%dpx;margin:0">%s</p>' % (width, text)
            )
            got = self._lines_text(t["p"])
            want = [" ".join(w) for w in _reference_wrap(text, 16.0, float(width))]
            self.assertEqual(got, want, "mismatch at width=%d" % width)

    def test_single_long_word_overflows_its_own_line(self):
        _, _, root, t = render(
            '<p data-t="p" style="width:40px;margin:0">supercalifragilisticexpialidocious short</p>'
        )
        lines = t["p"].lines
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].fragments[0][1], "supercalifragilisticexpialidocious")
        self.assertEqual(lines[1].fragments[0][1], "short")

    def test_explicit_br_forces_line_break(self):
        _, _, root, t = render('<p data-t="p" style="margin:0">one<br>two<br>three</p>')
        self.assertEqual(self._lines_text(t["p"]), ["one", "two", "three"])

    def test_whitespace_collapses_to_single_space(self):
        _, _, root, t = render('<p data-t="p" style="margin:0">a   b\n\tc</p>')
        self.assertEqual(self._lines_text(t["p"]), ["a b c"])

    def test_nested_inline_elements_flatten_into_one_run(self):
        _, _, root, t = render(
            '<p data-t="p" style="width:1000px;margin:0">Hello <b>bold</b> and <em>emph</em> text</p>'
        )
        self.assertEqual(self._lines_text(t["p"]), ["Hello bold and emph text"])

    def test_line_count_matches_reference_across_random_texts(self):
        import random

        rng = random.Random(1234)
        lorem = ["the", "quick", "brown", "fox", "jumps", "over", "lazy", "dog", "hello", "world", "folio"]
        for trial in range(15):
            n_words = rng.randint(3, 40)
            text = " ".join(rng.choice(lorem) for _ in range(n_words))
            width = rng.choice([80, 120, 180, 260, 400])
            _, _, root, t = render('<p data-t="p" style="width:%dpx;margin:0">%s</p>' % (width, text))
            got = self._lines_text(t["p"])
            want = [" ".join(w) for w in _reference_wrap(text, 16.0, float(width))]
            self.assertEqual(got, want, "trial %d: width=%d text=%r" % (trial, width, text))


class TestTextAlign(unittest.TestCase):
    def test_left_align_default(self):
        _, _, root, t = render('<p data-t="p" style="width:300px;margin:0">hi</p>')
        line = t["p"].lines[0]
        self.assertAlmostEqual(line.fragments[0][0], 0.0 + t["p"].border_box_x, delta=0.01)

    def test_right_align_flushes_to_content_edge(self):
        _, _, root, t = render(
            '<p data-t="p" style="width:300px;margin:0;text-align:right">hi</p>'
        )
        box = t["p"]
        line = box.lines[0]
        frag_x, text, style, fw = line.fragments[-1]
        right_edge = box.border_box_x + box.padding_left + box.content_width
        self.assertAlmostEqual(frag_x + fw, right_edge, delta=0.01)

    def test_center_align(self):
        _, _, root, t = render(
            '<p data-t="p" style="width:300px;margin:0;text-align:center">hi</p>'
        )
        box = t["p"]
        line = box.lines[0]
        left_gap = line.fragments[0][0] - box.border_box_x
        right_gap = (box.border_box_x + box.content_width) - (line.fragments[-1][0] + line.fragments[-1][3])
        self.assertAlmostEqual(left_gap, right_gap, delta=0.5)

    def test_justify_stretches_all_but_last_line(self):
        text = "one two three four five six seven eight nine ten eleven twelve"
        _, _, root, t = render(
            '<p data-t="p" style="width:220px;margin:0;text-align:justify">%s</p>' % text
        )
        box = t["p"]
        self.assertGreater(len(box.lines), 1)
        right_edge = box.border_box_x + box.content_width
        for line in box.lines[:-1]:
            last_frag_x, last_text, last_style, last_w = line.fragments[-1]
            self.assertAlmostEqual(last_frag_x + last_w, right_edge, delta=0.6)
        # the last line is NOT justified (stays left-aligned / ragged).
        last_line = box.lines[-1]
        last_end = last_line.fragments[-1][0] + last_line.fragments[-1][3]
        self.assertLess(last_end, right_edge - 1.0)


if __name__ == "__main__":
    unittest.main()
