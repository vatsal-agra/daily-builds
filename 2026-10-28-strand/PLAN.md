# Strand — Plan

## Concept
A from-scratch **genomics toolkit** in Rust (zero dependencies): the three computational pillars of
sequencing analysis in one binary.

1. **Align** short reads to a reference (BWA-style): suffix array (SA-IS) → BWT → FM-index with
   sampled suffix array, exact seeds by backward search, seed voting on diagonals, banded
   affine-gap extension, CIGAR, MAPQ, SAM output.
2. **Call variants** from the alignments: pileup, SNP/indel calling with a binomial genotype
   likelihood, VCF output, scored against the simulator's truth set (precision / recall / F1).
3. **Assemble** reads with no reference: k-mer counting, de Bruijn graph, tip clipping, bubble
   popping, unitig/contig extraction, N50 — then evaluated by aligning the contigs back.

A seeded **simulator** produces a reference genome (with repeat families), a diploid-free "sample"
with known SNPs/indels, and FASTQ reads with realistic position-dependent errors, so every stage
has ground truth to be graded against. No placeholder data anywhere.

## Why it's interesting
Bioinformatics is new to this repo. The FM-index is a beautiful data structure (compression +
search in one), SA-IS is a famous linear-time algorithm, and the whole pipeline is end-to-end
checkable: simulate → align → call → compare with truth.

## Architecture (src/)
- `rng.rs` splitmix/xoshiro PRNG, normal/poisson helpers
- `seq.rs` 2-bit DNA codes, revcomp, FASTA/FASTQ read/write
- `sais.rs` SA-IS suffix array (+ naive oracle in tests)
- `fm.rs` BWT, occ checkpoints, backward search, locate via sampled SA, (de)serialization
- `align.rs` affine-gap global / local / semi-global / banded, traceback, CIGAR
- `mapper.rs` seed → vote → extend → MAPQ, both strands, SAM writer/parser
- `pileup.rs`, `caller.rs` pileup and SNP/indel calls, VCF I/O, truth comparison
- `sim.rs` genome / mutation / read simulation
- `dbg.rs` k-mer counting, graph, cleaning, unitigs; `asmeval.rs` contig scoring
- `mash.rs` MinHash sketch distances; `report.rs` HTML report
- `main.rs` CLI

## Features
| # | Feature | Status |
|---|---------|--------|
| 1 | FM-index: SA-IS, BWT, backward search count/locate, index save/load | **required** |
| 2 | Affine-gap aligner (global/local/semi-global, banded) with CIGAR | **required** |
| 3 | Seed-and-extend read mapper, both strands, MAPQ, SAM output | **required** |
| 4 | Variant caller (SNP + indel) with VCF output and truth-set evaluation | **required** |
| 5 | De Bruijn assembler: tip clipping, bubble popping, contigs, N50, eval vs reference | stretch |
| 6 | Read/genome/variant simulator with ground truth | **supports all**, shipped in core |
| 7 | MinHash genome distance (Mash-style) + UPGMA tree | stretch |
| 8 | Self-contained HTML report (coverage track, variants, assembly stats) | stretch |

(Features 1–4 required; 5, 7, 8 stretch; the simulator is infrastructure built in phase 2.)
