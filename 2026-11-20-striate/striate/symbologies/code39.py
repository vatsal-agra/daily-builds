"""Code 39 (with optional mod-43 check character) and the narrow/wide pattern table."""
from .common import Barcode, EncodeError, widths_to_modules

# 9 elements, bar first, alternating bar/space. W = wide.
_RAW = """0 NNNWWNWNN|1 WNNWNNNNW|2 NNWWNNNNW|3 WNWWNNNNN|4 NNNWWNNNW|5 WNNWWNNNN|6 NNWWWNNNN|7 NNNWNNWNW
8 WNNWNNWNN|9 NNWWNNWNN|A WNNNNWNNW|B NNWNNWNNW|C WNWNNWNNN|D NNNNWWNNW|E WNNNWWNNN|F NNWNWWNNN
G NNNNNWWNW|H WNNNNWWNN|I NNWNNWWNN|J NNNNWWWNN|K WNNNNNNWW|L NNWNNNNWW|M WNWNNNNWN|N NNNNWNNWW
O WNNNWNNWN|P NNWNWNNWN|Q NNNNNNWWW|R WNNNNNWWN|S NNWNNNWWN|T NNNNWNWWN|U WWNNNNNNW|V NWWNNNNNW
W WWWNNNNNN|X NWNNWNNNW|Y WWNNWNNNN|Z NWWNWNNNN|- NWNNNNWNW|. WWNNNNWNN|_ NWWNNNWNN|* NWNNWNWNN
$ NWNWNWNNN|/ NWNWNNNWN|+ NWNNNWNWN|% NNNWNWNWN"""
PAT = {}
for item in _RAW.replace("\n", "|").split("|"):
    ch, p = item.split(" ")
    PAT["_" == ch and " " or ch] = p
CHARS = [c for c in PAT if c != "*"]          # the 43 data characters
CHECK_ORDER = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-. $/+%"
assert len(PAT) == 44 and len(set(PAT.values())) == 44
BY_PATTERN = {v: k for k, v in PAT.items()}
WIDE_RATIO = 3


def check_char(text):
    return CHECK_ORDER[sum(CHECK_ORDER.index(c) for c in text) % 43]


def _char_widths(ch):
    return [WIDE_RATIO if x == "W" else 1 for x in PAT[ch]]


def encode(text, mod43=False):
    t = text.upper()
    if not t:
        raise EncodeError("Code 39 cannot encode an empty string")
    for c in t:
        if c not in CHARS:
            raise EncodeError(f"character {c!r} is not in the Code 39 set (0-9 A-Z - . space $ / + %)")
    data = t + (check_char(t) if mod43 else "")
    widths = []
    for k, ch in enumerate(["*"] + list(data) + ["*"]):
        if k:
            widths.append(1)             # inter-character gap (a space)
        widths.extend(_char_widths(ch))
    return Barcode("Code 39", data, widths_to_modules(widths), quiet=10)
