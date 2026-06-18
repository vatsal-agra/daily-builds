# Galley

> Optimal typesetting from scratch — **Knuth–Plass total-fit line breaking**,
> **Liang hyphenation**, real **AFM font metrics**, and justified **SVG / HTML /
> ASCII** output. Pure Python 3 standard library, no dependencies.

Galley is the algorithm that sets every professionally typeset book: instead of
breaking a paragraph greedily one line at a time, it finds the set of line breaks
that minimises a global "total demerits" cost over *every* possible breaking,
turning "make this paragraph look good" into a shortest-path problem.

**Status: Phase 4 (stretch + polish) complete.** All four required features plus
four stretch features work end-to-end; adversarial review done. Full test suite
and ship notes still to come.

## Quick start

```bash
python3 galley.py demo --outdir demo_out      # full guided tour + artifacts
python3 galley.py hyphenate typesetting algorithm beautiful
python3 galley.py break --width 54            # ASCII column, Knuth–Plass
python3 galley.py compare --width 252 -o cmp.html   # optimal vs greedy
python3 galley.py render --width 320 --heat -o page.svg
python3 galley.py playground -o play.html     # interactive, drag the measure
```

## Features so far

- **Box / glue / penalty model** — Knuth's universal node representation, built
  from text with real inter-word glue (stretch/shrink) and measured word widths.
- **Knuth–Plass total-fit breaking** — full DP with badness, demerits, fitness
  classes, forced/flagged breaks, looseness, and TeX-style tolerance escalation.
  *Verified optimal* against a brute-force oracle (0 mismatches / thousands of
  random paragraphs).
- **Liang hyphenation** — the real competitive pattern-matching algorithm with a
  genuine subset of the Knuth–Liang US-English patterns plus an exception list.
- **Renderers** — justified SVG, a styled HTML comparison document, and a
  monospace ASCII column, all driven by per-line adjustment ratios.
- **Greedy first-fit** breaker + apples-to-apples demerit scorer for comparison.
- **Interactive playground** *(stretch)* — a JS port of the breaker that
  re-breaks live as you drag the measure.
- **Brute-force optimality oracle** *(stretch)* and **river detection**
  *(stretch)*.

See [PLAN.md](PLAN.md) for the full design.
