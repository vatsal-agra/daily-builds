"""Built-in test corpus generators — deterministic, no external files needed.

Covers the cases a compressor must not get wrong: empty, tiny, highly skewed,
highly repetitive, structured, natural-language-ish, and incompressible random.
"""
from __future__ import annotations

import random

_WORDS = (
    "the of and to in a is that it for as with was on are by be at this from or "
    "an but not you all can her was one our out has him his they she will would "
    "there their what about which when make like time just know take people year"
).split()


def english(n_words: int = 4000, seed: int = 7) -> bytes:
    """Pseudo-English: word salad with spaces and punctuation."""
    rng = random.Random(seed)
    out: list[str] = []
    for i in range(n_words):
        w = rng.choice(_WORDS)
        if i and rng.random() < 0.06:
            out.append(". " + w.capitalize())
        else:
            out.append(w)
    return (" ".join(out) + ".").encode()


def source_code(seed: int = 11) -> bytes:
    """Repetitive, structured text resembling source code."""
    rng = random.Random(seed)
    lines = []
    for i in range(600):
        kind = rng.random()
        if kind < 0.3:
            lines.append(f"    def method_{i}(self, x, y):")
        elif kind < 0.6:
            lines.append(f"        return self.value_{i % 17} + x * y")
        elif kind < 0.8:
            lines.append(f"    # comment about item {i} in the structure")
        else:
            lines.append("")
    return ("\n".join(lines)).encode()


def repetitive(seed: int = 13) -> bytes:
    rng = random.Random(seed)
    chunk = bytes(rng.randrange(256) for _ in range(40))
    return chunk * 500


def structured_binary(seed: int = 17) -> bytes:
    """Records with a few low-entropy fields and a counter."""
    rng = random.Random(seed)
    out = bytearray()
    for i in range(2000):
        out += (i & 0xFFFF).to_bytes(2, "little")
        out.append(rng.choice([0, 1, 2, 3, 255]))
        out += b"\x00\x00\x00"
    return bytes(out)


def random_bytes(n: int = 8000, seed: int = 19) -> bytes:
    rng = random.Random(seed)
    return bytes(rng.randrange(256) for _ in range(n))


def all_corpus() -> dict[str, bytes]:
    return {
        "empty": b"",
        "one-byte": b"Z",
        "all-same": b"x" * 4000,
        "english": english(),
        "source-code": source_code(),
        "repetitive": repetitive(),
        "structured-binary": structured_binary(),
        "random": random_bytes(),
        "256-bytes": bytes(range(256)),
    }
