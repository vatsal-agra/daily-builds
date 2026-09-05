# Helix

A from-scratch computational biology toolkit in pure Python 3 — no numpy,
no biopython, no external dependency of any kind. Pairwise sequence
alignment, phylogenetic tree reconstruction, de novo genome assembly, an
FM-index short-read aligner, and a variant caller, plus a small interactive
HTML visualizer for all of it — the algorithms a real short-read sequencing
pipeline is built on, implemented from first principles and wired together
into one realistic workflow: a reference genome is fragmented into noisy
simulated reads, which are then either assembled back into contigs with no
reference, or aligned back to the reference and used to call variants.

## What it is

Four required subsystems, each a genuinely different flavor of "hard from
scratch":

1. **Pairwise alignment** (`helix/align.py`) — Needleman-Wunsch (global,
   linear gap) and Gotoh's algorithm (affine-gap global **and**
   local/Smith-Waterman alignment via three coupled DP planes), full
   traceback to aligned strings + a CIGAR string, plain match/mismatch or
   BLOSUM62 scoring.
2. **Phylogenetics** (`helix/phylo.py`) — pairwise distance matrices (raw
   p-distance or Jukes-Cantor corrected) computed from real Gotoh
   alignments, UPGMA (average-linkage) and Neighbor-Joining tree
   construction, Newick serialization.
3. **De novo genome assembly** (`helix/assembly.py`) — de Bruijn graph
   construction from k-mers, coverage-depth filtering, genomic
   copy-number normalization (separating sequencing-depth redundancy from
   real repeat structure), tip clipping, bubble popping, and Eulerian-path
   contig assembly (Hierholzer's algorithm) behind an explicit
   existence-theorem check, with a unitig-extraction fallback for
   anything that doesn't satisfy it.
4. **FM-index short-read alignment** (`helix/fmindex.py`) — a real
   suffix array (prefix-doubling construction), Burrows-Wheeler Transform
   (with an independent LF-mapping inverse proving losslessness),
   checkpointed rank/occurrence tables, exact backward-search alignment,
   and seed-and-vote placement for reads carrying scattered mismatches.

Plus two stretch features, both shipped:

5. **Variant calling** (`helix/variants.py`) — pileup construction from
   FM-index-placed reads and a real majority-vote SNP caller. A full
   resequencing pipeline (reference → mutated sample genome → simulated
   reads → seed-and-vote placement → pileup → variant calls) recovers
   injected SNPs exactly, with zero false positives or negatives in
   testing.
6. **Interactive HTML visualizers** (`helix/viz.py`) — four self-contained
   SVG visualizations in one small tabbed report, no build step, no CDN:
   a real DP traceback matrix for alignment (the highlighted path is the
   actual traceback, not redrawn from the answer), a rectangular
   phylogenetic dendrogram, a compressed de Bruijn assembly graph showing
   real tips and branch points, and an IGV-style genome-browser pileup
   view with variant markers.

## How to run it

```bash
# every required + stretch feature, scripted end-to-end
python3 -m helix.cli demo

# individual subcommands
python3 -m helix.cli align --a GATTACA --b GATCACA --mode global
python3 -m helix.cli align --a AAAGATTACAAAA --b GGGGATTACAGGGG --mode local
python3 -m helix.cli phylo --fasta myseqs.fasta --method nj
python3 -m helix.cli assemble --genome-length 2000 --n-reads 6000 --k 25
python3 -m helix.cli index --genome-length 2000 --seed 1
python3 -m helix.cli search --pattern ACGTAC --genome-length 2000
python3 -m helix.cli simulate --genome-length 2000 --n-reads 500 --out-fasta genome.fasta
python3 -m helix.cli callvariants --genome-length 3000 --n-snps 5
python3 -m helix.cli viz --out report.html    # then open report.html in a browser

# full verification: test suite + every CLI path + a headless-browser
# console-error check on the generated report
./demo.sh

# just the tests (152, unit/property/fuzz/differential/CLI)
python3 -m unittest discover -s tests
```

No install step — pure Python 3 stdlib. `helix viz`'s output is a single
static HTML file; open it directly in any browser.

## Full feature list

**Required (4/4 shipped):**
- Pairwise alignment: Needleman-Wunsch + Gotoh affine-gap global/local,
  traceback, CIGAR, BLOSUM62.
- Phylogenetics: UPGMA + Neighbor-Joining from real alignment-derived
  distances, Newick output.
- De novo assembly: de Bruijn graph, coverage filtering + copy-number
  normalization, tip clipping, bubble popping, Eulerian-path assembly with
  an explicit existence check.
- FM-index read alignment: suffix array, BWT (+ independent inverse),
  checkpointed rank tables, exact search, seed-and-vote mismatch-tolerant
  placement.

**Stretch (2/2 shipped):**
- Variant calling: pileup + majority-vote SNP caller, ground-truth
  verified end-to-end.
- Interactive HTML visualizers: alignment matrix, dendrogram, assembly
  graph, genome-browser pileup — one tabbed report, screenshot-verified in
  headless Chromium with zero console errors.

**Also:** a full `helix` CLI (`align/phylo/assemble/index/search/simulate/
callvariants/viz/demo`), a seeded synthetic-genome + read simulator with a
configurable substitution-error model, and 152 tests (unit, property,
differential-vs-independent-oracle, and fuzz) plus `demo.sh` (the test
suite + every CLI path + a headless-browser check, run green 3 consecutive
times).

## Why I chose this today

This repo has built an enormous amount from scratch — nine transformers,
five CDCL SAT solvers, four Monte Carlo path tracers, three version-control
systems, three full-text search engines, two physics engines, two
compression toolkits, two crypto suites, a CPU pipeline simulator, a
SPICE-like analog circuit simulator, a chess engine, a roguelike, a market
matching engine, a robot SLAM stack — but never anything that touches
biological sequence data. Bioinformatics is a genuinely different flavor of
"hard from scratch": it's string dynamic programming (alignment) plus graph
theory (de Bruijn assembly is literally an Eulerian-path problem) plus
classic data structures (suffix arrays / BWT / FM-index) plus a
statistics-flavored decision problem (variant calling) — and it comes with
exact, hand-checkable ground truth that past builds have thrived on:
textbook alignment scores, an Eulerian-path existence theorem, the
ultrametric property a UPGMA tree's cophenetic distances must satisfy, a
losslessly-invertible BWT, and (for assembly/variant-calling) a simulated
ground truth you can check the pipeline's output against exactly. That
combination — new domain, hard algorithms, checkable answers — is exactly
what has made past builds strong here, and it hadn't been spent yet.

## Adversarial review — what got caught

Ten real issues were found and fixed across Phase 3 (core review) and
Phase 4 (stretch/polish), each with a dedicated regression test — full
write-ups in `REVIEW.md`. The two worth calling out:

- **`FMIndex(checkpoint_interval<0)` didn't crash — it silently returned
  wrong search results.** A pattern present at position 20 came back as
  "not found," no error, no warning. Found by testing the FM-index against
  degenerate constructor arguments, not just valid ones. This is the worst
  class of bug a from-scratch aligner can have, and it shipped in Phase 2
  before this review caught it.
- **De Bruijn graph edge weights initially conflated sequencing-depth
  redundancy with genomic repeat copy number**, causing the Eulerian-path
  existence check to fail on almost every real assembly (a 27,994-contig
  output from a 2,000bp genome). Fixed by explicitly normalizing raw
  k-mer counts to an estimated copy number before using them for anything
  topological — the fix that actually makes the Eulerian-path formulation
  correct, not just a workaround.

## Where a human could take this next

- **Bidirected de Bruijn graphs** for real double-stranded read sets
  (documented as an upfront scope decision — see `helix/assembly.py`'s
  module docstring) would let assembly handle mixed-strand reads, the
  realistic sequencing scenario.
- **Approximate (edit-distance-bounded) FM-index search** — currently
  exact-only, with mismatch tolerance handled separately via
  seed-and-vote; a real BWA-style FM-index-driven inexact search (with
  backtracking on mismatch budget) would unify the two.
- **Indel-aware variant calling** — the current caller assumes
  substitution-only reads (matching the read simulator's error model);
  extending both to model insertions/deletions would need CIGAR-aware
  pileup construction.
- **Multiple sequence alignment** (progressive alignment via a guide
  tree) would connect `align.py` and `phylo.py` directly, and unlock
  proper multi-sequence phylogenetics instead of independent pairwise
  distances.
- **A proper genotype-likelihood model** (Bayesian, like a real variant
  caller) in place of the current majority-vote threshold, for calling
  heterozygous variants with statistical confidence rather than a hard
  allele-frequency cutoff.
