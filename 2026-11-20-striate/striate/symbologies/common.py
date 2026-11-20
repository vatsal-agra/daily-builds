"""Shared types + the element-matching primitive used by module-based decoders."""
from dataclasses import dataclass


class EncodeError(ValueError):
    """Raised when text cannot be represented in the requested symbology."""


@dataclass
class Barcode:
    symbology: str
    text: str            # the human-readable / data text (check digits included)
    modules: str         # '1' = bar module, '0' = space module; quiet zones NOT included
    quiet: int = 10      # recommended quiet-zone width in modules (each side)

    def runs(self):
        """Alternating run lengths in modules, first run is a bar."""
        out, prev, n = [], "1", 0
        for ch in self.modules:
            if ch == prev:
                n += 1
            else:
                out.append(n); prev = ch; n = 1
        out.append(n)
        return out


def widths_to_modules(widths):
    """Alternating widths (bar first) -> '1'/'0' module string."""
    return "".join(("1" if i % 2 == 0 else "0") * int(w) for i, w in enumerate(widths))


def match_char(w, table, total, gain=0.0, sign0=1):
    """Match k measured element widths (px) against a table of module-width patterns.

    `gain` is the ink gain in px: bars print `gain` wider and spaces `gain` narrower than
    nominal, so each element is corrected by -sign*gain before comparison (sign0 = +1 if the
    first element is a bar, -1 if a space). Note that comparing only adjacent-pair sums
    (gain-invariant) is NOT enough — e.g. EAN L2 (2,1,2,2) and (1,2,1,3) have equal pair sums —
    so gain must be estimated explicitly (see fit_gain) and carried along the symbol.

    Returns (index, error, second_best_error, residual_gain_px); errors are squared modules.
    """
    k = len(w)
    c = [w[i] - (sign0 if i % 2 == 0 else -sign0) * gain for i in range(k)]
    s = sum(c)
    if s <= 0:
        return -1, 1e9, 1e9, 0.0
    scale = s / total
    r = [x / scale for x in c]
    best, be, se = -1, 1e9, 1e9
    for idx, p in enumerate(table):
        e = 0.0
        for i in range(k):
            d = r[i] - p[i]
            e += d * d
        if e < be:
            best, se, be = idx, be, e
        elif e < se:
            se = e
    resid = 0.0
    if best >= 0:
        p = table[best]
        resid = sum((sign0 if i % 2 == 0 else -sign0) * (r[i] - p[i]) for i in range(k)) / k * scale
    return best, be, se, resid


def fit_gain(w, table, total, sign0=1):
    """Best (index, error, gain_px) over `table` with the ink gain free-fitted per pattern."""
    k = len(w)
    s = sum(w)
    if s <= 0:
        return -1, 1e9, 0.0
    m = s / total
    sg = [(sign0 if i % 2 == 0 else -sign0) for i in range(k)]
    best, be, bg = -1, 1e9, 0.0
    for idx, p in enumerate(table):
        r = [w[i] / m - p[i] for i in range(k)]
        g = sum(sg[i] * r[i] for i in range(k)) / k
        e = sum((r[i] - sg[i] * g) ** 2 for i in range(k))
        if e < be:
            best, be, bg = idx, e, g * m
    return best, be, bg
