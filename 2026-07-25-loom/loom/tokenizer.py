"""
From-scratch byte-level BPE tokenizer.

Base vocabulary is the 256 raw byte values plus one special token
`<EOT>` (end-of-text, id 256) used to mark fable boundaries. Training
learns merge rules directly from the corpus, exactly as GPT-2's tokenizer
does, using the standard efficient algorithm: track pair frequencies
across all pre-tokenized "words", and when merging the most frequent
pair, only rescan the words that actually contained it.

Pre-tokenization splits on whitespace boundaries (keeping the leading
whitespace attached to the following word, GPT-2 style) so merges never
cross a word boundary — this keeps training tractable and keeps the
learned vocabulary meaningful (whole common words become single tokens).
"""
import json
import re

EOT_ID = 256
BASE_VOCAB_SIZE = 257  # 256 byte values + EOT

_PRETOKEN_RE = re.compile(r"\s*\S+|\s+")


def _pretokenize(text):
    return _PRETOKEN_RE.findall(text)


class BPETokenizer:
    def __init__(self):
        # merges: list of ((a, b), new_id) in the order they were learned
        self.merges = []
        # rank[(a, b)] = order index, lower = merge earlier (higher priority)
        self.rank = {}
        self.vocab_size = BASE_VOCAB_SIZE

    # ---------------------------------------------------------------- train
    def train(self, text, target_vocab_size, verbose=False):
        words = _pretokenize(text)
        # each word -> list of byte ids
        seqs = [list(w.encode("utf-8")) for w in words]

        pair_count = {}
        pair_to_words = {}  # pair -> set of word indices containing it

        def add_word_pairs(wi, seq):
            for i in range(len(seq) - 1):
                p = (seq[i], seq[i + 1])
                pair_count[p] = pair_count.get(p, 0) + 1
                pair_to_words.setdefault(p, set()).add(wi)

        for wi, seq in enumerate(seqs):
            add_word_pairs(wi, seq)

        next_id = BASE_VOCAB_SIZE
        n_merges = target_vocab_size - BASE_VOCAB_SIZE
        if n_merges < 0:
            raise ValueError("target_vocab_size must be >= base vocab size (257)")

        for step in range(n_merges):
            if not pair_count:
                break
            best_pair = max(pair_count.items(), key=lambda kv: (kv[1], -kv[0][0], -kv[0][1]))[0]
            best_count = pair_count[best_pair]
            if best_count < 2:
                break

            new_id = next_id
            next_id += 1
            self.merges.append((best_pair, new_id))
            self.rank[best_pair] = len(self.rank)

            affected = list(pair_to_words.get(best_pair, ()))
            for wi in affected:
                seq = seqs[wi]
                # remove this word's old pair contributions
                for i in range(len(seq) - 1):
                    p = (seq[i], seq[i + 1])
                    pair_count[p] -= 1
                    if pair_count[p] <= 0:
                        del pair_count[p]
                        pair_to_words.pop(p, None)

                # apply the merge
                merged = []
                i = 0
                a, b = best_pair
                while i < len(seq):
                    if i < len(seq) - 1 and seq[i] == a and seq[i + 1] == b:
                        merged.append(new_id)
                        i += 2
                    else:
                        merged.append(seq[i])
                        i += 1
                seqs[wi] = merged

                # re-add this word's new pair contributions
                add_word_pairs(wi, merged)

            pair_count.pop(best_pair, None)
            pair_to_words.pop(best_pair, None)

            if verbose and step % 50 == 0:
                print(f"  merge {step}/{n_merges}: {best_pair} -> {new_id} (count {best_count})")

        self.vocab_size = next_id

    # --------------------------------------------------------------- encode
    def _encode_word(self, seq):
        seq = list(seq)
        if not self.rank:
            return seq
        while len(seq) > 1:
            best = None
            best_rank = None
            for i in range(len(seq) - 1):
                p = (seq[i], seq[i + 1])
                r = self.rank.get(p)
                if r is not None and (best_rank is None or r < best_rank):
                    best_rank = r
                    best = i
            if best is None:
                break
            new_id = None
            for (pa, pb), nid in self.merges:
                if (pa, pb) == (seq[best], seq[best + 1]):
                    new_id = nid
                    break
            seq = seq[:best] + [new_id] + seq[best + 2:]
        return seq

    def encode(self, text, add_eot=False):
        ids = []
        for word in _pretokenize(text):
            ids.extend(self._encode_word(list(word.encode("utf-8"))))
        if add_eot:
            ids.append(EOT_ID)
        return ids

    # --------------------------------------------------------------- decode
    def decode(self, ids):
        # expand merges back down to raw byte ids
        merge_by_id = {nid: pair for pair, nid in self.merges}

        def expand(tok):
            if tok < 256:
                return [tok]
            if tok == EOT_ID:
                return []
            a, b = merge_by_id[tok]
            return expand(a) + expand(b)

        raw = []
        for tok in ids:
            raw.extend(expand(tok))
        return bytes(raw).decode("utf-8", errors="replace")

    # ------------------------------------------------------------- persist
    def save(self, path):
        with open(path, "w") as f:
            json.dump({
                "vocab_size": self.vocab_size,
                "merges": [[list(pair), nid] for pair, nid in self.merges],
            }, f)

    @classmethod
    def load(cls, path):
        with open(path) as f:
            data = json.load(f)
        tok = cls()
        tok.vocab_size = data["vocab_size"]
        tok.merges = [(tuple(pair), nid) for pair, nid in data["merges"]]
        tok.rank = {pair: i for i, (pair, _nid) in enumerate(tok.merges)}
        return tok
