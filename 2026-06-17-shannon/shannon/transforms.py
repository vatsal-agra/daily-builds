"""Reversible transforms for the bzip2-style pipeline: BWT, MTF, RLE.

None of these compress on their own; they *rearrange* data so the downstream
entropy coder does better. The Burrows-Wheeler Transform groups similar contexts
together, Move-To-Front turns that local similarity into lots of small numbers
(mostly zero), and run-length coding collapses the resulting runs.
"""
from __future__ import annotations

from typing import List, Tuple

SENTINEL = 256  # a symbol strictly greater than any byte, so all suffixes differ


def suffix_array(s: List[int]) -> List[int]:
    """Suffix array of an integer sequence via prefix doubling, O(n log^2 n)."""
    n = len(s)
    if n == 0:
        return []
    sa = list(range(n))
    rank = list(s)
    tmp = [0] * n
    k = 1
    sa.sort(key=lambda i: rank[i])
    while True:
        def key(i: int):
            return (rank[i], rank[i + k] if i + k < n else -1)
        sa.sort(key=key)
        tmp[sa[0]] = 0
        for idx in range(1, n):
            tmp[sa[idx]] = tmp[sa[idx - 1]] + (1 if key(sa[idx]) != key(sa[idx - 1]) else 0)
        rank = tmp[:]
        if rank[sa[-1]] == n - 1:
            break
        k *= 2
    return sa


def bwt_encode(block: bytes) -> Tuple[bytes, int]:
    """Burrows-Wheeler transform of a block.

    Returns (transformed_bytes, sentinel_position). A sentinel symbol (256) makes
    every rotation unique; we record where it lands so the inverse can rebuild the
    terminated string, and we strip it from the transmitted bytes (so the output
    stays a pure byte string).
    """
    if not block:
        return b"", 0
    s = list(block) + [SENTINEL]
    sa = suffix_array(s)
    m = len(s)
    out = bytearray()
    sent_pos = 0
    for rank, start in enumerate(sa):
        sym = s[start - 1]  # preceding symbol (wraps to s[-1] when start==0)
        if sym == SENTINEL:
            sent_pos = rank
        else:
            out.append(sym)
    return bytes(out), sent_pos


def bwt_decode(data: bytes, sent_pos: int) -> bytes:
    """Inverse BWT via LF-mapping. Inverse of :func:`bwt_encode`."""
    if not data:
        return b""
    # Reinsert the sentinel column: the full last column L over alphabet 0..256.
    n = len(data) + 1
    L = list(data)
    L.insert(sent_pos, SENTINEL)
    # Counting sort of L gives the first column and the LF mapping.
    counts = [0] * 257
    for c in L:
        counts[c] += 1
    starts = [0] * 257
    total = 0
    for c in range(257):
        starts[c] = total
        total += counts[c]
    # next[i] = row reached by following the LF mapping from row i
    occ = [0] * 257
    lf = [0] * n
    for i, c in enumerate(L):
        lf[i] = starts[c] + occ[c]
        occ[c] += 1
    # Reconstruct by walking from the sentinel row backwards.
    out = bytearray()
    row = sent_pos
    for _ in range(n):
        c = L[row]
        if c != SENTINEL:
            out.append(c)
        row = lf[row]
    out.reverse()
    # The walk emits the original string terminated by sentinel; sentinel skipped.
    return bytes(out)


def mtf_encode(data: bytes) -> bytes:
    table = list(range(256))
    out = bytearray()
    for b in data:
        idx = table.index(b)
        out.append(idx)
        table.pop(idx)
        table.insert(0, b)
    return bytes(out)


def mtf_decode(data: bytes) -> bytes:
    table = list(range(256))
    out = bytearray()
    for idx in data:
        b = table[idx]
        out.append(b)
        table.pop(idx)
        table.insert(0, b)
    return bytes(out)


# Run-length coding (PKZIP-style): four identical bytes are followed by a count
# byte giving the number of *additional* repeats (0..255). Purely byte-valued, so
# it composes cleanly with the Huffman backend.

def rle_encode(data: bytes) -> bytes:
    out = bytearray()
    n = len(data)
    i = 0
    while i < n:
        b = data[i]
        run = 1
        while i + run < n and data[i + run] == b and run < 4 + 255:
            run += 1
        if run >= 4:
            out.extend([b, b, b, b])
            out.append(run - 4)
            i += run
        else:
            out.extend([b] * run)
            i += run
    return bytes(out)


def rle_decode(data: bytes) -> bytes:
    out = bytearray()
    n = len(data)
    i = 0
    while i < n:
        b = data[i]
        out.append(b)
        # detect four-in-a-row
        if i + 3 < n and data[i + 1] == b and data[i + 2] == b and data[i + 3] == b:
            out.extend([b, b, b])
            extra = data[i + 4]
            out.extend([b] * extra)
            i += 5
        else:
            i += 1
    return bytes(out)
