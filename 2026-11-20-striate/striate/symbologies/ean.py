"""EAN-13, UPC-A and EAN-8."""
from .common import Barcode, EncodeError

L = ["0001101", "0011001", "0010011", "0111101", "0100011", "0110001", "0101111", "0111011", "0110111", "0001011"]
R = ["".join("1" if c == "0" else "0" for c in x) for x in L]
G = [x[::-1] for x in R]
PARITY = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG", "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"]
GUARD, CENTER = "101", "01010"


def check_digit(body):
    """GS1 mod-10 check digit for a digit string lacking its check digit."""
    total = 0
    for i, ch in enumerate(reversed(body)):
        total += int(ch) * (3 if i % 2 == 0 else 1)
    return str((10 - total % 10) % 10)


def _prep(text, body_len, name):
    t = text.strip()
    if not t.isascii() or not t.isdigit():
        raise EncodeError(f"{name} requires digits only")
    if len(t) == body_len:
        t += check_digit(t)
    elif len(t) == body_len + 1:
        if check_digit(t[:-1]) != t[-1]:
            raise EncodeError(f"{name}: bad check digit in {t!r} (expected {check_digit(t[:-1])})")
    else:
        raise EncodeError(f"{name} needs {body_len} or {body_len + 1} digits, got {len(t)}")
    return t


def _enc13(t13):
    par = PARITY[int(t13[0])]
    left = "".join((L if p == "L" else G)[int(d)] for p, d in zip(par, t13[1:7]))
    right = "".join(R[int(d)] for d in t13[7:])
    return GUARD + left + CENTER + right + GUARD


def encode_ean13(text):
    t = _prep(text, 12, "EAN-13")
    return Barcode("EAN-13", t, _enc13(t), quiet=11)


def encode_upca(text):
    t = _prep(text, 11, "UPC-A")
    return Barcode("UPC-A", t, _enc13("0" + t), quiet=9)


def encode_ean8(text):
    t = _prep(text, 7, "EAN-8")
    m = GUARD + "".join(L[int(d)] for d in t[:4]) + CENTER + "".join(R[int(d)] for d in t[4:]) + GUARD
    return Barcode("EAN-8", t, m, quiet=7)


def verify(text):
    return len(text) > 1 and text.isdigit() and check_digit(text[:-1]) == text[-1]
