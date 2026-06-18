# Galley

> **Optimal typesetting from scratch** — Knuth–Plass total-fit line breaking,
> Liang hyphenation, real Adobe AFM font metrics, and justified SVG / HTML / PNG
> / ASCII output. Pure Python 3 standard library, zero dependencies.

Galley is the algorithm that sets every professionally typeset book. A naïve
word processor breaks a paragraph **greedily** — it fills each line as far as it
can, then moves on — which leaves some lines stretched wide open and the next
crammed tight. Galley instead solves the whole paragraph at once: it turns *"make
this look good"* into a shortest-path problem over a graph of feasible
breakpoints and finds the set of breaks with the globally minimum **total
demerits**. The result is the even, river-free text you see in print.

```
text ─▶ tokenizer ─▶ Liang hyphenation ─▶ box / glue / penalty node list
                                                  │
                                    Knuth–Plass total-fit DP   ◀── verified
                                                  │                optimal vs
                                       optimal breakpoints        brute force
                                                  │
              ┌───────────────┬───────────────────┼─────────────┬───────────┐
           SVG page       HTML compare     interactive HTML   greeked PNG  ASCII
```

## Run it

No installation, no dependencies — just Python 3.8+.

```bash
# full guided tour: runs the algorithm, writes SVG/HTML/PNG artifacts
python3 galley.py demo --outdir demo_out

# Liang hyphenation
python3 galley.py hyphenate typesetting algorithm beautiful representation

# break a paragraph into a justified ASCII column (Knuth–Plass)
python3 galley.py break --width 56
python3 galley.py break --width 56 --method greedy        # compare the naive way

# optimal vs greedy, with a side-by-side HTML report
python3 galley.py compare --width 252 -o compare.html

# render justified type to SVG (multi-paragraph if the text has blank lines)
python3 galley.py render --file mytext.txt --width 320 --heat -o page.svg

# greeked PNG comparison — viewable without a browser
python3 galley.py preview --width 252 -o preview.png

# interactive playground: drag the measure, watch it re-break live
python3 galley.py playground -o playground.html

# detect whitespace "rivers"
python3 galley.py rivers --width 240
```

Run the tests and the whole demo:

```bash
./demo.sh                 # runs the 42-test suite, then the feature tour
python3 -m unittest discover -s tests -v
```

## Features

**Required (core)**

1. **Box / glue / penalty model** — Knuth's universal representation of typeset
   material, compiled from arbitrary text with real inter-word glue
   (stretch/shrink) and a measured width for every word.
2. **Knuth–Plass total-fit line breaking** — the full dynamic program: badness
   as a cubic of each line's adjustment ratio, demerits folding in badness,
   penalties, double-hyphen and fitness-class costs, active-node pruning,
   forced/flagged breaks, per-line measures, and TeX-style tolerance escalation
   so narrow columns still produce usable output. **Proven optimal** against a
   brute-force oracle (0 mismatches over thousands of random paragraphs).
3. **Liang hyphenation** — the real competitive pattern-matching algorithm with
   a genuine subset of the Knuth–Liang US-English patterns plus an exception
   list, with `lefthyphenmin`/`righthyphenmin` and punctuation-aware tokenizing
   (`beautiful,` → `beau-ti-ful,`).
4. **Renderers** — justified **SVG** (pixel-exact via `textLength`), a styled
   **HTML** comparison document, a multi-paragraph **page**, and a monospace
   **ASCII** column, all driven by per-line adjustment ratios.

**Stretch**

5. **Interactive HTML playground** — a faithful JavaScript port of the breaker
   that re-breaks the same node list live as you drag the measure/tolerance,
   with badness heat-coloring and a live demerit readout. Python↔JS parity is
   gated in the test suite via Node.
6. **Brute-force optimality oracle** — an exhaustive breaker used to prove the DP
   returns the true minimum, fuzzed across random paragraphs and widths.
7. **Greeked PNG preview** — a hand-rolled, dependency-free PNG encoder (zlib +
   CRC only) that renders the paragraph as word-bars so the shape difference
   between optimal and greedy is obvious without a browser.
8. **River detection** — finds vertical whitespace channels running down a
   justified column (a classic typographic defect) and reports them; optimal
   text shows materially fewer than greedy.

## How it works (the short version)

Each potential breakpoint is a node. The cost of setting the line between two
breaks is its **demerits**: `(10 + badness)²` plus penalty and fitness terms,
where `badness = 100·|r|³` and `r` is how far the line's spaces must stretch
(`r>0`) or shrink (`r<0`) to fill the measure. A line is *feasible* only if
`-1 ≤ r` and its badness is within tolerance. Dynamic programming over an
**active node list** — keeping the best path into each breakpoint per fitness
class, deactivating breakpoints that can no longer be reached feasibly — finds
the minimum-total-demerit path in close to linear time. That path is the set of
line breaks Galley returns.

## Verification

- **Differential oracle:** the Knuth–Plass DP's total demerits equals the
  brute-force minimum over *all* feasible break subsets — 0 mismatches across
  thousands of random paragraphs and measures.
- **Round-trip integrity:** the lines always tile the node list contiguously and
  the rendered words reproduce the input word stream exactly (nothing dropped,
  duplicated, or reordered).
- **Python↔JS parity:** the browser breaker produces identical breaks and
  demerits to the Python engine (checked under Node).
- **Hyphenation, math, render-validity, PNG, and full-CLI** tests — 42 in total,
  all green.

## Why I chose this today

The build ledger had drifted into a deep rut of SAT solvers (five in a row).
Typesetting is the opposite kind of problem and a genuinely beautiful,
under-appreciated algorithm: everyone has *used* the Knuth–Plass line breaker —
it set every book they have read — but almost nobody has looked inside it. It is
also a perfect fit for this format: a deep core algorithm with a crisp
optimality claim that can be *proven* against a brute-force oracle, plus output
that is immediately, visually satisfying.

## Where a human could take this next

- **Vertical typesetting / page breaking** — apply the same total-fit idea to
  break a galley into *pages*, balancing columns and avoiding widows/orphans
  (Knuth's "best fit" for the vertical list).
- **Microtypography** — character protrusion and font expansion (the hz-program
  / pdfTeX refinements) for even smoother margins.
- **Real font loading** — parse actual `.afm`/`.ttf` metrics and kerning pairs
  instead of the embedded base-14 tables; emit a true PDF.
- **Full Liang pattern set + other languages** — ship the complete
  `hyph-*.tex` tables and language selection.
- **A Markdown/HTML front end** — flow styled inline runs (bold/italic, sizes)
  through the same breaker to typeset whole documents.
- **Parshape & runarounds** — arbitrary per-line measures already work; expose
  them for shaped paragraphs and image wraps.

## Layout

```
galley/
  metrics.py     real Adobe AFM font width tables + Font abstraction
  model.py       box / glue / penalty items, tokenizer, hyphenate_token
  hyphen.py      Liang's algorithm + Knuth–Liang pattern subset + exceptions
  linebreak.py   Knuth–Plass DP, greedy, brute-force oracle, demerit scorer
  render.py      SVG / page-SVG / HTML / ASCII renderers
  verify.py      round-trip integrity + river detection
  preview.py     dependency-free PNG encoder + greeked comparison
  playground.py  self-contained interactive HTML (JS port of the breaker)
  cli.py         command-line interface
  demo.py        guided tour
galley.py        entry point
tests/           42-test unittest suite (incl. brute-force + JS parity)
demo.sh          test + feature-tour runner
```

Pure Python 3 standard library. Node is used **only** to gate JS↔Python parity
in tests; nothing at runtime depends on it.
