"""Byte-level BPE tokenizer, trained from scratch (no external tokenizer library).

Operates directly on UTF-8 bytes so every possible input string is encodable
(no <unk> tokens, unlike word-level vocabularies). This is the same family of
algorithm GPT-2's tokenizer uses, minus the regex pre-tokenization step.
"""
import json


def _get_pair_counts(ids):
    counts = {}
    for a, b in zip(ids, ids[1:]):
        pair = (a, b)
        counts[pair] = counts.get(pair, 0) + 1
    return counts


def _merge_pair(ids, pair, new_id):
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


class BPETokenizer:
    def __init__(self):
        # merges: (id_a, id_b) -> new_id, in the order they were learned
        self.merges = {}
        # vocab: id -> raw bytes it expands to
        self.vocab = {i: bytes([i]) for i in range(256)}

    @property
    def vocab_size(self):
        return len(self.vocab)

    def train(self, text, vocab_size, verbose=False):
        if vocab_size < 256:
            raise ValueError("vocab_size must be >= 256 (one id per raw byte)")
        ids = list(text.encode("utf-8"))
        num_merges = vocab_size - 256
        merges = {}
        vocab = {i: bytes([i]) for i in range(256)}

        for i in range(num_merges):
            counts = _get_pair_counts(ids)
            if not counts:
                break
            pair = max(counts, key=counts.get)
            if counts[pair] < 2:
                break  # merging a pair that occurs once buys nothing
            new_id = 256 + i
            ids = _merge_pair(ids, pair, new_id)
            merges[pair] = new_id
            vocab[new_id] = vocab[pair[0]] + vocab[pair[1]]
            if verbose and (i % 50 == 0 or i == num_merges - 1):
                print(
                    f"  merge {i + 1}/{num_merges}: {pair} -> {new_id} "
                    f"({vocab[new_id]!r}, count={counts[pair]})"
                )

        self.merges = merges
        self.vocab = vocab
        return ids  # the fully-encoded training corpus, as a bonus

    def encode(self, text):
        ids = list(text.encode("utf-8"))
        if len(ids) < 2:
            return ids
        while True:
            counts = _get_pair_counts(ids)
            # of all mergeable pairs present, apply the one learned earliest
            pair = min(counts, key=lambda p: self.merges.get(p, float("inf")))
            if pair not in self.merges:
                break
            ids = _merge_pair(ids, pair, self.merges[pair])
            if len(ids) < 2:
                break
        return ids

    def decode(self, ids):
        raw = b"".join(self.vocab[i] for i in ids)
        return raw.decode("utf-8", errors="replace")

    def save(self, path):
        data = {
            "vocab_size": self.vocab_size,
            # JSON keys must be strings; encode merge pairs as "a,b"
            "merges": [[f"{a},{b}", new_id] for (a, b), new_id in self.merges.items()],
        }
        with open(path, "w") as f:
            json.dump(data, f)

    @classmethod
    def load(cls, path):
        with open(path) as f:
            data = json.load(f)
        tok = cls()
        vocab = {i: bytes([i]) for i in range(256)}
        merges = {}
        for pair_str, new_id in data["merges"]:
            a, b = (int(x) for x in pair_str.split(","))
            merges[(a, b)] = new_id
            vocab[new_id] = vocab[a] + vocab[b]
        tok.merges = merges
        tok.vocab = vocab
        return tok
