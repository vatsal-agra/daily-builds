"""Character-level tokenizer. Deliberately the simplest possible tokenizer
(one id per Unicode codepoint seen in the training corpus) so the model's
entire job is to be a good sequence predictor over characters -- no BPE
merges hiding structure the Transformer would otherwise have to learn."""
import json


class CharTokenizer:
    def __init__(self, chars):
        self.chars = list(chars)
        self.stoi = {ch: i for i, ch in enumerate(self.chars)}
        self.itos = {i: ch for i, ch in enumerate(self.chars)}

    @classmethod
    def from_text(cls, text):
        return cls(sorted(set(text)))

    @property
    def vocab_size(self):
        return len(self.chars)

    def encode(self, text):
        try:
            return [self.stoi[c] for c in text]
        except KeyError as e:
            raise ValueError(f"character {e.args[0]!r} not in vocabulary") from None

    def decode(self, ids):
        return "".join(self.itos[int(i)] for i in ids)

    def to_dict(self):
        return {"chars": self.chars}

    @classmethod
    def from_dict(cls, d):
        return cls(d["chars"])

    def save(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False)

    @classmethod
    def load(cls, path):
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
