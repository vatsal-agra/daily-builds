"""A from-scratch byte-level BPE (byte-pair encoding) tokenizer.

Operates on raw UTF-8 bytes (256 base tokens), so it can tokenize and
losslessly reconstruct ANY unicode text, including text never seen during
training. A simple pretokenizer splits text into whitespace / word /
punctuation runs so merges never cross those boundaries (the same idea GPT-2
popularized, reimplemented independently here) -- this keeps punctuation and
word boundaries from merging into "unnatural" tokens.
"""
import json
import re
from collections import Counter

_PRETOKEN_RE = re.compile(r"\w+|\s+|[^\w\s]+", re.UNICODE)


def _pretokenize(text):
    return _PRETOKEN_RE.findall(text)


def _merge_seq(seq, pair, new_id):
    out = []
    i = 0
    n = len(seq)
    while i < n:
        if i < n - 1 and seq[i] == pair[0] and seq[i + 1] == pair[1]:
            out.append(new_id)
            i += 2
        else:
            out.append(seq[i])
            i += 1
    return out


class BPETokenizer:
    def __init__(self):
        self.merge_order = []  # list of (a, b) pairs, in the order they were learned
        self._rebuild_derived()

    def _rebuild_derived(self):
        self.vocab = {i: bytes([i]) for i in range(256)}
        self.merges = {}
        self.ranks = {}
        for rank, (a, b) in enumerate(self.merge_order):
            new_id = 256 + rank
            self.merges[(a, b)] = new_id
            self.ranks[(a, b)] = rank
            self.vocab[new_id] = self.vocab[a] + self.vocab[b]

    @property
    def vocab_size(self):
        return 256 + len(self.merge_order)

    def train(self, text, vocab_size, verbose=False):
        assert vocab_size >= 256, "vocab_size must be at least 256 (the byte base vocab)"
        num_merges = vocab_size - 256
        chunks = _pretokenize(text)
        chunk_freq = Counter(chunks)
        seqs = {chunk: list(chunk.encode("utf-8")) for chunk in chunk_freq}

        merge_order = []
        vocab = {i: bytes([i]) for i in range(256)}

        for i in range(num_merges):
            pair_counts = Counter()
            for chunk, freq in chunk_freq.items():
                seq = seqs[chunk]
                for a, b in zip(seq, seq[1:]):
                    pair_counts[(a, b)] += freq
            if not pair_counts:
                break
            best_pair, best_count = max(pair_counts.items(), key=lambda kv: kv[1])
            if best_count < 2:
                break  # merging a pair that occurs once never helps compression
            new_id = 256 + len(merge_order)
            merge_order.append(best_pair)
            vocab[new_id] = vocab[best_pair[0]] + vocab[best_pair[1]]
            for chunk in seqs:
                seqs[chunk] = _merge_seq(seqs[chunk], best_pair, new_id)
            if verbose and (i % 50 == 0 or i == num_merges - 1):
                a, b = best_pair
                print(
                    f"merge {i + 1}/{num_merges}: {vocab[a]!r} + {vocab[b]!r} "
                    f"-> {vocab[new_id]!r} (count={best_count})"
                )

        self.merge_order = merge_order
        self._rebuild_derived()

    def _encode_chunk(self, chunk_bytes):
        seq = list(chunk_bytes)
        while len(seq) >= 2:
            pairs = set(zip(seq, seq[1:]))
            ranked = [(self.ranks[p], p) for p in pairs if p in self.ranks]
            if not ranked:
                break
            _, best_pair = min(ranked)
            seq = _merge_seq(seq, best_pair, self.merges[best_pair])
        return seq

    def encode(self, text):
        ids = []
        for chunk in _pretokenize(text):
            ids.extend(self._encode_chunk(chunk.encode("utf-8")))
        return ids

    def decode(self, ids, errors="replace"):
        """`errors='replace'` (the default) never raises: a byte sequence
        that doesn't land on valid UTF-8 boundaries (possible when decoding
        an arbitrary/model-sampled token sequence, as opposed to one that
        came from `encode()`) is rendered with U+FFFD instead of crashing --
        the same convention real BPE tokenizers use. `encode()` output always
        round-trips exactly regardless of this setting, since it always
        produces valid UTF-8 byte boundaries by construction."""
        byte_seq = b"".join(self.vocab[i] for i in ids)
        return byte_seq.decode("utf-8", errors=errors)

    def save(self, path):
        with open(path, "w") as f:
            json.dump({"merge_order": self.merge_order}, f)

    def load(self, path):
        with open(path) as f:
            data = json.load(f)
        self.merge_order = [tuple(p) for p in data["merge_order"]]
        self._rebuild_derived()
        return self
