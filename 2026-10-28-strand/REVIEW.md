# Adversarial review (Phase 3)

Method: attack the Phase-2 build as a hostile reviewer — feed it malformed files, degenerate genomes
(poly-A, dinucleotide repeats, N-runs), hostile simulator settings (6× error rate, 1.3 % variant rate,
50 % repeats, 250-bp reads, 1 chromosome of 5 kb, 5 Mb genome), and cross-check every output against
the simulator's truth. Each finding below was reproduced before being fixed; "evidence" is what I saw.

## Findings (all fixed)

| # | Severity | Finding | Evidence | Fix |
|---|----------|---------|----------|-----|
| 1 | **high** | Homozygous indels were genotyped **heterozygous**. Reference-allele support was "depth at the anchor base", which counts reads that were soft-clipped or end right at the indel — they say nothing about the reference allele. | 23 of 265 true indels mis-genotyped (indel GT concordance 0.921); AD like `12,30` for a true `1/1`. | Ref support now requires one unbroken aligned block covering the event ± 5 bp (second pass over the alignments, sorted event table + binary search). Concordance → 0.981. DP/AD now report only informative reads. Regression test `diploid_100kb_pipeline_meets_accuracy_floor` (needs ≥ 0.93). |
| 2 | **high** | Reads hanging off the end of a contig were **unmapped**: the end-to-end alignment is impossible inside the clipped window, and `?` propagated `None` for the whole read before the local alignment was tried. Found by my own soft-clip unit test failing. | `read_overhanging_reference_end_is_soft_clipped` panicked on `unwrap()` of `None`. | Semi-global failure now falls back to the local alignment (soft clip). |
| 3 | medium | A FASTQ record with an empty sequence broke the parser (blank lines were filtered globally, so `+` landed in the wrong slot). | `strand map r.fa e.fq` → "line 3: expected '+' separator". | Parser walks 4-line records; blank lines are skipped only *between* records. Unit tests incl. trailing blanks. |
| 4 | medium | `strand align ACGU ACGT` silently treated `U` (and any letter) as `A`, then reported 75 % identity. | Reproduced. | Strict `ACGTN` validation with a position-specific error (RNA hint for `U`); `N` now maps to code 0, which matches nothing — also fixed for reads (previously a latent `N→A` in the shared helper). |
| 5 | medium | Duplicate contig names in the reference were accepted, making SAM/VCF coordinates ambiguous. | `dup.fa` with two `>a` indexed fine. | Rejected with a clear error (unit test). |
| 6 | medium | `strand search` printed counts including hits that straddle two FASTA records, but listed none of them (e.g. `CG` across `a|b`: "1 occurrence(s)", no location). | Reproduced on a 2-record file. | Count and listing now come from the same boundary-filtered set. |
| 7 | medium | Index checksum covered only the BWT. A flipped bit in the SA samples or contig names loaded silently, and an out-of-range sample made `locate` return garbage. | Code review of `from_bytes`; hand-corrupted file. | Checksum covers BWT + samples + names, samples are range-checked, trailing bytes rejected. |
| 8 | medium | Ambiguous reference bases (N) were mapped to `A`. A 10-kb run of N therefore became a poly-A trap attracting every poly-A/low-complexity read at high MAPQ-ish confidence. | Reasoned from real assemblies, then confirmed the encoding in `to_codes`. | Ambiguous bases become a deterministic position-hashed pseudo-random base (BWA's approach); the caller still skips those sites. Unit test checks the base mix. |
| 9 | low | Indel error model: `repeat_copies(s, at + unit.len().min(0), …)` — a nonsense expression left from an edit — and the *deletion* case counted the deleted copy itself as a repeat copy, over-inflating ε. | Code review. | Rewritten; deletion uses `copies − 1`. |
| 10 | low | Fisher exact test recomputed `ln n!` in O(n) per term → O(n²) per site; a 60 k-deep pile-up with a skewed strand ratio would take minutes. | Complexity analysis. | Cached log-factorial table, O(n). |
| 11 | low | `usable()` closure in the caller mutated the stats counters and was called from three passes (double counting reads in later passes). | Code review. | Pure predicate; counters updated once in pass 1. |
| 12 | low | `eval-vcf` printed a genotype concordance of `0.0000` when there were no true positives, which reads as "all wrong". | Haploid/no-indel run. | Prints `-`. |
| 13 | low | SAM parser rejected secondary/supplementary records with `SEQ=*`, which every real aligner emits. | Reasoned from the SAM spec. | Accepted for flags 256/2048 only; a primary mapped record without SEQ is still an error. |
| 14 | low | Simulator: with several chromosomes the random split could produce a chromosome shorter than the read length (zero reads, or a panic in `below(0)`). Also an `unsafe` raw-pointer shortcut crept into `evaluate` and a dead `n_fam` variable remained. | Param sweep; code review. | Minimum chromosome length floor; `unsafe` removed; dead code removed. |
| 15 | perf | Perfect-match reads (≈ 70 % of a typical run) went through two banded DPs each. | 23 k reads/s on a 5 Mb genome. | Fast path when one seed spans the whole read; byte-identical SAM, 34.8 k reads/s. |

## Probed and found sound
* SA-IS vs naive sort on 400 random + periodic strings; FM `count/locate` vs naive scan for 5 sampling rates; inverse BWT at lengths 1, 2, 63, 64, 65.
* Gotoh aligner vs **exhaustive enumeration of every alignment path** for 500 random tiny pairs × 3 scorings × 3 modes (scores equal; traceback re-scored independently equals the DP score).
* Poly-A, `(CA)n` and mixed low-complexity genomes: no hangs, all MAPQ 0 (0.015 s for 2 000 reads).
* 5 Mb / 4 contigs: index 1.2 s, 250 k reads mapped in 8 s, 99.79 % of mapped reads at the true locus.
* Threads 1 vs 4 give identical placements; `--threads 0`, unknown options, missing args, unwritable output paths all exit 1/2 with a one-line message.
* 6× error rate: mapping accuracy 99.79 %, SNP precision 1.000.

## Known limits (deliberate, documented in README)
* **No local realignment.** Indels within ~10 bp of a read end get soft-clipped rather than aligned, so alt support is under-counted near them; a few true heterozygous indels in clean sequence end up `LowQual` (e.g. a 4-bp het deletion with 9 alt vs 22 ref reads).
* **Repeats.** Variants inside near-identical repeat copies are invisible (all covering reads have MAPQ < 20). With 8 % repeats ≈ 3 % of SNPs are lost this way; at 50 % repeats recall drops to 82 %.
* Single-end reads only; indels longer than the band (24) are reported as clipped half-alignments (no supplementary/chimeric records).
* One alternate allele per site; no MNP phasing; no read-group/BAM support.
* Reference length limited to 4 Gb by 32-bit sample positions (asserted).
