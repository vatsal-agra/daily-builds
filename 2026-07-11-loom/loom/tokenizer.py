"""Byte-level BPE tokenizer, trained from scratch on a corpus (GPT-2's
approach: start from the 256 raw byte values so any input -- including bytes
never seen in training -- always encodes/decodes exactly, then iteratively
merge the most frequent adjacent symbol pair)."""
import json
from collections import Counter


class ByteBPETokenizer:
    def __init__(self):
        # id -> bytes, for the base 256 byte vocab plus merges
        self.id_to_bytes = {i: bytes([i]) for i in range(256)}
        self.merges = []  # list of ((id1, id2), new_id) in the order they were learned
        self._merge_rank = {}  # (id1, id2) -> rank (lower = applied first)

    @property
    def vocab_size(self):
        return len(self.id_to_bytes)

    # -- training ---------------------------------------------------------
    def train(self, text, num_merges, verbose=False):
        """Learns `num_merges` BPE merges from `text` (a str, encoded to
        utf-8 bytes internally). Stops early if no pair occurs more than
        once (further merges wouldn't reduce anything)."""
        data = list(text.encode("utf-8"))
        if len(data) < 2:
            return

        for step in range(num_merges):
            pairs = Counter(zip(data, data[1:]))
            if not pairs:
                break
            best_pair, count = pairs.most_common(1)[0]
            if count < 2:
                break
            new_id = 256 + len(self.merges)
            self.id_to_bytes[new_id] = self.id_to_bytes[best_pair[0]] + self.id_to_bytes[best_pair[1]]
            self.merges.append((best_pair, new_id))
            self._merge_rank[best_pair] = step
            data = self._merge_sequence(data, best_pair, new_id)
            if verbose:
                print(f"merge {step + 1}/{num_merges}: {best_pair} -> {new_id} "
                      f"({self.id_to_bytes[new_id]!r}), count={count}")

        return data

    @staticmethod
    def _merge_sequence(seq, pair, new_id):
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

    # -- encode / decode ----------------------------------------------------
    def encode(self, text):
        """Encodes `text` (str) into a list of token ids. Correct even for
        text containing bytes/merges never seen during training (falls back
        to raw byte ids)."""
        ids = list(text.encode("utf-8"))
        if not ids:
            return ids
        for pair, new_id in self.merges:
            ids = self._merge_sequence(ids, pair, new_id)
        return ids

    def decode(self, ids):
        """Decodes a list of token ids back into the exact original str."""
        out = bytearray()
        for i in ids:
            out += self.id_to_bytes[i]
        return out.decode("utf-8", errors="replace")

    def decode_bytes(self, ids):
        out = bytearray()
        for i in ids:
            out += self.id_to_bytes[i]
        return bytes(out)

    # -- persistence ----------------------------------------------------
    def save(self, path):
        obj = {
            "merges": [[list(pair), new_id] for pair, new_id in self.merges],
        }
        with open(path, "w") as f:
            json.dump(obj, f)

    @classmethod
    def load(cls, path):
        with open(path) as f:
            obj = json.load(f)
        tok = cls()
        for (a, b), new_id in obj["merges"]:
            pair = (a, b)
            tok.id_to_bytes[new_id] = tok.id_to_bytes[a] + tok.id_to_bytes[b]
            tok.merges.append((pair, new_id))
            tok._merge_rank[pair] = len(tok.merges) - 1
        return tok
