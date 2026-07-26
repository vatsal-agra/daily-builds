"""Tokenizers. CharTokenizer is the baseline used by the required training
pipeline. BPETokenizer (byte-pair encoding, trained from scratch) is a
stretch feature living alongside it as a drop-in alternative."""
import numpy as np
from collections import Counter


class CharTokenizer:
    def __init__(self, text):
        chars = sorted(set(text))
        self.itos = {i: c for i, c in enumerate(chars)}
        self.stoi = {c: i for i, c in enumerate(chars)}
        self.vocab_size = len(chars)

    def encode(self, text):
        unknown = sorted(set(c for c in text if c not in self.stoi))
        if unknown:
            raise ValueError(
                f"character(s) {unknown!r} were never seen in the training corpus "
                f"and have no token id in this CharTokenizer's vocabulary"
            )
        return np.array([self.stoi[c] for c in text], dtype=np.int64)

    def decode(self, ids):
        return "".join(self.itos[int(i)] for i in ids)

    def token_str(self, token_id):
        return self.itos[int(token_id)]

    def to_dict(self):
        return {"kind": "char", "itos": {str(k): v for k, v in self.itos.items()}}

    @staticmethod
    def from_dict(d):
        tok = CharTokenizer.__new__(CharTokenizer)
        tok.itos = {int(k): v for k, v in d["itos"].items()}
        tok.stoi = {v: k for k, v in tok.itos.items()}
        tok.vocab_size = len(tok.itos)
        return tok


class BPETokenizer:
    """Byte-level BPE, trained from scratch (no tiktoken/sentencepiece).

    Operates on raw UTF-8 bytes (0-255 base vocab) so it can encode any
    text without an "unknown token" fallback, then greedily merges the
    most frequent adjacent byte-pair into a new token id, repeated
    `num_merges` times -- exactly the algorithm behind GPT-2's tokenizer.
    """

    def __init__(self):
        self.merges = {}          # (a, b) -> new_id, in learned order
        self.ranks = {}           # (a, b) -> rank (lower = merge earlier)
        self.vocab = {i: bytes([i]) for i in range(256)}  # id -> raw bytes
        self.vocab_size = 256

    @staticmethod
    def _pair_counts(ids):
        counts = Counter()
        for a, b in zip(ids, ids[1:]):
            counts[(a, b)] += 1
        return counts

    @staticmethod
    def _apply_merge(ids, pair, new_id):
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
        return out

    def train(self, text, num_merges):
        ids = list(text.encode("utf-8"))
        merges = {}
        vocab = {i: bytes([i]) for i in range(256)}
        for i in range(num_merges):
            counts = self._pair_counts(ids)
            if not counts:
                break
            best = max(counts, key=counts.get)
            new_id = 256 + i
            ids = self._apply_merge(ids, best, new_id)
            merges[best] = new_id
            vocab[new_id] = vocab[best[0]] + vocab[best[1]]
        self.merges = merges
        self.ranks = {pair: rank for rank, pair in enumerate(merges.keys())}
        self.vocab = vocab
        self.vocab_size = len(vocab)
        return np.array(ids, dtype=np.int64)

    def encode(self, text):
        ids = list(text.encode("utf-8"))
        while len(ids) >= 2:
            counts = self._pair_counts(ids)
            candidate = min(counts, key=lambda p: self.ranks.get(p, float("inf")))
            if candidate not in self.ranks:
                break
            ids = self._apply_merge(ids, candidate, self.merges[candidate])
        return np.array(ids, dtype=np.int64)

    def decode(self, ids):
        byte_seq = b"".join(self.vocab[int(i)] for i in ids)
        return byte_seq.decode("utf-8", errors="replace")

    def token_str(self, token_id):
        return self.vocab[int(token_id)].decode("utf-8", errors="replace")

    def to_dict(self):
        return {
            "kind": "bpe",
            "merges": [[list(k), v] for k, v in self.merges.items()],
            "vocab_size": self.vocab_size,
        }

    @staticmethod
    def from_dict(d):
        tok = BPETokenizer.__new__(BPETokenizer)
        tok.merges = {}
        tok.vocab = {i: bytes([i]) for i in range(256)}
        for pair, new_id in d["merges"]:
            key = tuple(pair)
            tok.merges[key] = new_id
            tok.vocab[new_id] = tok.vocab[key[0]] + tok.vocab[key[1]]
        tok.ranks = {pair: rank for rank, pair in enumerate(tok.merges.keys())}
        tok.vocab_size = d["vocab_size"]
        return tok


def tokenizer_from_dict(d):
    if d["kind"] == "char":
        return CharTokenizer.from_dict(d)
    if d["kind"] == "bpe":
        return BPETokenizer.from_dict(d)
    raise ValueError(f"unknown tokenizer kind: {d['kind']!r}")
