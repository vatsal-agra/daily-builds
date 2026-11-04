# Gosper — a Hashlife cellular-automaton laboratory

## Concept
Gosper is a from-scratch implementation of Bill Gosper's **Hashlife** algorithm — a
hash-consed quadtree that memoises the future of every square of cells — generalised
to *any* two-state outer-totalistic ("Life-like", B/S) rule. It can jump a pattern
2^40 generations ahead in milliseconds, then analyse, classify, census and render it.

## Why it is interesting
* Hashlife makes the universe's *redundancy* the compute budget: a glider gun runs a
  trillion generations in the time naive simulation runs a few hundred, because the
  quadtree collapses repeated structure into shared nodes.
* Hash-consing gives O(1) structural equality, which makes period / spaceship
  detection and growth classification almost free.
* Nothing in the repo so far touches cellular automata (first CA build here).

## Architecture
```
life/
  universe.go   hash-consed quadtree, rule table, result(node,j) memoised stepper,
                universe expansion, compaction (GC by copy)
  naive.go      independent sparse-set reference simulator (the oracle)
  rle.go        RLE (+rule header), plaintext .cells, Golly Macrocell read/write
  patterns.go   built-in library (glider, gun, R-pentomino, acorn, ...)
  analyze.go    period/displacement, classification, population at gen N, growth
  census.go     random soups -> ash -> connected components -> named objects
  render.go     PNG (level-of-detail from node populations) + HTML/SVG report
main.go         CLI: run | info | analyze | census | render | report | verify | patterns
```
Core recursion: `result(n, j)` returns the centre half of a level-k node after 2^j
generations (j ≤ k-2), memoised per (node, j). 9 overlapping sub-squares, two phases.

## Features
| # | Feature | Status |
|---|---------|--------|
| 1 | Hashlife engine: any non-B0 B/S rule, variable power-of-two step, auto-expanding universe, compaction | **required** |
| 2 | Pattern I/O: RLE (with rule), plaintext, Macrocell read+write, built-in library | **required** |
| 3 | Reference naive simulator + differential `verify` command (random soups × rules × step sizes) | **required** |
| 4 | Analyzer: period, displacement, speed, still/oscillator/spaceship/dies/growth classification, population at any generation, bounding box, growth-rate fit | **required** |
| 5 | Soup census: random soups to ash, component extraction, named-object tally | stretch |
| 6 | PNG renderer with level-of-detail zoom-out from node populations | stretch |
| 7 | Self-contained HTML report (SVG pattern snapshots + log-log population curve), checked in headless Chromium | stretch |
