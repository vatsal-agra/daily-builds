"""From-scratch byte-pair-encoding tokenizer (GPT-2 style).

Text is pre-split into "word" chunks with a regex, byte-pair merges are
learned over the *unique* word set weighted by frequency (not by scanning
the raw corpus on every merge -- that's what makes training on a
megabyte-scale corpus tractable in pure Python), and encoding replays the
learned merges in rank order. Because the base vocabulary is the 256 raw
bytes, any input -- including text never seen during training -- can
always be encoded: unmerged bytes simply fall back to single-byte tokens.
"""
import json
import re
from collections import Counter

_PATTERN = re.compile(
    r"'s|'t|'re|'ve|'m|'ll|'d| ?[A-Za-z]+| ?[0-9]+| ?[^\sA-Za-z0-9]+|\s+"
)


def _split_words(text):
    return _PATTERN.findall(text)


def _merge_word(ids, pair, new_id):
    out = []
    i = 0
    n = len(ids)
    while i < n:
        if i < n - 1 and ids[i] == pair[0] and ids[i + 1] == pair[1]:
            out.append(new_id)
            i += 2
        else:
            out.append(ids[i])
            i += 1
    return tuple(out)


class BPETokenizer:
    def __init__(self):
        self.merges = {}          # (id, id) -> new_id
        self.merge_order = []     # [(id, id), ...] in learned order
        self.rank = {}            # (id, id) -> priority (lower = earlier/preferred)
        self.vocab = {i: bytes([i]) for i in range(256)}  # id -> bytes
        self._word_cache = {}

    @property
    def vocab_size(self):
        return 256 + len(self.merge_order)

    def train(self, text, vocab_size, verbose=False):
        if vocab_size < 256:
            raise ValueError("vocab_size must be >= 256 (the byte base vocab)")
        num_merges = vocab_size - 256

        word_counts = Counter(_split_words(text))
        word_ids = {}
        for w, c in word_counts.items():
            ids = tuple(w.encode("utf-8"))
            word_ids[ids] = word_ids.get(ids, 0) + c

        for i in range(num_merges):
            pair_counts = Counter()
            for ids, cnt in word_ids.items():
                for a, b in zip(ids, ids[1:]):
                    pair_counts[(a, b)] += cnt
            if not pair_counts:
                break
            best = max(pair_counts.items(), key=lambda kv: kv[1])[0]
            new_id = 256 + i
            self.merges[best] = new_id
            self.merge_order.append(best)
            self.rank[best] = i
            self.vocab[new_id] = self.vocab[best[0]] + self.vocab[best[1]]

            new_word_ids = {}
            for ids, cnt in word_ids.items():
                merged = _merge_word(ids, best, new_id) if best[0] in ids or best[1] in ids else ids
                new_word_ids[merged] = new_word_ids.get(merged, 0) + cnt
            word_ids = new_word_ids

            if verbose and (i + 1) % 50 == 0:
                print(f"  merge {i + 1}/{num_merges}: {best} -> {new_id} "
                      f"({self.vocab[new_id]!r})")

        self._word_cache = {}

    def _encode_word(self, w):
        cached = self._word_cache.get(w)
        if cached is not None:
            return list(cached)
        ids = list(w.encode("utf-8"))
        while len(ids) >= 2:
            pairs = list(zip(ids, ids[1:]))
            best_idx, best_rank = None, None
            for i, p in enumerate(pairs):
                r = self.rank.get(p)
                if r is not None and (best_rank is None or r < best_rank):
                    best_idx, best_rank = i, r
            if best_idx is None:
                break
            pair = pairs[best_idx]
            new_id = self.merges[pair]
            ids = ids[:best_idx] + [new_id] + ids[best_idx + 2:]
        self._word_cache[w] = tuple(ids)
        return ids

    def encode(self, text):
        out = []
        for w in _split_words(text):
            out.extend(self._encode_word(w))
        return out

    def decode(self, ids):
        b = b"".join(self.vocab[i] for i in ids)
        return b.decode("utf-8", errors="replace")

    def save(self, path):
        with open(path, "w") as f:
            json.dump({"merges": [list(p) for p in self.merge_order]}, f)

    @classmethod
    def load(cls, path):
        with open(path) as f:
            data = json.load(f)
        tok = cls()
        for i, (a, b) in enumerate(data["merges"]):
            pair = (a, b)
            new_id = 256 + i
            tok.merges[pair] = new_id
            tok.merge_order.append(pair)
            tok.rank[pair] = i
            tok.vocab[new_id] = tok.vocab[a] + tok.vocab[b]
        return tok
