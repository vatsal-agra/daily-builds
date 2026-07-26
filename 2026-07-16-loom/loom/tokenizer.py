"""A byte-level BPE (byte-pair encoding) tokenizer, trained from scratch.

Algorithm (Sennrich et al. 2016, byte-level variant as in GPT-2):
  1. Pre-split the text into chunks (word-ish/punctuation-ish/whitespace-ish
     runs) so merges never cross e.g. a word boundary into surrounding
     whitespace.
  2. Represent each chunk as a tuple of its raw UTF-8 byte values (0-255).
  3. Repeatedly find the most frequent adjacent byte-pair across the whole
     corpus (weighted by chunk frequency) and merge it into a new token id,
     recording the merge rule. Stop at the target vocab size.

Because the base alphabet is the 256 possible byte values, *any* input
(any unicode text, even malformed byte sequences) can always be encoded,
and decoding is always an exact byte-for-byte inverse of encoding.
"""
from __future__ import annotations

import json
import re
from collections import Counter

_SPLIT_RE = re.compile(r"\w+|[^\w\s]+|\s+")


def _chunks(text: str):
    return _SPLIT_RE.findall(text)


class BPETokenizer:
    def __init__(self):
        self.merges: list[tuple[int, int]] = []      # in learned order == rank order
        self.merge_rank: dict[tuple[int, int], int] = {}
        self.id_bytes: dict[int, bytes] = {i: bytes([i]) for i in range(256)}

    @property
    def vocab_size(self) -> int:
        return 256 + len(self.merges)

    # ---- training ---------------------------------------------------------
    def train(self, text: str, vocab_size: int, verbose: bool = False) -> None:
        if vocab_size < 256:
            raise ValueError("vocab_size must be >= 256 (the byte alphabet)")
        words = Counter(tuple(chunk.encode("utf-8")) for chunk in _chunks(text))

        target_merges = vocab_size - 256
        self.merges = []
        self.merge_rank = {}
        self.id_bytes = {i: bytes([i]) for i in range(256)}

        for step in range(target_merges):
            pair_counts = Counter()
            for word, freq in words.items():
                for a, b in zip(word, word[1:]):
                    pair_counts[(a, b)] += freq
            if not pair_counts:
                break
            best_pair, best_count = max(pair_counts.items(), key=lambda kv: kv[1])
            if best_count < 2:
                break  # merging singletons doesn't generalize; stop early

            new_id = 256 + step
            self.merges.append(best_pair)
            self.merge_rank[best_pair] = step
            self.id_bytes[new_id] = self.id_bytes[best_pair[0]] + self.id_bytes[best_pair[1]]

            new_words = Counter()
            for word, freq in words.items():
                new_words[_merge_word(word, best_pair, new_id)] += freq
            words = new_words
            if verbose and (step % 25 == 0 or step == target_merges - 1):
                merged_text = self.id_bytes[new_id].decode("utf-8", errors="replace")
                print(f"  merge {step + 1}/{target_merges}: {best_pair} -> {new_id} "
                      f"({best_count}x) = {merged_text!r}")

    # ---- encode / decode ---------------------------------------------------
    def encode(self, text: str) -> list[int]:
        ids: list[int] = []
        for chunk in _chunks(text):
            word = list(chunk.encode("utf-8"))
            while len(word) >= 2:
                pairs = list(zip(word, word[1:]))
                ranked = [(self.merge_rank[p], i) for i, p in enumerate(pairs) if p in self.merge_rank]
                if not ranked:
                    break
                _, i = min(ranked)
                a, b = word[i], word[i + 1]
                new_id = 256 + self.merge_rank[(a, b)]
                word = word[:i] + [new_id] + word[i + 2:]
            ids.extend(word)
        return ids

    def decode(self, ids: list[int]) -> str:
        raw = b"".join(self.id_bytes[i] for i in ids)
        return raw.decode("utf-8", errors="replace")

    # ---- persistence --------------------------------------------------------
    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump({"merges": self.merges}, f)

    @classmethod
    def load(cls, path: str) -> "BPETokenizer":
        with open(path) as f:
            data = json.load(f)
        tok = cls()
        for step, pair in enumerate(data["merges"]):
            a, b = pair
            new_id = 256 + step
            tok.merges.append((a, b))
            tok.merge_rank[(a, b)] = step
            tok.id_bytes[new_id] = tok.id_bytes[a] + tok.id_bytes[b]
        return tok


def _merge_word(word: tuple[int, ...], pair: tuple[int, int], new_id: int) -> tuple[int, ...]:
    a, b = pair
    out = []
    i = 0
    n = len(word)
    while i < n:
        if i < n - 1 and word[i] == a and word[i + 1] == b:
            out.append(new_id)
            i += 2
        else:
            out.append(word[i])
            i += 1
    return tuple(out)
