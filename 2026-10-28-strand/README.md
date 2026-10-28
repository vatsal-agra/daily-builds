# Strand

A from-scratch genomics toolkit in Rust (no dependencies): FM-index read aligner, variant caller and
(coming) de Bruijn assembler, all graded against a built-in ground-truth simulator.

**Status — Phase 4 (stretch + polish) complete.** The four required features work end to end:

1. **FM-index** — SA-IS suffix array → BWT → rank checkpoints + sampled SA; `count`/`locate`, inverse BWT, save/load with checksum (`strand index`, `strand search`).
2. **Affine-gap aligner** — global / local / semi-global with optional band, traceback, CIGAR (`strand align`); verified against exhaustive enumeration.
3. **Seed-and-extend read mapper** — exact seeds by backward search, diagonal clustering, banded extension, soft clipping, MAPQ, multithreaded, SAM out (`strand map`).
4. **Variant caller** — pileup + Bayesian genotype model for SNPs and indels, left-normalised, VCF out, scored against truth (`strand call`, `strand eval-vcf`).

Stretch features shipped:

5. **De Bruijn assembler** — canonical k-mer counting, automatic error cut-off from the k-mer spectrum, unitig graph, tip clipping, bubble popping (`strand assemble`), scored by a QUAST-style evaluator (`strand eval-asm`).
6. **MinHash genome distances + UPGMA tree** (`strand mash`).
7. **Self-contained HTML report** — coverage tracks with TP/FP/FN markers, MAPQ accuracy, assembly stats (`strand report`, also written by `strand demo`).

Plus the **simulator** (`strand simulate`) that makes the truth set, and `strand demo` which runs the whole pipeline.

```
$ strand demo
mapped 60000/60000 reads, MAPQ>=20: 95.6%      accuracy 99.86% (MAPQ>=20: 100.000%)
SNP     TP 225  FP 0  FN 7    precision 1.000  recall 0.970
indel   TP  38  FP 0  FN 2    precision 1.000  recall 0.950
```

See PLAN.md for the roadmap; the full README arrives in Phase 6.
