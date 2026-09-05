# Helix

*Status: Phase 3 (adversarial review) complete — 7 real issues found and
fixed (see REVIEW.md), all 4 required features still green. See PLAN.md for
the full plan.*

A from-scratch computational biology toolkit in pure Python 3 (stdlib only,
no numpy/biopython/any external dependency): pairwise sequence alignment,
phylogenetic tree reconstruction, de novo genome assembly, and an FM-index
short-read aligner — the algorithms behind real sequence-analysis pipelines,
built from first principles.

## What's implemented so far

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
- **`helix/cli.py`** — the `helix` command-line tool: `align`, `phylo`,
  `assemble`, `index`, `search`, `simulate`, and `demo` (a scripted
  walkthrough exercising all 4 required features end-to-end).

## Try it

```
python3 -m helix.cli demo
python3 -m helix.cli align --a GATTACA --b GATCACA --mode global
python3 -m helix.cli assemble --genome-length 2000 --n-reads 6000 --k 25
python3 -m helix.cli search --pattern ACGTAC --genome-length 2000
```

## Tests

```
python3 -m unittest discover -s tests
```

117 unit/property/fuzz/differential/CLI tests, all green — including a
dedicated regression test for every issue found in the adversarial review
(REVIEW.md).

See `PLAN.md` for the full concept, architecture, and feature list (including
the stretch features still to come), and `REVIEW.md` for the Phase 3
adversarial review.
