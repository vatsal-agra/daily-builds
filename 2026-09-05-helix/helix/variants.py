"""Pileup construction and simple SNP calling from reads placed against a
reference genome via the FM-index seed-and-vote placement in `fmindex.py`.

Scope note: `helix.seq.simulate_reads` models substitution-only sequencing
error (no indels), so once a read's start position is known, comparing it
against the reference base-by-base at that fixed offset is a faithful model
of the data — no CIGAR-aware realignment is needed to call SNPs correctly.
Indel calling is intentionally out of scope for this module (see PLAN.md /
README for the reasoning); `n_indel_suspected` on PileupSummary flags reads
whose seed votes disagree with each other (a real signature of an
indel-carrying read) so that limitation is visible rather than silently
swallowed.

Pure Python 3 stdlib only.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from helix.fmindex import FMIndex, place_read_by_seeds


class VariantError(ValueError):
    pass


@dataclass
class PileupColumn:
    position: int
    ref_base: str
    base_counts: Counter
    depth: int


@dataclass
class Variant:
    position: int
    ref_base: str
    alt_base: str
    ref_count: int
    alt_count: int
    depth: int
    allele_frequency: float

    def __str__(self) -> str:
        return (
            f"{self.position}\t{self.ref_base}>{self.alt_base}\t"
            f"AF={self.allele_frequency:.2f}\tDP={self.depth}\t"
            f"(ref={self.ref_count},alt={self.alt_count})"
        )


@dataclass
class PlacementSummary:
    n_reads: int
    n_placed: int
    n_unplaced: int
    n_ambiguous_votes: int  # reads whose seeds disagreed on start position


def place_reads(
    index: FMIndex, reads: list[str], *, seed_length: int = 20,
) -> tuple[list[tuple[int, str]], PlacementSummary]:
    """Place each read against the reference via seed-and-vote (see
    fmindex.place_read_by_seeds). Returns (placed, summary) where placed is
    a list of (start_position, sequence) for every read that placed."""
    if seed_length < 1:
        raise VariantError("seed_length must be >= 1")
    placed: list[tuple[int, str]] = []
    n_unplaced = 0
    n_ambiguous = 0
    for read in reads:
        votes: Counter[int] = Counter()
        for offset in range(0, len(read) - seed_length + 1, seed_length):
            seed = read[offset:offset + seed_length]
            for pos in index.search(seed):
                votes[pos - offset] += 1
        if not votes:
            n_unplaced += 1
            continue
        if len(votes) > 1:
            n_ambiguous += 1
        start = votes.most_common(1)[0][0]
        if 0 <= start <= len(index.reference) - len(read):
            placed.append((start, read))
        else:
            n_unplaced += 1
    summary = PlacementSummary(
        n_reads=len(reads), n_placed=len(placed),
        n_unplaced=n_unplaced, n_ambiguous_votes=n_ambiguous,
    )
    return placed, summary


def build_pileup(reference: str, placed_reads: list[tuple[int, str]]) -> list[PileupColumn]:
    """Column-wise base counts of `placed_reads` (each a (start, sequence)
    pair, already 1:1 with the reference at that offset) against `reference`."""
    if not reference:
        raise VariantError("reference must be non-empty")
    counts = [Counter() for _ in range(len(reference))]
    for start, seq in placed_reads:
        for i, base in enumerate(seq):
            pos = start + i
            if 0 <= pos < len(reference):
                counts[pos][base] += 1
    return [
        PileupColumn(pos, reference[pos], counts[pos], sum(counts[pos].values()))
        for pos in range(len(reference))
    ]


def call_variants(
    pileup: list[PileupColumn], *, min_depth: int = 4, min_allele_frequency: float = 0.5,
) -> list[Variant]:
    """Call a SNP at any column where the majority base differs from the
    reference with depth and allele-frequency support above threshold. A
    deliberately simple majority-vote caller — real callers (e.g. a proper
    Bayesian genotype likelihood model) are out of scope here, but the
    threshold logic is real and independently checkable against the raw
    counts on every call it makes."""
    if min_depth < 1:
        raise VariantError("min_depth must be >= 1")
    if not (0 < min_allele_frequency <= 1.0):
        raise VariantError("min_allele_frequency must be in (0, 1]")
    variants = []
    for col in pileup:
        if col.depth < min_depth or not col.base_counts:
            continue
        top_base, top_count = col.base_counts.most_common(1)[0]
        if top_base == col.ref_base:
            continue
        af = top_count / col.depth
        if af >= min_allele_frequency:
            variants.append(Variant(
                position=col.position, ref_base=col.ref_base, alt_base=top_base,
                ref_count=col.base_counts.get(col.ref_base, 0),
                alt_count=top_count, depth=col.depth, allele_frequency=af,
            ))
    return variants


def call_variants_from_reads(
    reference: str, index: FMIndex, reads: list[str], *,
    seed_length: int = 20, min_depth: int = 4, min_allele_frequency: float = 0.5,
) -> tuple[list[Variant], PlacementSummary]:
    """End-to-end convenience: place reads, build a pileup, call variants."""
    placed, summary = place_reads(index, reads, seed_length=seed_length)
    pileup = build_pileup(reference, placed)
    variants = call_variants(pileup, min_depth=min_depth, min_allele_frequency=min_allele_frequency)
    return variants, summary


def apply_variants(reference: str, edits: list[tuple[int, str]]) -> str:
    """Build a mutated ("sample") genome by substituting single bases of
    `reference` at the given (0-based position, new_base) pairs — used to
    construct ground truth for variant-calling tests/demos."""
    bases = list(reference)
    for pos, new_base in edits:
        if not (0 <= pos < len(bases)):
            raise VariantError(f"edit position {pos} out of range")
        bases[pos] = new_base
    return "".join(bases)
