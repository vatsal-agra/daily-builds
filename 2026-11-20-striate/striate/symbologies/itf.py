"""Interleaved 2 of 5 (ITF)."""
from .common import Barcode, EncodeError, widths_to_modules

PAT = ["NNWWN", "WNNNW", "NWNNW", "WWNNN", "NNWNW", "WNWNN", "NWWNN", "NNNWW", "WNNWN", "NWNWN"]
BY_PATTERN = {p: i for i, p in enumerate(PAT)}
W = 3


def mod10(digits):
    total = 0
    for i, c in enumerate(reversed(digits)):
        total += int(c) * (3 if i % 2 == 0 else 1)
    return str((10 - total % 10) % 10)


def encode(text, check=False):
    t = text.strip()
    if not t.isascii() or not t.isdigit():
        raise EncodeError("ITF requires digits only")
    if check:
        t += mod10(t)
    if len(t) % 2:
        raise EncodeError(f"ITF needs an even number of digits (got {len(t)}); use check=True or pad with a leading 0")
    widths = [1, 1, 1, 1]
    for i in range(0, len(t), 2):
        a, b = PAT[int(t[i])], PAT[int(t[i + 1])]
        for x, y in zip(a, b):
            widths.append(W if x == "W" else 1)   # bar from first digit
            widths.append(W if y == "W" else 1)   # space from second digit
    widths.extend([W, 1, 1])
    return Barcode("ITF", t, widths_to_modules(widths), quiet=10)
