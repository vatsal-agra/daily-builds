# Galley — PLAN

## Concept

**Galley** is a from-scratch *optimal typesetting engine*. Given a paragraph of
text and a column width, it decides where to break the lines so the whole
paragraph looks as good as possible — not greedily one line at a time, but by
globally minimizing a "total demerits" cost over *every possible* set of break
points. This is the algorithm Donald Knuth and Michael Plass invented for TeX
in 1981, and it is the reason professionally typeset books have even, river-free
text where naive word-processors leave ragged, gappy lines.

Galley implements the whole pipeline that sits between "a string of words" and
"a justified column of type":

```
text ──▶ tokenizer ──▶ Liang hyphenation ──▶ box/glue/penalty node list
                                                     │
                                       Knuth–Plass total-fit DP
                                                     │
                                          optimal breakpoints
                                                     │
                            ┌────────────────────────┼─────────────────────┐
                          SVG page            HTML playground         ASCII column
```

## Why it's interesting

- **The algorithm is genuinely beautiful.** Knuth–Plass turns "make this
  paragraph pretty" into a shortest-path problem over a graph of feasible
  breakpoints, solved with dynamic programming in near-linear time. Badness is
  measured as a cubic of how much each line's spaces must stretch or shrink;
  demerits fold in badness, hyphenation/penalty costs, and a "fitness class"
  penalty for putting a very loose line next to a very tight one. It is a
  textbook example of optimization producing something a human immediately
  perceives as *quality*.
- **It is under-appreciated.** Everyone has used a regex engine or a database;
  almost nobody has looked inside the line breaker that set every book they have
  read. Galley makes it inspectable.
- **It is fully verifiable.** The optimal cost from the DP can be checked
  against a brute-force search over all break subsets on small inputs (a perfect
  differential oracle), and the rendered output can be checked to reproduce the
  original word stream exactly (nothing dropped, nothing duplicated).
- **It produces a real visual artifact** — justified SVG/HTML pages you can look
  at and compare side-by-side with greedy breaking.

## Architecture

- `galley/metrics.py` — real Adobe AFM font width tables (Times-Roman,
  Courier) and a `Font` abstraction that turns characters/strings into advance
  widths at a given point size. This is genuine font data, not invented numbers.
- `galley/model.py` — the **box / glue / penalty** node model (Knuth's universal
  representation of typeset material) plus helpers to turn a string into a node
  list with inter-word glue and optional hyphenation penalties.
- `galley/hyphen.py` — **Liang's hyphenation algorithm** (the competitive
  pattern-matching method used by TeX): a real subset of the US-English patterns
  plus the exception list, compiled into hyphenation points.
- `galley/linebreak.py` — the **Knuth–Plass total-fit** line breaker: active
  node list, badness, demerits, fitness classes, forced/flagged breaks,
  looseness, plus a `greedy` first-fit breaker for comparison and a
  `brute_force` exhaustive optimal breaker used as a verification oracle.
- `galley/render.py` — lays broken lines out into **justified SVG**, a complete
  styled **HTML document**, and a monospace **ASCII** column; computes per-line
  stretch ratios and flags overfull/underfull lines.
- `galley/playground.py` — generates a single self-contained **interactive HTML**
  page with a JavaScript mirror of the Knuth–Plass breaker, so you can drag the
  column width and watch the paragraph re-break live.
- `galley/cli.py` + `galley.py` — command line: `break`, `render`, `hyphenate`,
  `compare`, `playground`, `demo`.
- `tests/` — unittest suite + `demo.sh`.

## Feature list

### Required (core)
1. **Box/glue/penalty model + tokenizer** — turn arbitrary text into Knuth's
   node list with correct inter-word glue (stretch/shrink) and a measured width
   for every word using real font metrics.
2. **Knuth–Plass total-fit line breaking** — the full DP: badness (cubic of
   adjustment ratio), demerits with line/flag/fitness penalties, active-node
   pruning, forced and optional breaks, returning the globally optimal break set
   with its total demerits.
3. **Liang hyphenation** — real pattern-based hyphenation that inserts optional
   breakpoints inside long words, wired into the node list as flagged penalties,
   so the breaker can hyphenate when it genuinely improves the paragraph.
4. **Renderers** — justified SVG page + full HTML document + ASCII column, with
   correct per-line spacing from the chosen breaks, plus a greedy-vs-optimal
   `compare` mode that reports the demerit/raggedness difference.

### Stretch
5. **Interactive HTML playground** — self-contained page with a JS port of the
   breaker; drag a slider to change the measure and watch lines re-break in real
   time, with badness heat-coloring and a live demerit readout.
6. **Brute-force optimality oracle + differential verification** — an exhaustive
   breaker that checks the DP returns a truly minimal-cost solution, fuzzed over
   many random paragraphs and widths.
7. **River detection** — find vertical "rivers" of whitespace running down a
   justified paragraph (a classic typographic defect) and report/score them.

## Verification strategy

- Unit tests for badness/adjustment-ratio/demerit math against hand-computed
  values.
- **Differential oracle:** Knuth–Plass DP total demerits == brute-force minimum
  over all feasible break subsets, fuzzed across random paragraphs/widths.
- **Round-trip invariant:** the words emitted by the renderer, with inserted
  hyphens removed, exactly equal the input word stream (no loss/dup/reorder).
- **Hyphenation spot-checks:** known words (hyphenation, computer, algorithm,
  …) hyphenate at the expected points.
- **No overfull lines** whenever shrink budget permits; flagged/loose line counts
  match between renderer and breaker.
- Optimal total demerits ≤ greedy total demerits on every corpus paragraph.
- A `demo.sh` that exercises every subcommand and emits real SVG/HTML artifacts.
