# Helix — a from-scratch computational biology toolkit

## The concept

Every algorithm a real short-read sequencing pipeline is built on, implemented
from first principles in pure Python: pairwise sequence alignment, phylogenetic
tree reconstruction, de novo genome assembly, and a suffix-array/BWT read
aligner (the actual algorithm inside BWA/Bowtie). Wired together into one
realistic pipeline: a reference genome is fragmented into noisy simulated
reads, which are then either (a) assembled back into contigs with no
reference, or (b) aligned back to the reference with the FM-index and used to
call variants — mirroring the two dominant real workflows in genomics
(de novo assembly vs. resequencing).

## Why this is interesting

This repo has built an enormous amount from scratch — nine transformers, five
CDCL SAT solvers, four path tracers, three version-control systems, three
full-text search engines, two physics engines, two compression toolkits, two
crypto suites, a CPU pipeline simulator, a SPICE-like circuit simulator, a
chess engine, a roguelike, a market matching engine, a robot SLAM stack — but
never anything that touches biological sequence data. Bioinformatics is a
genuinely different flavor of "hard from scratch": it's string dynamic
programming (alignment) plus graph theory (de Bruijn assembly is literally an
Eulerian-path problem) plus classic data structures (suffix arrays / BWT /
FM-index) plus a statistics-flavored decision problem (variant calling) — and
uniquely, it comes with exact, hand-checkable ground truth: textbook alignment
scores, an Eulerian-path existence theorem, an ultrametric property UPGMA
trees must satisfy, and a losslessly-invertible BWT. That combination of
"genuinely new domain" + "exact ground truth to verify against" is exactly
what has made past builds strong, and it hasn't been spent yet.

## Architecture

```
helix/
  seq.py       — DNA/protein sequence core: FASTA/FASTQ parse+write, reverse
                 complement, transcription/translation (codon table),
                 GC content, a seeded synthetic-genome + read generator with
                 a configurable per-base substitution error model.
  align.py     — Needleman-Wunsch (global, linear gap) and Gotoh's algorithm
                 (affine-gap global AND local/Smith-Waterman via 3 DP planes),
                 configurable match/mismatch or a real substitution matrix
                 (BLOSUM62 subset for protein), full traceback -> aligned
                 strings + CIGAR string.
  phylo.py     — pairwise distance matrix (p-distance, Jukes-Cantor
                 correction) from a multiple alignment; UPGMA and
                 Neighbor-Joining tree construction; Newick serialization;
                 tree-shape utilities (leaf sets, total branch length).
  assembly.py  — k-mer extraction, de Bruijn graph construction (nodes =
                 (k-1)-mers, edges = k-mers), tip-clipping + simple bubble
                 popping, Eulerian-path assembly (Hierholzer's algorithm) with
                 a real existence check (in/out-degree balance +
                 connectivity), contig extraction back to sequence.
  fmindex.py   — prefix-doubling O(n log^2 n) suffix array construction,
                 BWT via the suffix array (with a sentinel), the BWT's exact
                 inverse (LF-mapping) as its own correctness proof, an
                 FM-index (occurrence/rank tables with checkpointing, C[]
                 array) supporting exact backward-search alignment of reads
                 against a reference genome.
  variants.py  — pileup construction from a set of reference-aligned reads,
                 simple SNP calling (majority allele + minimum depth/purity
                 thresholds) and single-base indel flagging from CIGARs.
  cli.py       — `helix` CLI: align / phylo / assemble / index / search /
                 simulate / pileup / viz / demo subcommands.
viz/           — self-contained HTML/SVG/JS visualizers (no build step, no
                 CDN): alignment traceback matrix, phylogenetic dendrogram,
                 de Bruijn assembly graph, genome-browser pileup view.
tests/         — unit + property/differential tests per module.
demo.sh        — runs the test suite, then walks every CLI subcommand
                 end-to-end against real generated data.
```

## Feature list

**Required (core, must work end-to-end with zero stubs):**

1. **Pairwise alignment** — Needleman-Wunsch global alignment and Gotoh
   affine-gap Smith-Waterman local alignment, with real traceback producing
   an aligned pair of strings and a CIGAR string, verified against
   hand-computable textbook DP tables and a brute-force force-fill oracle.
2. **Phylogenetics** — UPGMA and Neighbor-Joining tree construction from a
   distance matrix derived from real pairwise alignments, serialized to
   Newick format, verified against hand-worked distance-matrix examples
   (UPGMA's ultrametric guarantee is a checkable invariant; NJ is checked
   against a from-scratch independent reimplementation of the same
   algorithm plus known textbook results).
3. **De novo genome assembly** — de Bruijn graph construction from k-mers,
   graph simplification (tip clipping), and Eulerian-path contig assembly,
   run end-to-end: a random synthetic reference genome -> simulated
   overlapping reads with sequencing errors -> assembled contigs, checked
   for correct reconstruction of the original sequence (or its reverse
   complement).
4. **FM-index short-read aligner** — a real suffix array + BWT + rank-table
   FM-index built over a reference genome, with exact backward-search
   alignment of reads, verified against naive substring search (`str.find`
   equivalent) across randomized fuzzing over many reference/read pairs.

**Stretch (2+, at least 1 must ship fully working):**

5. **Variant calling** — pileup construction from FM-index-aligned reads
   against the reference and a real (if simplified) SNP/indel caller.
6. **Interactive HTML visualizers** — alignment traceback-matrix viewer,
   phylogenetic dendrogram, de Bruijn assembly-graph viewer, and a
   genome-browser-style pileup view with variants highlighted — all
   self-contained single-file HTML/SVG/JS, no server, no build step.

## Verification strategy

- Alignment: brute-force DP-table cross-check + hand-worked textbook example
  (the classic GATTACA/GCATGCU-style cases) with known optimal scores.
- Phylogenetics: UPGMA ultrametric-distance invariant; NJ additivity recovery
  on a distance matrix constructed to be exactly tree-additive (must recover
  the exact known tree topology and branch lengths).
- Assembly: Eulerian-path existence theorem checked explicitly before
  attempting traversal; end-to-end reference-recovery check across many
  random seeds/genome lengths/error rates.
- FM-index: BWT invertibility round-trip (build BWT, invert it, must recover
  the exact original string with sentinel); search results differentially
  fuzzed against naive substring search across hundreds of random cases.
- Variant calling: seeded known-position mutations must be recovered from
  simulated re-sequencing reads.
