"""Code 128 (subsets A/B/C) — encoder with optimal subset switching, plus symbol-value decoding."""
from .common import Barcode, EncodeError, widths_to_modules

FNC1 = "\xf1"   # in-band marker for FNC1 (both for encoding input and decoded output)

PATTERNS = """212222 222122 222221 121223 121322 131222 122213 122312 132212 221213
221312 231212 112232 122132 122231 113222 123122 123221 223211 221132
221231 213212 223112 312131 311222 321122 321221 312212 322112 322211
212123 212321 232121 111323 131123 131321 112313 132113 132311 211313
231113 231311 112133 112331 132131 113123 113321 133121 313121 211331
231131 213113 213311 213131 311123 311321 331121 312113 312311 332111
314111 221411 431111 111224 111422 121124 121421 141122 141221 112214
112412 122114 122411 142112 142211 241211 221114 413111 241112 134111
111242 121142 121241 114212 124112 124211 411212 421112 421211 212141
214121 412121 111143 111341 131141 114113 114311 411113 411311 113141
114131 311141 411131 211412 211214 211232 2331112""".split()
TABLE = [tuple(int(c) for c in p) for p in PATTERNS]
assert len(TABLE) == 107
START_A, START_B, START_C, STOP = 103, 104, 105, 106
CODE_A, CODE_B, CODE_C, SHIFT = 101, 100, 99, 98   # as encoded in the *current* set (see below)
# value meaning differs per set:
#  A: 98 SHIFT 99 CODE_C 100 CODE_B 101 FNC4 102 FNC1
#  B: 98 SHIFT 99 CODE_C 100 FNC4 101 CODE_A 102 FNC1
#  C: 100 CODE_B 101 CODE_A 102 FNC1


def _val_in_set(ch, s):
    """Value of single char ch in set 'A'/'B', or None."""
    o = ord(ch)
    if ch == FNC1:
        return 102
    if s == "A":
        if 32 <= o <= 95:
            return o - 32
        if 0 <= o <= 31:
            return o + 64
    elif s == "B":
        if 32 <= o <= 127:
            return o - 32
    return None


def _tokens(text):
    return list(text)


def checksum(values):
    """Mod-103 checksum over [start, data...]."""
    total = values[0]
    for i, v in enumerate(values[1:], 1):
        total += i * v
    return total % 103


def encode_values(text):
    """Return list of symbol values (start..data, no checksum/stop) using the minimum symbol count."""
    toks = _tokens(text)
    n = len(toks)
    if n == 0:
        raise EncodeError("Code 128 cannot encode an empty string")
    for ch in toks:
        if ord(ch) > 127 and ch != FNC1:
            raise EncodeError(f"character {ch!r} (U+{ord(ch):04X}) is not encodable in Code 128 (ASCII 0-127 only)")
    INF = 10 ** 9
    # best[i][s] = (cost, back) to have consumed i tokens and be in set s (A/B/C), start code counted.
    best = [{s: (INF, None) for s in "ABC"} for _ in range(n + 1)]
    for s in "ABC":
        best[0][s] = (1, ("start", None))

    def relax(i, s, cost, back):
        if cost < best[i][s][0]:
            best[i][s] = (cost, back)

    for i in range(n + 1):
        # code switches (cost 1) — iterate to a fixpoint within the same position
        for _ in range(2):
            for s in "ABC":
                c = best[i][s][0]
                if c >= INF:
                    continue
                for t in "ABC":
                    if t != s:
                        relax(i, t, c + 1, ("switch", s))
        if i == n:
            break
        ch = toks[i]
        for s in "ABC":
            c = best[i][s][0]
            if c >= INF:
                continue
            if s in "AB":
                if _val_in_set(ch, s) is not None:
                    relax(i + 1, s, c + 1, ("char", s))
                else:
                    other = "B" if s == "A" else "A"
                    if _val_in_set(ch, other) is not None:
                        relax(i + 1, s, c + 2, ("shift", s))
            else:
                if ch == FNC1:
                    relax(i + 1, "C", c + 1, ("char", "C"))
                elif ch.isdigit() and ch.isascii() and i + 1 < n and toks[i + 1].isdigit() and toks[i + 1].isascii():
                    relax(i + 2, "C", c + 1, ("pair", "C"))
    # pick end
    s_end = min("ABC", key=lambda s: (best[n][s][0], s != "C"))
    # backtrack into ops
    ops, i, s = [], n, s_end
    while True:
        cost, back = best[i][s]
        kind = back[0]
        if kind == "start":
            ops.append(("start", s)); break
        if kind == "switch":
            ops.append(("switch", back[1], s)); s = back[1]
        elif kind == "char":
            ops.append(("char", s, i - 1)); i -= 1
        elif kind == "shift":
            ops.append(("shift", s, i - 1)); i -= 1
        elif kind == "pair":
            ops.append(("pair", s, i - 2)); i -= 2
    ops.reverse()
    vals = []
    for op in ops:
        k = op[0]
        if k == "start":
            vals.append({"A": START_A, "B": START_B, "C": START_C}[op[1]])
        elif k == "switch":
            frm, to = op[1], op[2]
            if to == "C":
                vals.append(99)
            elif to == "B":
                vals.append(100)    # CODE B from A or C
            else:
                vals.append(101)    # CODE A from B or C
        elif k == "char":
            s, idx = op[1], op[2]
            vals.append(102 if toks[idx] == FNC1 else (_val_in_set(toks[idx], s)))
        elif k == "shift":
            s, idx = op[1], op[2]
            other = "B" if s == "A" else "A"
            vals.append(98)
            vals.append(_val_in_set(toks[idx], other))
        elif k == "pair":
            idx = op[2]
            vals.append(int(toks[idx] + toks[idx + 1]))
    return vals


def encode(text):
    vals = encode_values(text)
    vals.append(checksum(vals))
    vals.append(STOP)
    widths = []
    for v in vals:
        widths.extend(TABLE[v])
    return Barcode("Code 128", text, widths_to_modules(widths), quiet=10)


def decode_values(vals):
    """vals = [start, data..., (no checksum), (no stop)] -> text (FNC1 as '\\xf1'). Raises ValueError."""
    if not vals or vals[0] not in (START_A, START_B, START_C):
        raise ValueError("no start code")
    s = {START_A: "A", START_B: "B", START_C: "C"}[vals[0]]
    out, shift_next, i = [], None, 1
    while i < len(vals):
        v = vals[i]; i += 1
        cur = shift_next or s
        shift_next = None
        if cur == "C":
            if v <= 99:
                out.append(f"{v:02d}")
            elif v == 100:
                s = "B"
            elif v == 101:
                s = "A"
            elif v == 102:
                out.append(FNC1)
            else:
                raise ValueError("bad value in set C")
            continue
        if v == 98:
            shift_next = "B" if cur == "A" else "A"
            continue
        if v == 99:
            s = "C"; continue
        if cur == "A":
            if v == 100:
                s = "B"
            elif v == 101 or v in (96, 97):
                if v == 101:
                    pass  # FNC4 — extended ASCII not supported; ignored (rare)
            elif v == 102:
                out.append(FNC1)
            elif v < 64:
                out.append(chr(v + 32))
            elif v < 96:
                out.append(chr(v - 64))
            else:
                raise ValueError("bad value in set A")
        else:
            if v == 101:
                s = "A"
            elif v == 100 or v in (96, 97):
                pass
            elif v == 102:
                out.append(FNC1)
            elif v < 96:
                out.append(chr(v + 32))
            else:
                raise ValueError("bad value in set B")
    return "".join(out)
