"""Pairwise sequence alignment: Needleman-Wunsch (global, linear gap) and
Gotoh's algorithm (affine-gap global and local/Smith-Waterman alignment via
three coupled DP planes), with full traceback and CIGAR output.

Conventions:
  - `seq_a` is treated as the reference, `seq_b` as the query, for CIGAR
    purposes: 'D' (deletion) consumes reference only, 'I' (insertion)
    consumes query only, '=' / 'X' consume both (match / mismatch).
  - Affine gap cost for a gap of length k is `gap_open + k * gap_extend`
    (the EMBOSS/needle convention: gap_open is a one-time additional charge
    on top of gap_extend for every gapped position).

Pure Python 3 stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass

NEG_INF = float("-inf")

# A widely-used amino-acid substitution matrix (BLOSUM62), included so
# protein alignment isn't limited to plain match/mismatch scoring. Symmetric;
# only the upper triangle + diagonal is written out and mirrored below.
_BLOSUM62_UPPER = {
    ("A", "A"): 4, ("A", "R"): -1, ("A", "N"): -2, ("A", "D"): -2, ("A", "C"): 0,
    ("A", "Q"): -1, ("A", "E"): -1, ("A", "G"): 0, ("A", "H"): -2, ("A", "I"): -1,
    ("A", "L"): -1, ("A", "K"): -1, ("A", "M"): -1, ("A", "F"): -2, ("A", "P"): -1,
    ("A", "S"): 1, ("A", "T"): 0, ("A", "W"): -3, ("A", "Y"): -2, ("A", "V"): 0,
    ("R", "R"): 5, ("R", "N"): 0, ("R", "D"): -2, ("R", "C"): -3, ("R", "Q"): 1,
    ("R", "E"): 0, ("R", "G"): -2, ("R", "H"): 0, ("R", "I"): -3, ("R", "L"): -2,
    ("R", "K"): 2, ("R", "M"): -1, ("R", "F"): -3, ("R", "P"): -2, ("R", "S"): -1,
    ("R", "T"): -1, ("R", "W"): -3, ("R", "Y"): -2, ("R", "V"): -3,
    ("N", "N"): 6, ("N", "D"): 1, ("N", "C"): -3, ("N", "Q"): 0, ("N", "E"): 0,
    ("N", "G"): 0, ("N", "H"): 1, ("N", "I"): -3, ("N", "L"): -3, ("N", "K"): 0,
    ("N", "M"): -2, ("N", "F"): -3, ("N", "P"): -2, ("N", "S"): 1, ("N", "T"): 0,
    ("N", "W"): -4, ("N", "Y"): -2, ("N", "V"): -3,
    ("D", "D"): 6, ("D", "C"): -3, ("D", "Q"): 0, ("D", "E"): 2, ("D", "G"): -1,
    ("D", "H"): -1, ("D", "I"): -3, ("D", "L"): -4, ("D", "K"): -1, ("D", "M"): -3,
    ("D", "F"): -3, ("D", "P"): -1, ("D", "S"): 0, ("D", "T"): -1, ("D", "W"): -4,
    ("D", "Y"): -3, ("D", "V"): -3,
    ("C", "C"): 9, ("C", "Q"): -3, ("C", "E"): -4, ("C", "G"): -3, ("C", "H"): -3,
    ("C", "I"): -1, ("C", "L"): -1, ("C", "K"): -3, ("C", "M"): -1, ("C", "F"): -2,
    ("C", "P"): -3, ("C", "S"): -1, ("C", "T"): -1, ("C", "W"): -2, ("C", "Y"): -2,
    ("C", "V"): -1,
    ("Q", "Q"): 5, ("Q", "E"): 2, ("Q", "G"): -2, ("Q", "H"): 0, ("Q", "I"): -3,
    ("Q", "L"): -2, ("Q", "K"): 1, ("Q", "M"): 0, ("Q", "F"): -3, ("Q", "P"): -1,
    ("Q", "S"): 0, ("Q", "T"): -1, ("Q", "W"): -2, ("Q", "Y"): -1, ("Q", "V"): -2,
    ("E", "E"): 5, ("E", "G"): -2, ("E", "H"): 0, ("E", "I"): -3, ("E", "L"): -3,
    ("E", "K"): 1, ("E", "M"): -2, ("E", "F"): -3, ("E", "P"): -1, ("E", "S"): 0,
    ("E", "T"): -1, ("E", "W"): -3, ("E", "Y"): -2, ("E", "V"): -2,
    ("G", "G"): 6, ("G", "H"): -2, ("G", "I"): -4, ("G", "L"): -4, ("G", "K"): -2,
    ("G", "M"): -3, ("G", "F"): -3, ("G", "P"): -2, ("G", "S"): 0, ("G", "T"): -2,
    ("G", "W"): -2, ("G", "Y"): -3, ("G", "V"): -3,
    ("H", "H"): 8, ("H", "I"): -3, ("H", "L"): -3, ("H", "K"): -1, ("H", "M"): -2,
    ("H", "F"): -1, ("H", "P"): -2, ("H", "S"): -1, ("H", "T"): -2, ("H", "W"): -2,
    ("H", "Y"): 2, ("H", "V"): -3,
    ("I", "I"): 4, ("I", "L"): 2, ("I", "K"): -3, ("I", "M"): 1, ("I", "F"): 0,
    ("I", "P"): -3, ("I", "S"): -2, ("I", "T"): -1, ("I", "W"): -3, ("I", "Y"): -1,
    ("I", "V"): 3,
    ("L", "L"): 4, ("L", "K"): -2, ("L", "M"): 2, ("L", "F"): 0, ("L", "P"): -3,
    ("L", "S"): -2, ("L", "T"): -1, ("L", "W"): -2, ("L", "Y"): -1, ("L", "V"): 1,
    ("K", "K"): 5, ("K", "M"): -1, ("K", "F"): -3, ("K", "P"): -1, ("K", "S"): 0,
    ("K", "T"): -1, ("K", "W"): -3, ("K", "Y"): -2, ("K", "V"): -2,
    ("M", "M"): 5, ("M", "F"): 0, ("M", "P"): -2, ("M", "S"): -1, ("M", "T"): -1,
    ("M", "W"): -1, ("M", "Y"): -1, ("M", "V"): 1,
    ("F", "F"): 6, ("F", "P"): -4, ("F", "S"): -2, ("F", "T"): -2, ("F", "W"): 1,
    ("F", "Y"): 3, ("F", "V"): -1,
    ("P", "P"): 7, ("P", "S"): -1, ("P", "T"): -1, ("P", "W"): -4, ("P", "Y"): -3,
    ("P", "V"): -2,
    ("S", "S"): 4, ("S", "T"): 1, ("S", "W"): -3, ("S", "Y"): -2, ("S", "V"): -2,
    ("T", "T"): 5, ("T", "W"): -2, ("T", "Y"): -2, ("T", "V"): 0,
    ("W", "W"): 11, ("W", "Y"): 2, ("W", "V"): -3,
    ("Y", "Y"): 7, ("Y", "V"): -1,
    ("V", "V"): 4,
}


def _build_blosum62() -> dict[tuple[str, str], int]:
    full = {}
    for (a, b), v in _BLOSUM62_UPPER.items():
        full[(a, b)] = v
        full[(b, a)] = v
    return full


BLOSUM62 = _build_blosum62()


@dataclass
class AlignmentResult:
    score: int
    aligned_a: str
    aligned_b: str
    # 0-based, half-open [start, end) region of each input sequence that
    # participated in the alignment (for local alignment this is the hit
    # region; for global alignment it is always the whole sequence).
    a_start: int
    a_end: int
    b_start: int
    b_end: int
    cigar: str

    def pretty(self) -> str:
        match_line = "".join(
            "|" if x == y and x != "-" else (" " if x == "-" or y == "-" else ".")
            for x, y in zip(self.aligned_a, self.aligned_b)
        )
        return f"{self.aligned_a}\n{match_line}\n{self.aligned_b}"


def _score_fn(match: int, mismatch: int, matrix: dict | None):
    if matrix is not None:
        def fn(a, b):
            if (a, b) not in matrix:
                raise KeyError(f"no substitution score for pair ({a!r}, {b!r})")
            return matrix[(a, b)]
        return fn

    def fn(a, b):
        return match if a == b else mismatch
    return fn


def _cigar_from_ops(ops: list[str]) -> str:
    """Run-length encode a list of single-char CIGAR ops into a CIGAR string."""
    if not ops:
        return ""
    out = []
    cur = ops[0]
    count = 1
    for op in ops[1:]:
        if op == cur:
            count += 1
        else:
            out.append(f"{count}{cur}")
            cur = op
            count = 1
    out.append(f"{count}{cur}")
    return "".join(out)


# ---------------------------------------------------------------------------
# Needleman-Wunsch — global alignment, simple linear gap penalty.
# Kept deliberately separate from the Gotoh engine below so it can serve as
# an independent oracle to differentially test the (more complex) affine-gap
# implementation against, in the degenerate gap_open=0 case.
# ---------------------------------------------------------------------------

def needleman_wunsch_linear(
    seq_a: str, seq_b: str, *, match: int = 1, mismatch: int = -1, gap: int = -2,
    matrix: dict | None = None,
) -> AlignmentResult:
    if not seq_a or not seq_b:
        raise ValueError("both sequences must be non-empty")
    n, m = len(seq_a), len(seq_b)
    score = _score_fn(match, mismatch, matrix)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = i * gap
    for j in range(1, m + 1):
        dp[0][j] = j * gap
    for i in range(1, n + 1):
        ai = seq_a[i - 1]
        row = dp[i]
        prev = dp[i - 1]
        for j in range(1, m + 1):
            bj = seq_b[j - 1]
            diag = prev[j - 1] + score(ai, bj)
            up = prev[j] + gap
            left = row[j - 1] + gap
            row[j] = max(diag, up, left)

    # Traceback.
    aligned_a, aligned_b, ops = [], [], []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + score(seq_a[i - 1], seq_b[j - 1]):
            aligned_a.append(seq_a[i - 1])
            aligned_b.append(seq_b[j - 1])
            ops.append("=" if seq_a[i - 1] == seq_b[j - 1] else "X")
            i -= 1
            j -= 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + gap:
            aligned_a.append(seq_a[i - 1])
            aligned_b.append("-")
            ops.append("D")
            i -= 1
        else:
            aligned_a.append("-")
            aligned_b.append(seq_b[j - 1])
            ops.append("I")
            j -= 1
    aligned_a.reverse()
    aligned_b.reverse()
    ops.reverse()
    return AlignmentResult(
        score=dp[n][m],
        aligned_a="".join(aligned_a),
        aligned_b="".join(aligned_b),
        a_start=0, a_end=n, b_start=0, b_end=m,
        cigar=_cigar_from_ops(ops),
    )


# ---------------------------------------------------------------------------
# Gotoh's algorithm — affine-gap global and local alignment via 3 DP planes.
#
#   M[i][j] = best score of an alignment of a[:i], b[:j] that ends with a
#             match/mismatch at (i, j)
#   D[i][j] = ... that ends with a gap in b (a "deletion" relative to a)
#   I[i][j] = ... that ends with a gap in a (an "insertion" relative to a)
#
# In local (Smith-Waterman) mode, M additionally resets to 0 whenever the
# running score would go negative, exactly as in the linear-gap case, and
# D[*][0] / I[0][*] are never allowed to be the start of a local alignment
# (starting on a gap is never optimal).
# ---------------------------------------------------------------------------

def _gotoh_matrices(seq_a, seq_b, score, gap_open, gap_extend, *, local: bool):
    n, m = len(seq_a), len(seq_b)
    gap_first = gap_open + gap_extend  # cost of the FIRST gapped position
    M = [[NEG_INF] * (m + 1) for _ in range(n + 1)]
    D = [[NEG_INF] * (m + 1) for _ in range(n + 1)]
    I = [[NEG_INF] * (m + 1) for _ in range(n + 1)]

    if local:
        for i in range(n + 1):
            M[i][0] = 0
        for j in range(m + 1):
            M[0][j] = 0
        # D[*][0] and I[0][*] stay NEG_INF: a local alignment never opens on a gap.
    else:
        M[0][0] = 0
        # M[i][0] / M[0][j] for i,j > 0 stay NEG_INF: there is no real
        # match/mismatch state on a DP boundary row/column (a match/
        # mismatch always consumes one base from BOTH sequences), so
        # nothing but the true (0,0) origin should ever be treated as one
        # during traceback. D[i][0] and I[0][j] are the real all-gap-prefix
        # boundary costs the forward recurrence and traceback both need.
        for i in range(1, n + 1):
            D[i][0] = -(gap_open + i * gap_extend)
        for j in range(1, m + 1):
            I[0][j] = -(gap_open + j * gap_extend)

    best = (0, 0, 0)  # score, i, j — best local cell (only meaningful if local)

    for i in range(1, n + 1):
        ai = seq_a[i - 1]
        for j in range(1, m + 1):
            bj = seq_b[j - 1]
            s = score(ai, bj)
            diag = max(M[i - 1][j - 1], D[i - 1][j - 1], I[i - 1][j - 1]) + s
            if local:
                diag = max(diag, 0)
            M[i][j] = diag
            D[i][j] = max(M[i - 1][j] - gap_first, D[i - 1][j] - gap_extend)
            I[i][j] = max(M[i][j - 1] - gap_first, I[i][j - 1] - gap_extend)
            if local and M[i][j] > best[0]:
                best = (M[i][j], i, j)

    return M, D, I, best


def align_affine(
    seq_a: str, seq_b: str, *,
    mode: str = "global",
    match: int = 1, mismatch: int = -1,
    gap_open: int = 5, gap_extend: int = 1,
    matrix: dict | None = None,
    trace: list | None = None,
) -> AlignmentResult:
    """Gotoh affine-gap alignment.

    mode='global' -> full Needleman-Wunsch-with-affine-gaps alignment of the
    entire sequences.
    mode='local'  -> Smith-Waterman-with-affine-gaps: the highest-scoring
    local alignment (may be a strict substring of each input).

    If `trace` is given a list, it is populated (in forward, start-to-end
    order) with the (i, j) DP-matrix cell visited at each step of the
    traceback — used by helix.viz to draw the real traceback path over the
    alignment matrix, rather than re-deriving it from the returned strings.
    """
    if mode not in ("global", "local"):
        raise ValueError("mode must be 'global' or 'local'")
    if not seq_a or not seq_b:
        raise ValueError("both sequences must be non-empty")
    if gap_open < 0 or gap_extend < 0:
        raise ValueError("gap_open and gap_extend must be non-negative penalties")
    n, m = len(seq_a), len(seq_b)
    score = _score_fn(match, mismatch, matrix)
    local = mode == "local"
    M, D, I, best = _gotoh_matrices(seq_a, seq_b, score, gap_open, gap_extend, local=local)
    gap_first = gap_open + gap_extend

    if local:
        if best[0] <= 0:
            # No positive-scoring local alignment exists at all.
            return AlignmentResult(0, "", "", 0, 0, 0, 0, "")
        final_score, i, j = best
        state = "M"
    else:
        final_score = max(M[n][m], D[n][m], I[n][m])
        i, j = n, m
        state = max(("M", M[n][m]), ("D", D[n][m]), ("I", I[n][m]), key=lambda t: t[1])[0]

    aligned_a, aligned_b, ops = [], [], []
    a_end, b_end = i, j

    while True:
        if local:
            if state == "M" and M[i][j] == 0:
                break
        else:
            if i == 0 and j == 0:
                break
        if trace is not None:
            trace.append((i, j))

        if state == "M":
            ai, bj = seq_a[i - 1], seq_b[j - 1]
            aligned_a.append(ai)
            aligned_b.append(bj)
            ops.append("=" if ai == bj else "X")
            pm = M[i - 1][j - 1]
            pd = D[i - 1][j - 1]
            pi = I[i - 1][j - 1]
            i, j = i - 1, j - 1
            candidates = {"M": pm, "D": pd, "I": pi}
            state = max(candidates, key=candidates.get)
        elif state == "D":
            aligned_a.append(seq_a[i - 1])
            aligned_b.append("-")
            ops.append("D")
            came_from_M = D[i][j] == M[i - 1][j] - gap_first
            i -= 1
            state = "M" if came_from_M else "D"
        else:  # state == "I"
            aligned_a.append("-")
            aligned_b.append(seq_b[j - 1])
            ops.append("I")
            came_from_M = I[i][j] == M[i][j - 1] - gap_first
            j -= 1
            state = "M" if came_from_M else "I"

    if trace is not None:
        trace.append((i, j))  # the terminal cell (a_start, b_start)
        trace.reverse()       # forward, start-to-end order

    aligned_a.reverse()
    aligned_b.reverse()
    ops.reverse()
    a_start, b_start = i, j
    return AlignmentResult(
        score=int(final_score),
        aligned_a="".join(aligned_a),
        aligned_b="".join(aligned_b),
        a_start=a_start, a_end=a_end, b_start=b_start, b_end=b_end,
        cigar=_cigar_from_ops(ops),
    )


def global_align(seq_a: str, seq_b: str, **kwargs) -> AlignmentResult:
    return align_affine(seq_a, seq_b, mode="global", **kwargs)


def local_align(seq_a: str, seq_b: str, **kwargs) -> AlignmentResult:
    return align_affine(seq_a, seq_b, mode="local", **kwargs)


def brute_force_global_score(
    seq_a: str, seq_b: str, *, match: int = 1, mismatch: int = -1, gap: int = -2,
) -> int:
    """A independent top-down memoized linear-gap global alignment scorer
    used ONLY as a correctness oracle in tests, not on any hot path — a
    separate implementation (recursive, not the bottom-up DP table) from
    needleman_wunsch_linear so it can't share a bug with it."""
    from functools import lru_cache
    score = _score_fn(match, mismatch, None)

    @lru_cache(maxsize=None)
    def best(i, j):
        if i == 0 and j == 0:
            return 0
        if i == 0:
            return j * gap
        if j == 0:
            return i * gap
        return max(
            best(i - 1, j - 1) + score(seq_a[i - 1], seq_b[j - 1]),
            best(i - 1, j) + gap,
            best(i, j - 1) + gap,
        )

    return best(len(seq_a), len(seq_b))
