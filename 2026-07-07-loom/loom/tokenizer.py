"""A from-scratch byte-level BPE (Byte Pair Encoding) tokenizer.

Operates over raw UTF-8 bytes (not Unicode codepoints or a fixed word
list), so any string - including punctuation/Unicode never seen during
training - round-trips through encode/decode exactly. There is no
`<unk>` token because there is nothing that falls outside the vocabulary:
worst case, a string just falls back to single raw bytes.
"""
import json
import re
from collections import Counter

# Split into words / whitespace-runs / punctuation-runs so merges never
# span a word boundary (the same reason GPT-2's tokenizer pre-splits).
_SPLIT_RE = re.compile(r"\w+|[^\w\s]+|\s+")


def _pre_tokenize(text):
    return _SPLIT_RE.findall(text)


class BPETokenizer:
    def __init__(self):
        self.merges = []            # list[(id_a, id_b)] in learned order
        self.vocab_bytes = {i: bytes([i]) for i in range(256)}  # id -> raw bytes
        self._ranks = {}            # pair -> merge rank, cached (see _merge_ranks)

    @property
    def vocab_size(self):
        return 256 + len(self.merges)

    def train(self, text, vocab_size, verbose=False):
        # An `assert` here would be stripped entirely under `python -O`,
        # silently training a smaller-than-requested (or, for vocab_size < 0,
        # a plain 256-token) tokenizer instead of rejecting bad input.
        if vocab_size < 256:
            raise ValueError(f"vocab_size must be >= 256 (the base byte vocab), got {vocab_size}")
        num_merges = vocab_size - 256

        word_counts = Counter(_pre_tokenize(text))
        splits = {w: list(w.encode("utf-8")) for w in word_counts}

        for merge_i in range(num_merges):
            pair_counts = Counter()
            for w, count in word_counts.items():
                ids = splits[w]
                for i in range(len(ids) - 1):
                    pair_counts[(ids[i], ids[i + 1])] += count

            if not pair_counts:
                break
            best_pair = max(pair_counts.items(), key=lambda kv: (kv[1], kv[0]))[0]
            new_id = 256 + merge_i
            self.merges.append(best_pair)
            self.vocab_bytes[new_id] = self.vocab_bytes[best_pair[0]] + self.vocab_bytes[best_pair[1]]

            for w in word_counts:
                ids = splits[w]
                if len(ids) < 2:
                    continue
                merged, i = [], 0
                while i < len(ids):
                    if i < len(ids) - 1 and ids[i] == best_pair[0] and ids[i + 1] == best_pair[1]:
                        merged.append(new_id)
                        i += 2
                    else:
                        merged.append(ids[i])
                        i += 1
                splits[w] = merged

            if verbose and (merge_i + 1) % 50 == 0:
                print(f"  merge {merge_i + 1}/{num_merges}: {best_pair} "
                      f"-> {new_id} (freq {pair_counts[best_pair]})")

        self._ranks = {pair: i for i, pair in enumerate(self.merges)}
        return self

    def encode(self, text):
        ranks = self._ranks
        out = []
        for w in _pre_tokenize(text):
            ids = list(w.encode("utf-8"))
            while len(ids) >= 2:
                pairs = [(ids[i], ids[i + 1]) for i in range(len(ids) - 1)]
                ranked = [(ranks[p], i) for i, p in enumerate(pairs) if p in ranks]
                if not ranked:
                    break
                _, idx = min(ranked)
                new_id = 256 + ranks[pairs[idx]]
                ids = ids[:idx] + [new_id] + ids[idx + 2:]
            out.extend(ids)
        return out

    def decode(self, ids):
        pieces = []
        for i in ids:
            i = int(i)
            if i not in self.vocab_bytes:
                raise ValueError(
                    f"token id {i} is outside this tokenizer's vocab "
                    f"(valid range is 0..{self.vocab_size - 1})")
            pieces.append(self.vocab_bytes[i])
        raw = b"".join(pieces)
        # Sequences produced by encode() on real text always concatenate to
        # valid UTF-8 (merges only ever group byte-aligned substrings), so
        # this is lossless for anything this tokenizer actually encoded.
        # But arbitrary token-id sequences - e.g. sampled from an untrained
        # or undertrained model - are not guaranteed to land on UTF-8
        # boundaries, so we fall back to U+FFFD replacement rather than
        # crash, exactly like production byte-level BPE decoders (GPT-2/
        # tiktoken) do.
        return raw.decode("utf-8", errors="replace")

    def save(self, path):
        with open(path, "w") as f:
            json.dump({"merges": self.merges}, f)

    @classmethod
    def load(cls, path):
        with open(path) as f:
            data = json.load(f)
        tok = cls()
        tok.merges = [tuple(p) for p in data["merges"]]
        for merge_i, pair in enumerate(tok.merges):
            new_id = 256 + merge_i
            tok.vocab_bytes[new_id] = tok.vocab_bytes[pair[0]] + tok.vocab_bytes[pair[1]]
        tok._ranks = {pair: i for i, pair in enumerate(tok.merges)}
        return tok
