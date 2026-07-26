"""Byte-level Byte-Pair-Encoding tokenizer, trained from scratch.

Base vocabulary is the 256 raw byte values, so encode/decode round-trips any
byte string exactly (including bytes never seen during training) — the same
guarantee GPT-2-style byte-level BPE gives. Merges are learned greedily by
repeatedly combining the most frequent adjacent symbol pair, counted over a
GPT-2-style pre-tokenization (so merges don't jump across "word" boundaries
in a way that hurts token quality).
"""
import json
import re
from collections import Counter

# GPT-2-style pretokenizer: keeps contrapositions like "'s"/"'t" whole, splits
# runs of letters / runs of digits / runs of punctuation, and treats a
# leading space as part of the following token. ASCII-only (fine for the
# training corpus here); non-ASCII bytes still tokenize correctly as raw
# byte tokens via the final `\s+|\S` fallback.
_PAT = re.compile(
    r"""'s|'t|'re|'ve|'m|'ll|'d| ?[A-Za-z]+| ?[0-9]+| ?[^\sA-Za-z0-9]+|\s+(?!\S)|\s+|\S"""
)


def _pretokenize(text):
    return _PAT.findall(text)


class BPETokenizer:
    """Byte-level BPE, trained from scratch (no external tokenizer library)."""

    def __init__(self):
        # id -> bytes, for the base 256 byte tokens plus every learned merge.
        self.id_to_bytes = [bytes([i]) for i in range(256)]
        # merges recorded in the order they were learned: (id_a, id_b) -> new_id
        self.merges = {}
        # rank of each merge (lower = learned earlier = applied first)
        self._merge_rank = {}

    @property
    def vocab_size(self):
        return len(self.id_to_bytes)

    def train(self, text, vocab_size, verbose=False):
        """Learn `vocab_size - 256` merges from `text`."""
        if vocab_size < 256:
            raise ValueError("vocab_size must be >= 256 (the byte-level base vocab)")
        num_merges = vocab_size - 256

        # Count unique "words" (pretokenized chunks) with their frequency,
        # each represented as a tuple of byte-token ids. Working on unique
        # words weighted by frequency is what makes training on a large
        # corpus tractable — merges are found once per pair, not once per
        # occurrence.
        word_freq = Counter(_pretokenize(text))
        words = {
            tuple(w.encode("utf-8")): freq for w, freq in word_freq.items()
        }

        for merge_i in range(num_merges):
            pair_counts = Counter()
            for word, freq in words.items():
                for a, b in zip(word, word[1:]):
                    pair_counts[(a, b)] += freq
            if not pair_counts:
                break
            best_pair = max(
                pair_counts.items(), key=lambda kv: (kv[1], -kv[0][0], -kv[0][1])
            )[0]
            new_id = len(self.id_to_bytes)
            self.id_to_bytes.append(
                self.id_to_bytes[best_pair[0]] + self.id_to_bytes[best_pair[1]]
            )
            self.merges[best_pair] = new_id
            self._merge_rank[best_pair] = merge_i

            new_words = {}
            for word, freq in words.items():
                merged = self._merge_word(word, best_pair, new_id)
                new_words[merged] = new_words.get(merged, 0) + freq
            words = new_words
            if verbose and (merge_i + 1) % 100 == 0:
                print(f"  merge {merge_i + 1}/{num_merges}: {best_pair} -> {new_id}")

    @staticmethod
    def _merge_word(word, pair, new_id):
        out = []
        i = 0
        n = len(word)
        while i < n:
            if i < n - 1 and (word[i], word[i + 1]) == pair:
                out.append(new_id)
                i += 2
            else:
                out.append(word[i])
                i += 1
        return tuple(out)

    def _encode_word(self, byte_ids):
        symbols = list(byte_ids)
        while len(symbols) > 1:
            # find the lowest-rank (earliest-learned) applicable merge
            best = None
            best_rank = None
            for i, (a, b) in enumerate(zip(symbols, symbols[1:])):
                rank = self._merge_rank.get((a, b))
                if rank is not None and (best_rank is None or rank < best_rank):
                    best_rank = rank
                    best = i
            if best is None:
                break
            a, b = symbols[best], symbols[best + 1]
            new_id = self.merges[(a, b)]
            symbols = symbols[:best] + [new_id] + symbols[best + 2 :]
        return symbols

    def encode(self, text):
        ids = []
        for word in _pretokenize(text):
            byte_ids = list(word.encode("utf-8"))
            ids.extend(self._encode_word(byte_ids))
        return ids

    def decode(self, ids):
        raw = b"".join(self.id_to_bytes[i] for i in ids)
        return raw.decode("utf-8", errors="replace")

    def save(self, path):
        merges_ordered = sorted(self.merges.items(), key=lambda kv: self._merge_rank[kv[0]])
        data = {
            "merges": [[a, b, new_id] for (a, b), new_id in merges_ordered],
        }
        with open(path, "w") as f:
            json.dump(data, f)

    @classmethod
    def load(cls, path):
        with open(path) as f:
            data = json.load(f)
        tok = cls()
        for a, b, new_id in data["merges"]:
            assert new_id == len(tok.id_to_bytes)
            tok.id_to_bytes.append(tok.id_to_bytes[a] + tok.id_to_bytes[b])
            tok.merges[(a, b)] = new_id
            tok._merge_rank[(a, b)] = len(tok._merge_rank)
        return tok
