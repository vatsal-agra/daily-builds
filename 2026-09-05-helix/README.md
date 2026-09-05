# Helix

*Status: Phase 4 (stretch + polish) complete — both planned stretch features
shipped (variant calling, interactive HTML visualizers), 3 more issues found
and fixed during polish. See PLAN.md for the full plan, REVIEW.md for every
issue found (Phase 3 + Phase 4) and how it was fixed.*

A from-scratch computational biology toolkit in pure Python 3 (stdlib only,
no numpy/biopython/any external dependency): pairwise sequence alignment,
phylogenetic tree reconstruction, de novo genome assembly, an FM-index
short-read aligner, and a variant caller — the algorithms behind real
sequence-analysis pipelines, built from first principles.

## What's implemented

**Required:**
- **`helix/seq.py`** — FASTA/FASTQ parsing and writing, reverse complement,
  transcription/translation, GC content, and a seeded synthetic-genome +
  read simulator (with a configurable per-base substitution error rate and
  optional reverse-strand sampling).
- **`helix/align.py`** — Needleman-Wunsch (global, linear gap) and Gotoh's
  algorithm (affine-gap global **and** local/Smith-Waterman alignment via
  three coupled DP planes), full traceback to aligned strings + a CIGAR
  string, plain match/mismatch or BLOSUM62 scoring.
- **`helix/phylo.py`** — pairwise distance matrices (raw p-distance or
  Jukes-Cantor corrected) from real alignments, UPGMA and Neighbor-Joining
  tree construction, Newick serialization.
- **`helix/assembly.py`** — de novo genome assembly via de Bruijn graphs:
  k-mer graph construction, coverage-depth filtering + genomic copy-number
  normalization, tip clipping, bubble popping, and Eulerian-path contig
  assembly (Hierholzer's algorithm), with an explicit Eulerian-path
  existence-theorem check and a unitig-extraction fallback for anything that
  doesn't satisfy it.
- **`helix/fmindex.py`** — a real FM-index: prefix-doubling suffix array
  construction, Burrows-Wheeler Transform (with an independent LF-mapping
  inverse proving losslessness), checkpointed rank/occurrence tables, and
  exact backward-search read alignment, plus seed-and-vote placement for
  reads carrying scattered mismatches.

**Stretch (both shipped):**
- **`helix/variants.py`** — pileup construction from FM-index-placed reads
  and a real majority-vote SNP caller; a full resequencing pipeline
  (reference → mutated sample genome → simulated reads → placement →
  pileup → variant calls) recovers injected SNPs exactly with zero false
  positives/negatives in testing.
- **`helix/viz.py`** — four self-contained SVG visualizations (a real DP
  traceback matrix for alignment, a rectangular phylogenetic dendrogram, a
  compressed de Bruijn assembly graph showing real tips/branch points, and
  an IGV-style genome-browser pileup view with variant markers) wrapped in
  one small tabbed HTML report — no build step, no CDN, ~40 lines of
  vanilla JS, screenshot-verified in headless Chromium with zero console
  errors.

**`helix/cli.py`** — the `helix` command-line tool: `align`, `phylo`,
`assemble`, `index`, `search`, `simulate`, `callvariants`, `viz`, and `demo`
(a scripted walkthrough exercising every required + stretch feature
end-to-end).

## Try it

```
python3 -m helix.cli demo
python3 -m helix.cli align --a GATTACA --b GATCACA --mode global
python3 -m helix.cli assemble --genome-length 2000 --n-reads 6000 --k 25
python3 -m helix.cli search --pattern ACGTAC --genome-length 2000
python3 -m helix.cli callvariants --genome-length 3000 --n-snps 5
python3 -m helix.cli viz --out report.html
```

## Tests

```
python3 -m unittest discover -s tests
```

152 unit/property/fuzz/differential/CLI tests, all green — including a
dedicated regression test for every issue found in the adversarial review
(REVIEW.md).

See `PLAN.md` for the full concept, architecture, and feature list, and
`REVIEW.md` for the full adversarial review (Phase 3 + Phase 4).
