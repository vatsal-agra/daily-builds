"""Galley test suite — exercises every feature end to end."""

import json
import os
import random
import shutil
import subprocess
import sys
import unittest
import xml.dom.minidom as minidom

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from galley import (
    Font, available_families, build_paragraph, break_paragraph, greedy_break,
    brute_force_break, evaluate_breaks, badness, fitness_class, Hyphenator,
    hyphenate, INFINITY,
)
from galley.linebreak import INF_BAD, _natural_width
from galley.model import hyphenate_token
from galley.render import (
    render_svg, render_page_svg, render_ascii, ascii_paragraph,
    render_html_document, render_card, layout_line,
)
from galley.verify import roundtrip_words, count_rivers, reconstruct_words
from galley.preview import comparison_png, Canvas
from galley.cli import main as cli_main, SAMPLE

NODE = shutil.which("node") or (
    "/opt/node22/bin/node" if os.path.exists("/opt/node22/bin/node") else None)

WORDS = ("the of and a to in is was he for it with as his on be at by had not "
         "are but from beautiful wonderful representation typesetting optimal "
         "paragraph hyphenation knuth plass demerits justified").split()


def random_text(rng, lo=3, hi=9):
    return " ".join(rng.choice(WORDS) for _ in range(rng.randint(lo, hi)))


# --------------------------------------------------------------------------- #

class TestMetrics(unittest.TestCase):
    def test_known_widths(self):
        f = Font("times", 10)
        # AFM: Times-Roman space = 250/1000 em.
        self.assertAlmostEqual(f.space_width, 2.5)
        self.assertAlmostEqual(f.char_width("M"), 8.89)  # 889/1000 * 10
        self.assertAlmostEqual(f.width("AV"), (722 + 722) / 1000 * 10)

    def test_size_scales(self):
        self.assertAlmostEqual(Font("times", 20).width("hello"),
                               2 * Font("times", 10).width("hello"))

    def test_monospace(self):
        f = Font("courier", 10)
        self.assertTrue(f.monospace)
        self.assertAlmostEqual(f.char_width("i"), f.char_width("W"))

    def test_errors(self):
        with self.assertRaises(ValueError):
            Font("comic-sans", 12)
        with self.assertRaises(ValueError):
            Font("times", 0)
        self.assertIn("times", available_families())


class TestHyphenation(unittest.TestCase):
    def setUp(self):
        self.h = Hyphenator()

    def test_known_words(self):
        self.assertEqual(self.h.hyphenate("typesetting"), ["type", "set", "ting"])
        self.assertEqual(self.h.hyphenate("algorithm"), ["al", "go", "rithm"])
        self.assertEqual("-".join(self.h.hyphenate("hyphenation")),
                         "hy-phen-a-tion")

    def test_left_right_min(self):
        # No fragment in the first 2 / last 3 letters.
        for w in ["beautiful", "wonderful", "development", "establishment"]:
            frags = self.h.hyphenate(w)
            self.assertGreaterEqual(len(frags[0]), 2, w)
            self.assertGreaterEqual(len(frags[-1]), 3, w)

    def test_short_and_nonalpha_unchanged(self):
        self.assertEqual(self.h.hyphenate("cat"), ["cat"])
        self.assertEqual(self.h.hyphenate("a1b2"), ["a1b2"])

    def test_fragments_rejoin(self):
        rng = random.Random(1)
        for _ in range(200):
            w = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz")
                        for _ in range(rng.randint(5, 14)))
            self.assertEqual("".join(self.h.hyphenate(w)), w)

    def test_punctuation_aware_token(self):
        self.assertEqual(hyphenate_token("beautiful,", hyphenate),
                         ["beau", "ti", "ful,"])
        self.assertEqual(hyphenate_token("(typesetting)", hyphenate)[-1], "ting)")
        # interior punctuation -> left whole
        self.assertEqual(hyphenate_token("self-aware", hyphenate), ["self-aware"])

    def test_case_preserved(self):
        self.assertEqual("".join(self.h.hyphenate("Beautiful")), "Beautiful")


class TestMath(unittest.TestCase):
    def test_badness(self):
        self.assertAlmostEqual(badness(0.0), 0.0)
        self.assertAlmostEqual(badness(1.0), 100.0)
        self.assertAlmostEqual(badness(-0.5), 12.5)

    def test_fitness_classes(self):
        self.assertEqual(fitness_class(-1.0), 0)   # tight
        self.assertEqual(fitness_class(0.0), 1)    # decent
        self.assertEqual(fitness_class(0.8), 2)    # loose
        self.assertEqual(fitness_class(2.0), 3)    # very loose


class TestLineBreaking(unittest.TestCase):
    def setUp(self):
        self.f = Font("times", 10)
        self.h = Hyphenator()

    def _para(self, text):
        return build_paragraph(text, self.f, hyphenate=self.h.hyphenate)

    def test_differential_vs_brute_force(self):
        """The DP optimum must equal the brute-force optimum (the core claim)."""
        rng = random.Random(2026)
        feasible = mism = 0
        for _ in range(1200):
            para = self._para(random_text(rng))
            m = float(rng.choice([80, 100, 120, 150, 200]))
            kp = break_paragraph(para.items, m, tolerance=200, escalate=False)
            bf, _ = brute_force_break(para.items, m, tolerance=200)
            if bf < INF_BAD:
                feasible += 1
                if not kp.feasible or abs(kp.total_demerits - bf) > 1e-4:
                    mism += 1
        self.assertGreater(feasible, 600, "test should hit many feasible cases")
        self.assertEqual(mism, 0, f"{mism} DP/brute-force mismatches")

    def test_optimal_no_worse_than_greedy(self):
        rng = random.Random(99)
        for _ in range(300):
            para = self._para(random_text(rng, 6, 14))
            m = float(rng.choice([150, 220, 300]))
            kp = break_paragraph(para.items, m)
            gr = evaluate_breaks(para.items, greedy_break(para.items, m).breaks, m)
            if kp.feasible and gr.feasible:
                self.assertLessEqual(kp.total_demerits, gr.total_demerits + 1e-6)

    def test_greedy_feasible_when_possible(self):
        # On a comfortable measure greedy should not overflow.
        para = self._para(SAMPLE)
        gr = greedy_break(para.items, 320.0)
        self.assertTrue(gr.feasible)

    def test_escalation_handles_narrow(self):
        para = self._para(SAMPLE)
        for m in (90.0, 110.0, 140.0):
            br = break_paragraph(para.items, m)
            self.assertTrue(br.feasible, f"escalation failed at {m}")

    def test_overfull_unbreakable_word(self):
        para = self._para("supercalifragilisticexpialidocious short")
        br = break_paragraph(para.items, 40.0, escalate=False)
        # No crash; the long word forces an overfull line.
        self.assertGreaterEqual(len(br.lines), 1)

    def test_empty_and_single(self):
        for text in ("", "hello"):
            para = self._para(text)
            br = break_paragraph(para.items, 200.0)
            self.assertGreaterEqual(len(br.lines), 1)

    def test_per_line_measure(self):
        para = self._para(SAMPLE)
        br = break_paragraph(para.items, [200.0, 260.0, 300.0])
        self.assertTrue(br.feasible)


class TestRoundTrip(unittest.TestCase):
    def setUp(self):
        self.f = Font("times", 11)
        self.h = Hyphenator()

    def test_roundtrip_many(self):
        rng = random.Random(7)
        for _ in range(500):
            text = random_text(rng, 4, 16)
            para = build_paragraph(text, self.f, hyphenate=self.h.hyphenate)
            m = float(rng.choice([120, 180, 240, 320]))
            br = break_paragraph(para.items, m)
            ok, msg = roundtrip_words(para.items, br, para.words)
            self.assertTrue(ok, f"{msg} | text={text!r} m={m}")

    def test_lines_tile_items(self):
        para = build_paragraph(SAMPLE, self.f, hyphenate=self.h.hyphenate)
        br = break_paragraph(para.items, 240.0)
        self.assertEqual(br.lines[0].start, 0)
        for a, b in zip(br.lines, br.lines[1:]):
            self.assertEqual(a.end, b.start)

    def test_reconstruct_matches_words(self):
        para = build_paragraph(SAMPLE, self.f, hyphenate=self.h.hyphenate)
        br = break_paragraph(para.items, 200.0)
        self.assertEqual(reconstruct_words(para.items, br), para.words)


class TestRivers(unittest.TestCase):
    def test_optimal_no_more_rivers_than_greedy(self):
        f = Font("times", 11)
        h = Hyphenator()
        para = build_paragraph(SAMPLE, f, hyphenate=h.hyphenate)
        kp = break_paragraph(para.items, 252.0)
        gr = greedy_break(para.items, 252.0)
        self.assertLessEqual(len(count_rivers(para.items, kp, f)),
                             len(count_rivers(para.items, gr, f)))


class TestRender(unittest.TestCase):
    def setUp(self):
        self.f = Font("times", 11)
        self.h = Hyphenator()
        self.para = build_paragraph(SAMPLE, self.f, hyphenate=self.h.hyphenate)
        self.br = break_paragraph(self.para.items, 280.0)

    def test_svg_valid_xml(self):
        svg = render_svg(self.para.items, self.br, self.f, 280.0, heat=True,
                         title="Test")
        minidom.parseString(svg)  # raises on malformed XML
        self.assertIn("textLength", svg)

    def test_page_svg_valid(self):
        paras = []
        for chunk in ["alpha beta gamma delta epsilon",
                      "one two three four five six seven eight"]:
            p = build_paragraph(chunk, self.f, hyphenate=self.h.hyphenate)
            paras.append((p.items, break_paragraph(p.items, 200.0)))
        svg = render_page_svg(paras, self.f, 200.0, title="Doc")
        minidom.parseString(svg)

    def test_svg_escapes_specials(self):
        p = build_paragraph("a < b & c > d \"quote\"", self.f)
        br = break_paragraph(p.items, 200.0)
        svg = render_svg(p.items, br, self.f, 200.0)
        minidom.parseString(svg)
        self.assertNotIn("a < b", svg.replace("&lt;", ""))

    def test_html_document_parses(self):
        card = render_card("T", "meta", render_svg(self.para.items, self.br,
                           self.f, 280.0), [("lines", "5")])
        doc = render_html_document("Title", "sub", [card])
        self.assertIn("<!DOCTYPE html>", doc)
        self.assertIn("</html>", doc)

    def test_ascii_justification_exact_width(self):
        ap = ascii_paragraph(SAMPLE, hyphenate=self.h.hyphenate)
        br = break_paragraph(ap.items, 50.0)
        lines = render_ascii(ap.items, br)
        for l in lines[:-1]:  # last line is ragged
            if l.strip():
                self.assertLessEqual(len(l), 50)

    def test_layout_line_widths(self):
        runs, end_x = layout_line(self.para.items, self.br.lines[0])
        self.assertTrue(all(w > 0 for _, _, w in runs))


class TestPreview(unittest.TestCase):
    def test_png_signature_and_size(self):
        f = Font("times", 11)
        h = Hyphenator()
        para = build_paragraph(SAMPLE, f, hyphenate=h.hyphenate)
        kp = break_paragraph(para.items, 252.0)
        gr = greedy_break(para.items, 252.0)
        data = comparison_png(para.items, kp, gr, f, 252.0, scale=2.0)
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        import struct
        w, ht = struct.unpack(">II", data[16:24])
        self.assertGreater(w, 0)
        self.assertGreater(ht, 0)

    def test_canvas_roundtrips_to_png(self):
        cv = Canvas(10, 10)
        cv.rect(2, 2, 5, 5, (0, 0, 0))
        self.assertEqual(cv.to_png()[:8], b"\x89PNG\r\n\x1a\n")


class TestCLI(unittest.TestCase):
    def _run(self, *argv):
        return cli_main(list(argv))

    def test_hyphenate(self):
        self.assertEqual(self._run("hyphenate", "typesetting"), 0)

    def test_break_roundtrip_ok(self):
        self.assertEqual(self._run("break", "--width", "50",
                                   "--text", random_text(random.Random(3), 8, 20)), 0)

    def test_render_writes_svg(self):
        out = "/tmp/_galley_test.svg"
        self.assertEqual(self._run("render", "--width", "260", "-o", out), 0)
        minidom.parse(out)
        os.remove(out)

    def test_render_multiparagraph(self):
        out = "/tmp/_galley_page.svg"
        self.assertEqual(self._run("render", "--width", "240", "-o", out,
                                   "--text", "alpha beta gamma\n\ndelta epsilon zeta"), 0)
        minidom.parse(out)
        os.remove(out)

    def test_compare(self):
        self.assertEqual(self._run("compare", "--width", "252"), 0)

    def test_preview_writes_png(self):
        out = "/tmp/_galley_test.png"
        self.assertEqual(self._run("preview", "--width", "252", "-o", out), 0)
        with open(out, "rb") as fh:
            self.assertEqual(fh.read(8), b"\x89PNG\r\n\x1a\n")
        os.remove(out)

    def test_playground_writes_html(self):
        out = "/tmp/_galley_play.html"
        self.assertEqual(self._run("playground", "-o", out), 0)
        with open(out) as fh:
            self.assertIn("breakKP", fh.read())
        os.remove(out)

    def test_rivers(self):
        self.assertEqual(self._run("rivers", "--width", "240"), 0)

    def test_invalid_width(self):
        self.assertEqual(self._run("render", "--width", "0"), 2)
        self.assertEqual(self._run("render", "--width", "-5"), 2)

    def test_empty_text_renders_empty(self):
        out = "/tmp/_galley_empty.svg"
        self.assertEqual(self._run("render", "--text", "", "-o", out), 0)
        os.remove(out)


@unittest.skipIf(NODE is None, "node not available for JS parity")
class TestJSParity(unittest.TestCase):
    def test_js_matches_python(self):
        from galley.playground import algorithm_js, _serialize_items
        f = Font("times", 11)
        h = Hyphenator()
        rng = random.Random(42)
        harness = algorithm_js() + (
            "\nconst fs=require('fs');"
            "const cases=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));"
            "const out=cases.map(c=>{const r=c.greedy?breakGreedy(c.items,c.m)"
            ":breakKP(c.items,c.m,c.tol);"
            "return {lines:r.lines.length,breaks:r.lines.map(l=>l.end),"
            "dem:Math.round(r.dem),feas:r.feasible};});"
            "console.log(JSON.stringify(out));")
        hpath = "/tmp/_galley_parity_harness.js"
        cpath = "/tmp/_galley_parity_cases.json"
        with open(hpath, "w") as fh:
            fh.write(harness)
        cases, expected = [], []
        for _ in range(60):
            para = build_paragraph(random_text(rng, 4, 12), f,
                                   hyphenate=h.hyphenate)
            m = float(rng.choice([180, 240, 300]))
            greedy = rng.random() < 0.5
            cases.append({"items": _serialize_items(para.items), "m": m,
                          "tol": 100, "greedy": greedy})
            if greedy:
                br = greedy_break(para.items, m)
            else:
                br = break_paragraph(para.items, m, tolerance=100)
            expected.append((len(br.lines), br.breaks))
        with open(cpath, "w") as fh:
            json.dump(cases, fh)
        out = subprocess.check_output([NODE, hpath, cpath]).decode()
        got = json.loads(out)
        for (exp_lines, exp_breaks), g in zip(expected, got):
            self.assertEqual(g["lines"], exp_lines)
            self.assertEqual(g["breaks"], exp_breaks)
        os.remove(hpath)
        os.remove(cpath)


if __name__ == "__main__":
    unittest.main(verbosity=2)
