"""Sequence core: FASTA/FASTQ I/O, reverse complement, translation, GC
content, and a seeded synthetic-genome + read simulator.

Pure Python 3 stdlib only.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

COMPLEMENT = str.maketrans("ACGTNacgtn", "TGCANtgcan")

# The standard genetic code, DNA codon -> single-letter amino acid.
# '*' denotes a stop codon.
CODON_TABLE = {
    "TTT": "F", "TTC": "F", "TTA": "L", "TTG": "L",
    "CTT": "L", "CTC": "L", "CTA": "L", "CTG": "L",
    "ATT": "I", "ATC": "I", "ATA": "I", "ATG": "M",
    "GTT": "V", "GTC": "V", "GTA": "V", "GTG": "V",
    "TCT": "S", "TCC": "S", "TCA": "S", "TCG": "S",
    "CCT": "P", "CCC": "P", "CCA": "P", "CCG": "P",
    "ACT": "T", "ACC": "T", "ACA": "T", "ACG": "T",
    "GCT": "A", "GCC": "A", "GCA": "A", "GCG": "A",
    "TAT": "Y", "TAC": "Y", "TAA": "*", "TAG": "*",
    "CAT": "H", "CAC": "H", "CAA": "Q", "CAG": "Q",
    "AAT": "N", "AAC": "N", "AAA": "K", "AAG": "K",
    "GAT": "D", "GAC": "D", "GAA": "E", "GAG": "E",
    "TGT": "C", "TGC": "C", "TGA": "*", "TGG": "W",
    "CGT": "R", "CGC": "R", "CGA": "R", "CGG": "R",
    "AGT": "S", "AGC": "S", "AGA": "R", "AGG": "R",
    "GGT": "G", "GGC": "G", "GGA": "G", "GGG": "G",
}

DNA_ALPHABET = set("ACGTN")


class SequenceError(ValueError):
    """Raised on malformed FASTA/FASTQ input or invalid sequence data."""


@dataclass
class FastaRecord:
    header: str
    sequence: str


@dataclass
class FastqRecord:
    header: str
    sequence: str
    quality: str


def validate_dna(seq: str, *, name: str = "sequence") -> str:
    """Upper-case and validate a DNA string. Raises SequenceError on any
    character outside A/C/G/T/N (case-insensitive)."""
    if not seq:
        raise SequenceError(f"{name} is empty")
    up = seq.upper()
    bad = set(up) - DNA_ALPHABET
    if bad:
        raise SequenceError(
            f"{name} contains non-DNA characters: {sorted(bad)!r}"
        )
    return up


def reverse_complement(seq: str) -> str:
    """Reverse-complement a DNA sequence. Preserves case per-base."""
    return seq.translate(COMPLEMENT)[::-1]


def gc_content(seq: str) -> float:
    """Fraction of bases that are G or C (N excluded from the denominator)."""
    up = seq.upper()
    acgt = sum(up.count(b) for b in "ACGT")
    if acgt == 0:
        return 0.0
    gc = up.count("G") + up.count("C")
    return gc / acgt


def transcribe(dna: str) -> str:
    """DNA (coding strand) -> RNA: T -> U."""
    return dna.upper().replace("T", "U")


def translate(dna: str, *, to_stop: bool = True) -> str:
    """Translate a DNA coding sequence into a protein string using the
    standard genetic code. Trailing partial codons are ignored.

    If to_stop is True, translation halts at (and excludes) the first stop
    codon. Otherwise stop codons are emitted as '*'.
    """
    up = validate_dna(dna, name="coding sequence").replace("N", "")
    protein = []
    for i in range(0, len(up) - len(up) % 3, 3):
        codon = up[i:i + 3]
        aa = CODON_TABLE.get(codon, "X")
        if aa == "*":
            if to_stop:
                break
            protein.append("*")
            continue
        protein.append(aa)
    return "".join(protein)


# ---------------------------------------------------------------------------
# FASTA
# ---------------------------------------------------------------------------

def parse_fasta(text: str) -> list[FastaRecord]:
    """Parse FASTA text into a list of FastaRecord. Tolerates blank lines and
    trailing whitespace; raises SequenceError on structurally invalid input
    (sequence data before any '>' header)."""
    records: list[FastaRecord] = []
    header = None
    chunks: list[str] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            if header is not None:
                records.append(FastaRecord(header, "".join(chunks)))
            header = line[1:].strip()
            chunks = []
        else:
            if header is None:
                raise SequenceError(
                    f"line {lineno}: sequence data before first '>' header"
                )
            chunks.append(line)
    if header is not None:
        records.append(FastaRecord(header, "".join(chunks)))
    if not records:
        raise SequenceError("no FASTA records found")
    return records


def write_fasta(records: list[FastaRecord], *, width: int = 70) -> str:
    """Serialize FastaRecords back to FASTA text, wrapped at `width` columns."""
    out = []
    for rec in records:
        out.append(f">{rec.header}")
        seq = rec.sequence
        for i in range(0, len(seq), width) if seq else [0]:
            out.append(seq[i:i + width])
        if not seq:
            out.append("")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# FASTQ
# ---------------------------------------------------------------------------

def parse_fastq(text: str) -> list[FastqRecord]:
    """Parse FASTQ text (4 lines/record: @header, seq, +[header], qual)."""
    lines = [l for l in text.splitlines() if l != ""]
    if len(lines) % 4 != 0:
        raise SequenceError(
            f"FASTQ record count not a multiple of 4 ({len(lines)} lines)"
        )
    records = []
    for i in range(0, len(lines), 4):
        h, seq, plus, qual = lines[i:i + 4]
        if not h.startswith("@"):
            raise SequenceError(f"line {i + 1}: expected '@header', got {h!r}")
        if not plus.startswith("+"):
            raise SequenceError(f"line {i + 3}: expected '+...', got {plus!r}")
        if len(qual) != len(seq):
            raise SequenceError(
                f"record {h!r}: quality length {len(qual)} != "
                f"sequence length {len(seq)}"
            )
        records.append(FastqRecord(h[1:], seq, qual))
    if not records:
        raise SequenceError("no FASTQ records found")
    return records


def write_fastq(records: list[FastqRecord]) -> str:
    out = []
    for rec in records:
        out.append(f"@{rec.header}")
        out.append(rec.sequence)
        out.append("+")
        out.append(rec.quality)
    return "\n".join(out) + "\n"


def phred_to_quality_string(error_prob: float) -> str:
    """A single Phred+33 quality character for a given per-base error
    probability (clamped to a sane 2..60 Phred range)."""
    import math
    q = -10 * math.log10(max(error_prob, 1e-6))
    q = max(2, min(60, round(q)))
    return chr(q + 33)


# ---------------------------------------------------------------------------
# Synthetic genome + read simulation
# ---------------------------------------------------------------------------

def random_genome(length: int, *, seed: int, gc_bias: float = 0.5) -> str:
    """A seeded random DNA sequence of the given length. gc_bias in [0,1] is
    the probability of drawing a G/C base at each position."""
    if length <= 0:
        raise SequenceError("genome length must be positive")
    rng = random.Random(seed)
    bases = []
    for _ in range(length):
        if rng.random() < gc_bias:
            bases.append(rng.choice("GC"))
        else:
            bases.append(rng.choice("AT"))
    return "".join(bases)


@dataclass
class SimulatedRead:
    read_id: str
    sequence: str
    quality: str
    true_start: int          # 0-based origin position on the reference
    true_end: int             # exclusive
    strand: str                # '+' or '-'
    n_errors: int


def simulate_reads(
    genome: str,
    *,
    n_reads: int,
    read_length: int,
    error_rate: float = 0.01,
    seed: int = 0,
    both_strands: bool = True,
) -> list[SimulatedRead]:
    """Fragment `genome` into `n_reads` reads of `read_length`, each drawn
    from a uniformly random start position (and, if both_strands, a uniformly
    random strand), with independent per-base substitution errors at
    `error_rate`. Read length must not exceed the genome length."""
    genome = validate_dna(genome, name="genome")
    if read_length <= 0 or read_length > len(genome):
        raise SequenceError(
            f"read_length {read_length} must be in (0, {len(genome)}]"
        )
    if n_reads <= 0:
        raise SequenceError("n_reads must be positive")
    if not (0.0 <= error_rate < 1.0):
        raise SequenceError("error_rate must be in [0, 1)")
    rng = random.Random(seed)
    reads = []
    other_base = {"A": "CGT", "C": "AGT", "G": "ACT", "T": "ACG"}
    for i in range(n_reads):
        start = rng.randint(0, len(genome) - read_length)
        end = start + read_length
        frag = genome[start:end]
        strand = "+"
        if both_strands and rng.random() < 0.5:
            frag = reverse_complement(frag)
            strand = "-"
        bases = list(frag)
        n_errors = 0
        for j in range(len(bases)):
            if rng.random() < error_rate:
                orig = bases[j]
                choices = other_base.get(orig)
                if choices:
                    bases[j] = rng.choice(choices)
                    n_errors += 1
        qual = phred_to_quality_string(error_rate) * read_length
        reads.append(SimulatedRead(
            read_id=f"read{i}",
            sequence="".join(bases),
            quality=qual,
            true_start=start,
            true_end=end,
            strand=strand,
            n_errors=n_errors,
        ))
    return reads
