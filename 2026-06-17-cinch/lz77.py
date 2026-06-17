"""LZ77 dictionary compression with a hash-chain match finder.

`tokenize` turns bytes into a stream of tokens:
  - an int 0..255            -> a literal byte
  - a (length, distance) tuple -> "copy `length` bytes from `distance` back"
`detokenize` is the exact inverse (handling overlapping copies, e.g. runs).

`encode`/`decode` wrap that in a compact, self-describing byte blob: a flag
bitstream (literal vs match) plus separate literal and match payload streams.
The genuinely compressive entropy stage lives in deflate.py, which Huffman-codes
these same tokens; here the tokens are serialized fairly directly.
"""
from __future__ import annotations

from bitio import BitReader, BitWriter
from util import read_uvarint, write_uvarint

MIN_MATCH = 3
MAX_MATCH = 258
WINDOW = 32768          # max distance
HASH_BITS = 15
HASH_SIZE = 1 << HASH_BITS
HASH_MASK = HASH_SIZE - 1

Token = "int | tuple[int, int]"


def _hash3(data: bytes, i: int) -> int:
    return ((data[i] << 10) ^ (data[i + 1] << 5) ^ data[i + 2]) & HASH_MASK


def tokenize(data: bytes, max_chain: int = 128) -> list:
    """Greedy longest-match LZ77 with one-step lazy matching.

    `max_chain` bounds match-finder effort (higher = better ratio, slower).

    Invariant: every insertable position (p with p+MIN_MATCH <= n) is inserted
    into the hash chains exactly once, in increasing order, so chains only ever
    point backwards and never form a self-loop.
    """
    n = len(data)
    tokens: list = []
    if n == 0:
        return tokens

    head = [-1] * HASH_SIZE
    prev = [-1] * n

    def insert(i: int) -> int:
        """Insert position i; return the previous chain head (an earlier pos)."""
        h = _hash3(data, i)
        j = head[h]
        prev[i] = j
        head[h] = i
        return j

    def find_match(i: int, chain_start: int) -> tuple[int, int]:
        """Best (length, distance) for position i, searching from chain_start."""
        if i + MIN_MATCH > n:
            return 0, 0
        j = chain_start
        best_len = 0
        best_dist = 0
        limit = min(MAX_MATCH, n - i)
        chain = max_chain
        while j >= 0 and chain > 0:
            if i - j > WINDOW:
                break
            # Quick reject: only bother if we could beat the current best.
            if best_len == 0 or (i + best_len < n and data[j + best_len] == data[i + best_len]):
                length = 0
                while length < limit and data[j + length] == data[i + length]:
                    length += 1
                if length > best_len:
                    best_len = length
                    best_dist = i - j
                    if length >= limit:
                        break
            j = prev[j]
            chain -= 1
        if best_len >= MIN_MATCH:
            return best_len, best_dist
        return 0, 0

    def match_at(i: int) -> tuple[int, int]:
        if i + MIN_MATCH <= n:
            return find_match(i, insert(i))
        return 0, 0

    i = 0
    deferred: tuple[int, int] | None = None  # a match starting at i-1, not yet emitted
    while i < n:
        cur_len, cur_dist = match_at(i)
        if deferred is not None:
            plen, pdist = deferred
            if cur_len > plen:
                # Current match is strictly better: emit a literal for i-1,
                # and defer the current match instead.
                tokens.append(data[i - 1])
                deferred = (cur_len, cur_dist)
                i += 1
                continue
            # Previous match wins: emit it and skip the bytes it covers.
            tokens.append((plen, pdist))
            start = i - 1
            end = start + plen          # exclusive
            j = i + 1                   # i-1 and i are already inserted
            while j < end:
                if j + MIN_MATCH <= n:
                    insert(j)
                j += 1
            i = end
            deferred = None
            continue
        if cur_len >= MIN_MATCH:
            deferred = (cur_len, cur_dist)  # lazily hold; maybe i+1 is better
            i += 1
        else:
            tokens.append(data[i])
            i += 1
    if deferred is not None:
        tokens.append(deferred)
    return tokens


def detokenize(tokens: list) -> bytes:
    out = bytearray()
    for tok in tokens:
        if isinstance(tok, int):
            out.append(tok)
        else:
            length, dist = tok
            start = len(out) - dist
            if start < 0:
                raise ValueError("match distance points before start of output")
            for k in range(length):
                out.append(out[start + k])
    return bytes(out)


def encode(data: bytes, max_chain: int = 128) -> bytes:
    tokens = tokenize(data, max_chain=max_chain)
    flags = BitWriter()
    lits = bytearray()
    mats = bytearray()
    for tok in tokens:
        if isinstance(tok, int):
            flags.write_bit(0)
            lits.append(tok)
        else:
            length, dist = tok
            flags.write_bit(1)
            write_uvarint(mats, length - MIN_MATCH)
            write_uvarint(mats, dist)
    flag_bytes = flags.getvalue()

    out = bytearray()
    write_uvarint(out, len(data))
    write_uvarint(out, len(tokens))
    write_uvarint(out, len(flag_bytes))
    out += flag_bytes
    write_uvarint(out, len(lits))
    out += lits
    out += mats
    return bytes(out)


def decode(blob: bytes) -> bytes:
    n, pos = read_uvarint(blob, 0)
    if n == 0:
        return b""
    ntokens, pos = read_uvarint(blob, pos)
    flag_len, pos = read_uvarint(blob, pos)
    flag_bytes = blob[pos:pos + flag_len]
    pos += flag_len
    lit_len, pos = read_uvarint(blob, pos)
    lits = blob[pos:pos + lit_len]
    pos += lit_len
    mat_pos = pos

    flags = BitReader(flag_bytes)
    out = bytearray()
    li = 0
    for _ in range(ntokens):
        if flags.read_bit() == 0:
            out.append(lits[li])
            li += 1
        else:
            length_m, mat_pos = read_uvarint(blob, mat_pos)
            dist, mat_pos = read_uvarint(blob, mat_pos)
            length = length_m + MIN_MATCH
            start = len(out) - dist
            for k in range(length):
                out.append(out[start + k])
    return bytes(out)
