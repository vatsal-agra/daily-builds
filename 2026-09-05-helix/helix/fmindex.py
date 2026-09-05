"""Suffix array / BWT / FM-index — the algorithm behind BWA/Bowtie-style
short-read aligners.

Pipeline: reference -> suffix array (prefix-doubling, O(n log^2 n)) ->
Burrows-Wheeler Transform (read directly off the suffix array) -> FM-index
(a compact rank/occurrence structure over the BWT with periodic
checkpoints) -> exact backward-search alignment of query reads.

The BWT's own losslessness is demonstrated by `invert_bwt`, an independent
LF-mapping-based inverse that doesn't touch the suffix array at all — if the
forward transform has a bug, round-tripping through this inverse will not
recover the original string.

Pure Python 3 stdlib only.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

SENTINEL = "$"  # sorts before every real base (ASCII 36 < 'A'..'Z' 65-90)


class FMIndexError(ValueError):
    pass


def build_suffix_array(s: str) -> list[int]:
    """Prefix-doubling suffix array construction, O(n log^2 n): sort
    suffixes by successively longer prefixes (length 1, 2, 4, 8, ...),
    reusing the previous round's rank to compare each doubled-length prefix
    in O(1). `s` must already end with a unique sentinel smaller than every
    other character (callers append SENTINEL themselves)."""
    n = len(s)
    if n == 0:
        return []
    sa = list(range(n))
    rank = [ord(c) for c in s]
    k = 1
    while True:
        def key(i: int):
            return (rank[i], rank[i + k] if i + k < n else -1)

        sa.sort(key=key)
        new_rank = [0] * n
        new_rank[sa[0]] = 0
        for i in range(1, n):
            new_rank[sa[i]] = new_rank[sa[i - 1]] + (
                1 if key(sa[i]) != key(sa[i - 1]) else 0
            )
        rank = new_rank
        if rank[sa[-1]] == n - 1:
            break
        k *= 2
    return sa


def bwt_from_suffix_array(s: str, sa: list[int]) -> str:
    """BWT[i] = the character immediately preceding suffix sa[i] in s (with
    wraparound: the suffix starting at 0 is preceded by s's last character,
    which is the sentinel by construction)."""
    return "".join(s[i - 1] if i > 0 else s[-1] for i in sa)


def invert_bwt(bwt: str, sentinel: str = SENTINEL) -> str:
    """Reconstruct the original string from its BWT alone via LF-mapping —
    deliberately independent of the suffix array (a real correctness proof
    of the transform, not just a round trip through the same code path)."""
    if not bwt:
        raise FMIndexError("empty BWT")
    n = len(bwt)
    counts = Counter(bwt)
    chars = sorted(counts)
    first_index: dict[str, int] = {}
    total = 0
    for c in chars:
        first_index[c] = total
        total += counts[c]
    # LF[i]: for row i (character bwt[i]), the row in the sorted-rotations
    # matrix that the same physical character occupies in the first column.
    seen: dict[str, int] = {c: 0 for c in chars}
    LF = [0] * n
    for i, c in enumerate(bwt):
        LF[i] = first_index[c] + seen[c]
        seen[c] += 1
    # Row 0 of the sorted rotation matrix is the lexicographically smallest
    # rotation, i.e. the one starting with the sentinel. bwt[row] is always
    # the character immediately BEFORE the current row's rotation, so
    # walking row -> LF[row] and collecting bwt[row] at each step (before
    # advancing) walks the original text backward, one character per step,
    # starting from its last character and ending at the sentinel itself.
    row = 0
    out = []
    for _ in range(n):
        out.append(bwt[row])
        row = LF[row]
    reconstructed = "".join(reversed(out))
    # reconstructed = sentinel + original_string (the walk collects the
    # sentinel last); drop the leading sentinel to match input.
    if not reconstructed.startswith(sentinel):
        raise FMIndexError("BWT inversion did not recover a sentinel-terminated string")
    return reconstructed[1:]


@dataclass
class FMIndex:
    reference: str
    checkpoint_interval: int = 16

    def __post_init__(self):
        if not self.reference:
            raise FMIndexError("reference must be non-empty")
        if SENTINEL in self.reference:
            raise FMIndexError(f"reference must not contain the sentinel {SENTINEL!r}")
        if self.checkpoint_interval < 1:
            # Not just a crash-avoidance check: a negative interval doesn't
            # raise at all (Python's % on a negative divisor is well-defined,
            # just not what this indexing scheme assumes) — it silently
            # produces WRONG occ() lookups and therefore wrong search
            # results, which is worse than a crash.
            raise FMIndexError("checkpoint_interval must be >= 1")
        s = self.reference + SENTINEL
        self.sa = build_suffix_array(s)
        self.bwt = bwt_from_suffix_array(s, self.sa)
        self.n = len(s)
        counts = Counter(self.bwt)
        self.alphabet = sorted(counts)
        self.C: dict[str, int] = {}
        total = 0
        for c in self.alphabet:
            self.C[c] = total
            total += counts[c]
        # Checkpointed occurrence table: every `checkpoint_interval`
        # positions, snapshot the running per-character count so far;
        # queries between checkpoints do a short linear scan.
        self._checkpoints: dict[str, list[int]] = {c: [] for c in self.alphabet}
        running = {c: 0 for c in self.alphabet}
        for i, c in enumerate(self.bwt):
            if i % self.checkpoint_interval == 0:
                for cc in self.alphabet:
                    self._checkpoints[cc].append(running[cc])
            running[c] += 1
        # one final checkpoint covering i == n exactly (occ()'s upper end
        # of the FM-index search range starts at self.n), since the loop
        # above only ever snapshots at i < n.
        for cc in self.alphabet:
            self._checkpoints[cc].append(running[cc])
        self._total_counts = dict(running)

    def occ(self, c: str, i: int) -> int:
        """Number of occurrences of character c in bwt[0:i] (exclusive)."""
        if c not in self.C:
            return 0
        cp_idx = i // self.checkpoint_interval
        base = self._checkpoints[c][cp_idx]
        start = cp_idx * self.checkpoint_interval
        count = base
        bwt = self.bwt
        for j in range(start, i):
            if bwt[j] == c:
                count += 1
        return count

    def _backward_search_range(self, pattern: str) -> tuple[int, int]:
        l, r = 0, self.n
        for ch in reversed(pattern):
            if ch not in self.C:
                return (0, 0)
            l = self.C[ch] + self.occ(ch, l)
            r = self.C[ch] + self.occ(ch, r)
            if l >= r:
                return (0, 0)
        return l, r

    def search(self, pattern: str) -> list[int]:
        """Exact backward-search: all 0-based start positions of `pattern`
        in the reference. Empty result for a pattern that doesn't occur."""
        if not pattern:
            raise FMIndexError("pattern must be non-empty")
        l, r = self._backward_search_range(pattern)
        if l >= r:
            return []
        return sorted(self.sa[l:r])

    def count(self, pattern: str) -> int:
        l, r = self._backward_search_range(pattern)
        return max(0, r - l)


def naive_search(text: str, pattern: str) -> list[int]:
    """Naive O(nm) substring search, used ONLY as a differential oracle in
    tests/CLI verification — not on any hot path."""
    if not pattern:
        raise FMIndexError("pattern must be non-empty")
    out = []
    start = 0
    while True:
        idx = text.find(pattern, start)
        if idx == -1:
            break
        out.append(idx)
        start = idx + 1
    return out


@dataclass
class AlignedRead:
    read_id: str
    sequence: str
    positions: list[int]     # empty if unaligned; >1 entry if multi-mapped
    strand: str               # '+' or '-' (whichever orientation matched)

    @property
    def mapped(self) -> bool:
        return len(self.positions) > 0

    @property
    def unique(self) -> bool:
        return len(self.positions) == 1


def align_reads(index: FMIndex, reads: list[tuple[str, str]], *, try_reverse_complement: bool = True) -> list[AlignedRead]:
    """Align each (read_id, sequence) pair against `index` via exact
    backward search, trying the reverse complement if the forward strand
    doesn't map (FM-index search itself is strand-agnostic about *which*
    orientation is queried, so this is how read alignment normally handles
    not knowing a read's originating strand)."""
    from helix.seq import reverse_complement

    out = []
    for read_id, seq in reads:
        fwd = index.search(seq)
        if fwd:
            out.append(AlignedRead(read_id, seq, fwd, "+"))
            continue
        if try_reverse_complement:
            rc = reverse_complement(seq)
            rev = index.search(rc)
            if rev:
                out.append(AlignedRead(read_id, seq, rev, "-"))
                continue
        out.append(AlignedRead(read_id, seq, [], "+"))
    return out


def place_read_by_seeds(index: FMIndex, read: str, *, seed_length: int = 20) -> int | None:
    """Locate a read carrying scattered mismatches (sequencing errors, or
    real variants) that an exact whole-read search would miss entirely: chop
    it into non-overlapping `seed_length` seeds, exact-match each seed with
    the FM-index, and let every matching seed "vote" for the read's implied
    start position (seed genomic position minus its offset within the
    read). As long as at least one seed is error-free — true for any read
    whose per-base error rate isn't extreme relative to seed_length — the
    correct start position gets a vote and wins a majority. Returns None if
    no seed matches anywhere (the read doesn't belong to this reference)."""
    if seed_length < 1:
        raise FMIndexError("seed_length must be >= 1")
    votes: Counter[int] = Counter()
    for offset in range(0, len(read) - seed_length + 1, seed_length):
        seed = read[offset:offset + seed_length]
        for pos in index.search(seed):
            votes[pos - offset] += 1
    if not votes:
        return None
    return votes.most_common(1)[0][0]
