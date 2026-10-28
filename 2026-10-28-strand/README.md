# Strand

**A from-scratch genomics toolkit in Rust — zero dependencies.** It does the three jobs of sequence
analysis in one binary: **align** short reads with an FM-index, **call variants** from the alignments,
and **assemble** a genome from reads with no reference — and it grades itself against a built-in
ground-truth simulator, so every number it prints can be checked.

```
$ strand demo
== 3. map ==
mapped 60001/60001 reads (100.00%), MAPQ>=20: 94.81%      accuracy 99.55% (MAPQ>=20: 100.000%)
== 4. call variants ==
class       TP     FP     FN  precision   recall       F1  GT-conc
SNP        259      0     13     1.0000   0.9522   0.9755   1.0000
indel       34      0      0     1.0000   1.0000   1.0000   1.0000
== 5. assemble ==
contigs 61   total 191076 bp   N50 5692      genome fraction 95.26%   misassemblies 0
```

About 6,400 lines of Rust, 85 unit + 6 CLI + 4 end-to-end tests, a mutation harness and a
headless-browser check of the HTML report.

## Run it

Requires Rust ≥ 1.75 (tested on 1.97). Node + Playwright are optional (browser check only).

```bash
cargo build --release
./target/release/strand demo                    # whole pipeline on a fresh simulation, writes report.html
./verify.sh                                     # everything: tests, scripted demo, browser check, mutants
./verify.sh --quick                             # same without the ~2 min mutation harness

# the pieces
strand simulate -o run --length 500000 --coverage 30 --ploidy 2     # ref.fa reads.fq truth.vcf sample.fa
strand index   run/ref.fa -o run/ref.fm                              # FM-index, saved with a checksum
strand search  run/ref.fm GATTACAGATTACA --both-strands              # exact count + locations
strand align   GATTACAGATTACA GATTACAGGATTACA --mode global          # CIGAR + pretty alignment
strand map     run/ref.fm run/reads.fq -o run/aln.sam --threads 4
strand eval-map run/aln.sam                                          # accuracy by MAPQ (simulated names)
strand call    run/ref.fa run/aln.sam -o run/calls.vcf --ploidy 2
strand eval-vcf run/ref.fa run/truth.vcf run/calls.vcf --show 10     # precision / recall / genotype concordance
strand assemble run/reads.fq -o run/contigs.fa --spectrum
strand eval-asm run/sample.fa run/contigs.fa                         # truth must be the sample, not the reference
strand mash a.fa b.fa c.fa                                           # distance matrix + UPGMA Newick tree
strand report --ref run/ref.fa --sam run/aln.sam --calls run/calls.vcf --truth run/truth.vcf -o run/report.html
```

`strand help` lists every option. Exit status is 0 on success, 1 on a runtime error, 2 on a usage error;
messages are one line and name the file or option at fault. All commands accept real FASTA/FASTQ/SAM/VCF,
so you can point them at your own data (single-end reads, haploid or diploid, small genomes).

## Features

| # | Feature | Where |
|---|---------|-------|
| 1 | **FM-index.** SA-IS linear-time suffix array → BWT → rank checkpoints + sampled suffix array; `count`, `locate`, inverse-BWT proof of losslessness, save/load with a whole-file checksum | `sais.rs`, `fm.rs` |
| 2 | **Affine-gap aligner** (Gotoh): global, local, semi-global, optional diagonal band, leftmost gap placement, CIGAR / `=X` ops, pretty printer. Verified against exhaustive path enumeration | `align.rs` |
| 3 | **Read mapper.** Backward-search seeds → diagonal clustering → banded extension, both strands, soft clipping vs full-length trade-off (BWA-style), MAPQ from best vs second-best locus, repeat detection, exact-match fast path, multithreaded, coordinate-sorted SAM | `mapper.rs` |
| 4 | **Variant caller.** Pileup + Bayesian genotype posterior (haploid or diploid), SNPs and indels, left-normalised, STR-aware indel error model, flank-aware reference support, Fisher strand-bias filter, VCF out | `caller.rs`, `vcf.rs` |
| 5 | **De Bruijn assembler.** Canonical k-mer counting, auto error cut-off from the k-mer spectrum, unitig graph, tip clipping, bubble popping (aligner-verified identity), N50/L50 | `dbg.rs` |
| 6 | **Assembly evaluator** (QUAST-lite): genome fraction, misassemblies by chained chunk mapping, mismatch / indel rate per 100 kb, NGA50 | `asmeval.rs` |
| 7 | **MinHash distances + UPGMA** (Mash distance, Newick tree) | `mash.rs` |
| 8 | **Self-contained HTML report**: coverage tracks with TP / FP / missed markers, MAPQ accuracy, assembly panels; inline SVG, light/dark, phone-friendly, no scripts, no network | `report.rs` |
| 9 | **Simulator** with ground truth: repeat families, microsatellites, SNPs/indels (het/hom, haploid/diploid), Illumina-like position-dependent errors with honest quality strings | `sim.rs` |

## How well does it work?

Measured by `verify.sh` / the review runs (simulated data, so truth is exact):

| scenario | result |
|---|---|
| 200 kb diploid, 30×, 100-bp reads | 99.6 % of mapped reads at true locus (100.000 % at MAPQ ≥ 20); SNP precision 1.000 / recall 0.95; indel precision 1.000 / recall ≥ 0.95; genotype concordance ≥ 0.98 |
| 5 Mb, 4 contigs, 250 k reads | index 1.2 s (1.5 B/base on disk), mapping ~35 k reads/s on 4 threads |
| 6× error rate | mapping accuracy 99.8 %, SNP precision 1.000 |
| 1.3 % variant density | SNP F1 0.985, indel F1 0.966 |
| 50 % repeat content | recall falls to 0.82 (variants in near-identical copies are unmappable — honestly reported) |
| 300 kb haploid assembly | 95 % genome fraction, 0 misassemblies, ≈ 2 mismatches / 100 kb |

## Why I built this today

Every earlier build in this repo is deterministic or logical (compilers, solvers, protocols,
engines) — none touched **bioinformatics**, and none had a result you could grade against a
simulated truth. Genomics has an unusually satisfying shape for from-scratch work: the FM-index is a
beautiful data structure (compression and search at once), SA-IS is one of the great linear-time
algorithms, and the pipeline is end-to-end checkable — simulate → align → call → compare with the
truth the simulator wrote down. It also has real traps (left-normalising indels, clipped reads
counted as reference evidence, N-runs becoming poly-A attractors) that an adversarial review could
genuinely find — see REVIEW.md (20 findings fixed).

## Design notes

* `PLAN.md` — the concept and architecture; `REVIEW.md` — two adversarial reviews with evidence.
* Aligner scoring defaults are BWA-MEM's (+1 / −4 / gap −6 −1·len, clip penalty 5).
* Genotype model: per-base error from Phred; priors 1e-3 het, 5e-4 hom-alt; QUAL = Phred P(ref/ref | data).
* Everything is deterministic given a seed (`simulate --seed`), including multithreaded mapping.

## Limits (documented, not hidden)

No local realignment (indels near read ends are clipped, so a few heterozygous indels end up `LowQual`);
variants inside near-identical repeats are not callable at MAPQ ≥ 20; single-end reads only; indels longer
than the 24-bp band become clipped half-alignments; one alternate allele per site; assembler is single-k
(k ≤ 31) without scaffolding, so repeats and microsatellites longer than a read break contigs; genomes up
to 4 Gb by construction but only tested to 5 Mb.

## Where a human could take this next

1. **Local reassembly around candidate indels** (as GATK HaplotypeCaller does) — the single biggest accuracy win left.
2. **Paired-end reads**: insert-size aware mapping rescues repeats; scaffolding links contigs the DBG cannot join.
3. **Bidirectional FM-index** (or r-index) for true SMEM seeding; bit-packed occ tables for 10× less memory/cache pressure.
4. **Multi-k assembly** (IDBA/SPAdes style) and coverage-aware repeat resolution.
5. **BAM/CRAM and bgzipped VCF I/O**, read groups, and a real-data benchmark (e.g. E. coli, lambda phage, GIAB chr20 slice).
6. Population tools on top of the sketches: tree building with neighbour-joining, containment search against a sketch database.
