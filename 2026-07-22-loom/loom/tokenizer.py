"""A from-scratch byte-level BPE (byte-pair encoding) tokenizer.

Trains directly on the UTF-8 bytes of the corpus (the same base representation
GPT-2's tokenizer uses), so every possible input -- any language, emoji,
typo, whatever -- has an exact, lossless encoding: worst case it falls back
to individual bytes. No pretokenizer/regex splitting is used, so merges are
free to cross whitespace boundaries; that's a simplification relative to
GPT-2's tokenizer, traded for a much smaller implementation, and is noted
in the README.
"""

import json


class BPETokenizer:
    def __init__(self):
        self.merges_list = []  # ordered list of (a, b) pairs, in the order they were learned
        self.merges = {}       # (a, b) -> new_id
        self.vocab = {i: bytes([i]) for i in range(256)}  # id -> bytes

    @property
    def vocab_size(self):
        return 256 + len(self.merges_list)

    @staticmethod
    def _count_pairs(ids):
        counts = {}
        for a, b in zip(ids, ids[1:]):
            counts[(a, b)] = counts.get((a, b), 0) + 1
        return counts

    @staticmethod
    def _merge(ids, pair, new_id):
        merged = []
        i = 0
        n = len(ids)
        while i < n:
            if i < n - 1 and ids[i] == pair[0] and ids[i + 1] == pair[1]:
                merged.append(new_id)
                i += 2
            else:
                merged.append(ids[i])
                i += 1
        return merged

    def train(self, text, vocab_size, verbose=False):
        assert vocab_size >= 256, "vocab_size must be at least 256 (the raw byte alphabet)"
        ids = list(text.encode("utf-8"))
        num_merges = vocab_size - 256
        for i in range(num_merges):
            counts = self._count_pairs(ids)
            if not counts:
                break
            best_pair = max(counts, key=counts.get)
            if counts[best_pair] < 2:
                break  # merging a pair that occurs once buys nothing
            new_id = 256 + len(self.merges_list)
            ids = self._merge(ids, best_pair, new_id)
            self.merges_list.append(best_pair)
            self.merges[best_pair] = new_id
            self.vocab[new_id] = self.vocab[best_pair[0]] + self.vocab[best_pair[1]]
            if verbose and (i + 1) % 50 == 0:
                print(f"  merge {i + 1}/{num_merges}: {best_pair} -> {new_id} "
                      f"({self.vocab[new_id]!r}, count={counts[best_pair]})")
        return ids

    def encode(self, text):
        ids = list(text.encode("utf-8"))
        while len(ids) >= 2:
            pairs = set(zip(ids, ids[1:]))
            candidate = min(pairs, key=lambda p: self.merges.get(p, float("inf")))
            if candidate not in self.merges:
                break
            ids = self._merge(ids, candidate, self.merges[candidate])
        return ids

    def decode(self, ids):
        raw = b"".join(self.vocab[i] for i in ids)
        return raw.decode("utf-8", errors="replace")

    def save(self, path):
        with open(path, "w") as f:
            json.dump({"merges": self.merges_list}, f)

    @classmethod
    def load(cls, path):
        with open(path) as f:
            data = json.load(f)
        tok = cls()
        for a, b in data["merges"]:
            new_id = 256 + len(tok.merges_list)
            tok.merges_list.append((a, b))
            tok.merges[(a, b)] = new_id
            tok.vocab[new_id] = tok.vocab[a] + tok.vocab[b]
        return tok
