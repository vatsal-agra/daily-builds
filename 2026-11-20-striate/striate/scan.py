"""Raster barcode scanner: scanline sampling -> adaptive edge detection -> run-lengths ->
per-symbology decoders (both directions) -> checksum validation -> multi-scanline voting."""
import math
from dataclasses import dataclass, field

from .symbologies import code128, code39, ean, itf
from .symbologies.common import match_char, fit_gain

INF = float("inf")
MAXERR_128 = 2.2      # squared-module error allowed when matching one Code128 symbol (5 pair-sums)
MAXERR_EAN = 1.4      # 3 pair-sums


@dataclass
class Candidate:
    symbology: str
    text: str
    start: int            # element index range [start, end] inclusive (in the list that was decoded)
    end: int
    module: float         # estimated module width in px
    error: float          # mean matching error (lower = cleaner)


@dataclass
class Detection:
    symbology: str
    text: str
    votes: int                         # number of scanlines that independently decoded this symbol
    angle: float                       # scan angle (degrees) at which it was found
    bbox: tuple                        # (x0, y0, x1, y1) in image pixels
    module_px: float
    quality: float                     # mean matching error (0 = perfect)
    gs1: bool = False                  # Code 128 starting with FNC1
    extra: dict = field(default_factory=dict)

    def as_dict(self):
        return {"symbology": self.symbology, "text": self.text.replace("\xf1", "<FNC1>"), "votes": self.votes,
                "angle": self.angle, "bbox": list(self.bbox), "module_px": round(self.module_px, 2),
                "quality": round(self.quality, 3), "gs1": self.gs1, **self.extra}


# ------------------------------------------------------------------ line -> runs
def edges_from_samples(samples, min_grad=10.0):
    """Sub-pixel edge positions from gradient extrema. Returns list of (pos, to_dark).

    A threshold/binarization approach fails on blurred narrow spaces (their peak never reaches the
    mid-level), whereas the *steepest point* of each transition is amplitude independent. Samples are
    lightly smoothed, central differences taken, and local extrema of the gradient that are strong
    relative to the neighbourhood are kept; consecutive same-sign extrema collapse to the stronger.
    """
    n = len(samples)
    if n < 8:
        return []
    s = [samples[0]] + [(samples[i - 1] + 2 * samples[i] + samples[i + 1]) / 4.0 for i in range(1, n - 1)] + [samples[-1]]
    d = [0.0] * n
    for i in range(1, n - 1):
        d[i] = (s[i + 1] - s[i - 1]) / 2.0
    # local gradient scale (max |d| over a wide neighbourhood, block based)
    B = 16
    nb = (n + B - 1) // B
    bm = [max(abs(v) for v in d[b * B:(b + 1) * B]) for b in range(nb)]
    R = max(2, n // (B * 6))
    edges = []   # [pos, to_dark, strength]
    for i in range(1, n - 1):
        v = d[i]
        a = abs(v)
        if a < min_grad:
            continue
        if a < abs(d[i - 1]) or a < abs(d[i + 1]):
            continue
        if a == abs(d[i + 1]) and d[i + 1] * v > 0:
            continue                           # plateau: take its last point
        b = i // B
        local = max(bm[max(0, b - R):b + R + 1])
        if a < 0.3 * local:
            continue
        sign = v > 0
        w0 = max(0.0, d[i - 1] * (1 if sign else -1))
        w1 = a
        w2 = max(0.0, d[i + 1] * (1 if sign else -1))
        tot = w0 + w1 + w2
        pos = (i - 1) * w0 / tot + i * w1 / tot + (i + 1) * w2 / tot
        item = [pos, not sign, a]
        if edges and edges[-1][1] == item[1]:
            if item[2] > edges[-1][2]:
                edges[-1] = item
        else:
            edges.append(item)
    return [(p, dk) for p, dk, _ in edges]


def runs_from_edges(edges):
    """-> (boundaries, widths): element j spans boundaries[j]..boundaries[j+1]; element 0 is a bar."""
    e = list(edges)
    while e and not e[0][1]:
        e.pop(0)                       # line began inside a dark region: width unknown
    while e and e[-1][1]:
        e.pop()                        # unterminated bar
    # collapse consecutive same-direction edges (shouldn't happen with hysteresis, but be safe)
    clean = []
    for pos, d in e:
        if clean and clean[-1][1] == d:
            continue
        clean.append((pos, d))
    b = [p for p, _ in clean]
    w = [b[i + 1] - b[i] for i in range(len(b) - 1)]
    return b, w


# ------------------------------------------------------------------ helpers
def _quiet_ok(w, i, module, mult):
    return i == 0 or w[i - 1] >= mult * module


def _quiet_after(w, j, module, mult):
    return j + 1 >= len(w) or w[j + 1] >= mult * module


def _runs_of(mods):
    out, prev, n = [], mods[0], 0
    for ch in mods:
        if ch == prev:
            n += 1
        else:
            out.append(n); prev = ch; n = 1
    out.append(n)
    return tuple(out)


_EAN_LG = [_runs_of(m) for m in ean.L] + [_runs_of(m) for m in ean.G]   # index<10: L digit, else G digit
_EAN_R = [_runs_of(m) for m in ean.R]
assert all(len(p) == 4 for p in _EAN_LG + _EAN_R)


# ------------------------------------------------------------------ Code 128
_C128_CHARS = code128.TABLE[:106]
_C128_STARTS = {103: "A", 104: "B", 105: "C"}


def find_code128(w, par):
    out = []
    n = len(w)
    for i in range(par, n - 8, 2):
        idx, err, G = fit_gain(w[i:i + 6], _C128_CHARS[103:106], 11, 1)
        if idx < 0 or err > MAXERR_128:
            continue
        module = sum(w[i:i + 6]) / 11.0
        if abs(G) > 0.9 * module or not _quiet_ok(w, i, module, 4.5):
            continue
        vals, errs, j, done = [103 + idx], [err], i + 6, False
        while j + 6 <= n:
            cidx, cerr, _, resid = match_char(w[j:j + 6], _C128_CHARS, 11, G, 1)
            if j + 7 <= n:
                sidx, serr, _, _r = match_char(w[j:j + 7], [code128.TABLE[106]], 13, G, 1)
                if serr <= 1.6 and serr < cerr:
                    if len(vals) >= 3 and _quiet_after(w, j + 6, module, 4.0):
                        errs.append(serr); done = True
                    break
            if cidx < 0 or cerr > MAXERR_128:
                break
            G = 0.75 * G + 0.25 * (G + resid)
            vals.append(cidx); errs.append(cerr); j += 6
        if not done:
            continue
        if code128.checksum(vals[:-1]) != vals[-1]:
            continue
        try:
            text = code128.decode_values(vals[:-1])
        except ValueError:
            continue
        if not text:
            continue
        out.append(Candidate("Code 128", text, i, j + 6, module, sum(errs) / len(errs)))
    return out


# ------------------------------------------------------------------ EAN / UPC
def _ean_guards_ok(w, i, count, m):
    return all(0.35 * m <= x <= 2.4 * m for x in w[i:i + count])


def find_ean(w, par):
    out = []
    n = len(w)
    for i in range(par, n - 42, 2):
        for kind in (13, 8):
            half = 6 if kind == 13 else 4
            total = 3 + 4 * half + 5 + 4 * half + 3
            if i + total > n:
                continue
            digits, types, errs, scales, ok = [], [], [], [], True
            p = i + 3
            G = ((w[i] + w[i + 2]) / 2.0 - w[i + 1]) / 2.0      # ink gain from the start guard (1,1,1)
            for _ in range(half):
                idx, err, _s, resid = match_char(w[p:p + 4], _EAN_LG if kind == 13 else _EAN_LG[:10], 7, G, -1)
                if idx < 0 or err > MAXERR_EAN:
                    ok = False; break
                G = 0.7 * G + 0.3 * (G + resid)
                digits.append(idx % 10); types.append("L" if idx < 10 else "G")
                errs.append(err); scales.append(sum(w[p:p + 4]) / 7.0); p += 4
            if not ok:
                continue
            if kind == 8 and "G" in types:
                continue
            m = sum(scales) / len(scales)
            if not _ean_guards_ok(w, i, 3, m) or not _ean_guards_ok(w, p, 5, m):
                continue
            p += 5
            rd = []
            for _ in range(half):
                idx, err, _s, resid = match_char(w[p:p + 4], _EAN_R, 7, G, 1)
                if idx < 0 or err > MAXERR_EAN:
                    ok = False; break
                G = 0.7 * G + 0.3 * (G + resid)
                rd.append(idx); errs.append(err); scales.append(sum(w[p:p + 4]) / 7.0); p += 4
            if not ok:
                continue
            if not _ean_guards_ok(w, p, 3, m):
                continue
            m = sum(scales) / len(scales)
            if not _quiet_ok(w, i, m, 4.0) or not _quiet_after(w, p + 2, m, 4.0):
                continue
            if kind == 13:
                par_s = "".join(types)
                if par_s not in ean.PARITY:
                    continue
                text = str(ean.PARITY.index(par_s)) + "".join(map(str, digits)) + "".join(map(str, rd))
                sym = "EAN-13"
                if text[0] == "0":
                    text, sym = text[1:], "UPC-A"
                    if not ean.verify(text):
                        continue
                elif not ean.verify(text):
                    continue
            else:
                text = "".join(map(str, digits + rd)); sym = "EAN-8"
                if not ean.verify(text):
                    continue
            out.append(Candidate(sym, text, i, p + 2, m, sum(errs) / len(errs)))
    return out


# ------------------------------------------------------------------ narrow/wide helpers
def _two_means(vals):
    lo, hi = min(vals), max(vals)
    if hi <= 0:
        return 0, 0
    for _ in range(12):
        a = [v for v in vals if abs(v - lo) <= abs(v - hi)]
        b = [v for v in vals if abs(v - lo) > abs(v - hi)]
        if not a or not b:
            break
        nlo, nhi = sum(a) / len(a), sum(b) / len(b)
        if abs(nlo - lo) < 1e-6 and abs(nhi - hi) < 1e-6:
            break
        lo, hi = nlo, nhi
    return lo, hi


def _median(v):
    s = sorted(v)
    return s[len(s) // 2]


# ------------------------------------------------------------------ Code 39
def find_code39(w, par):
    out = []
    n = len(w)
    for i in range(par, n - 28, 2):
        nar = _median(w[i:i + 9])
        if nar <= 0 or not _quiet_ok(w, i, nar, 5.0):
            continue
        j = i
        while j < n and not (j > i and (j - i) % 2 == 1 and w[j] > 4.6 * nar):
            j += 1
        m = j - i                      # elements i..j-1 ; must end on a bar
        if m % 2 == 0 or (m + 1) % 10 != 0 or m < 29:
            continue
        el = w[i:j]
        bars, spaces = el[0::2], el[1::2]
        blo, bhi = _two_means(bars)
        slo, shi = _two_means(spaces)
        if blo <= 0 or slo <= 0 or bhi / blo < 1.5 or shi / slo < 1.5 or bhi / blo > 5 or shi / slo > 5:
            continue
        bt, st = (blo + bhi) / 2, (slo + shi) / 2
        chars, bad = [], False
        for c in range((m + 1) // 10):
            base = c * 10
            s = ""
            for k in range(9):
                x = el[base + k]
                s += "W" if (x > bt if k % 2 == 0 else x > st) else "N"
            ch = code39.BY_PATTERN.get(s)
            if ch is None:
                bad = True; break
            chars.append(ch)
            if c < (m + 1) // 10 - 1 and el[base + 9] > st:   # inter-char gap must be narrow
                bad = True; break
        if bad or chars[0] != "*" or chars[-1] != "*" or "*" in chars[1:-1]:
            continue
        mod = (blo + slo) / 2 if abs(blo - slo) < 0.5 * blo else min(blo, slo)
        if not _quiet_after(w, j - 1, mod, 5.0):
            continue
        # cluster tightness as error proxy
        spread = sum(abs(x - (blo if x <= bt else bhi)) for x in bars) / (len(bars) * blo)
        out.append(Candidate("Code 39", "".join(chars[1:-1]), i, j - 1, mod, spread))
    return out


# ------------------------------------------------------------------ ITF
def _top2_wide(five):
    order = sorted(range(5), key=lambda k: -five[k])
    if five[order[1]] < 1.25 * five[order[2]]:
        return None
    key = "".join("W" if k in order[:2] else "N" for k in range(5))
    return itf.BY_PATTERN.get(key)


def find_itf(w, par):
    out = []
    n = len(w)
    for i in range(par, n - 16, 2):
        a, b, c, d = w[i:i + 4]
        nar = (a + b + c + d) / 4
        if nar <= 0 or not _quiet_ok(w, i, nar, 5.0):
            continue
        if abs((a + b) - (c + d)) > 0.35 * (a + b + c + d) / 2 or max(a, b, c, d) > 2.4 * min(a, b, c, d) + 1e-9:
            continue
        j = i + 4
        while j < n and not ((j - i) % 2 == 1 and w[j] > 4.6 * nar):
            j += 1
        m = j - (i + 4)               # data+stop elements
        if m < 13 or (m - 3) % 10 != 0:
            continue
        data = w[i + 4:j - 3]
        stop = w[j - 3:j]
        if not (stop[0] > 1.5 * max(stop[1], stop[2]) and 0.4 * nar < stop[1] < 1.8 * nar * 1.4 and 0.4 * nar < stop[2] < 1.8 * nar * 1.4):
            continue
        digits, bad = [], False
        for g in range(0, len(data), 10):
            blk = data[g:g + 10]
            d1, d2 = _top2_wide(blk[0::2]), _top2_wide(blk[1::2])
            if d1 is None or d2 is None:
                bad = True; break
            digits.extend([d1, d2])
        if bad:
            continue
        if not _quiet_after(w, j - 1, nar, 5.0):
            continue
        out.append(Candidate("ITF", "".join(map(str, digits)), i, j - 1, nar, 0.0))
    return out


FINDERS = [find_code128, find_ean, find_code39, find_itf]
CHECKED = {"Code 128", "EAN-13", "UPC-A", "EAN-8"}


def decode_line(boundaries, widths):
    """Run every decoder, forward and reversed. Returns list of (Candidate, t_start, t_end, reversed)."""
    n = len(widths)
    res = []
    if n < 10:
        return res
    rev = widths[::-1]
    for finder in FINDERS:
        for c in finder(widths, 0):
            res.append((c, boundaries[c.start], boundaries[c.end + 1], False))
        par_rev = (n - 1) % 2           # bars sit at reversed indices with this parity
        for c in finder(rev, par_rev):
            res.append((c, boundaries[n - c.end - 1], boundaries[n - c.start], True))
    return res


# ------------------------------------------------------------------ image level
def _line_samples(img, p0, p1):
    (x0, y0), (x1, y1) = p0, p1
    length = math.hypot(x1 - x0, y1 - y0)
    n = int(length) + 1
    if n < 16:
        return None
    dx, dy = (x1 - x0) / length, (y1 - y0) / length
    if dy == 0 and float(y0).is_integer():
        row = img.rows[int(y0)]
        xs = int(x0)
        return list(row[xs:xs + n]), (x0, y0, dx, dy)
    return [img.get(x0 + dx * t, y0 + dy * t) for t in range(n)], (x0, y0, dx, dy)


def _clip_line(img, cx, cy, dx, dy):
    """Intersect the infinite line through (cx,cy) with direction (dx,dy) with the image rectangle."""
    ts = []
    W, H = img.w - 1, img.h - 1
    for (lo, hi, c, d) in ((0, W, cx, dx), (0, H, cy, dy)):
        if abs(d) < 1e-12:
            if c < lo or c > hi:
                return None
            continue
        t1, t2 = (lo - c) / d, (hi - c) / d
        ts.append((min(t1, t2), max(t1, t2)))
    if not ts:
        return None
    t0 = max(a for a, _ in ts); t1 = min(b for _, b in ts)
    if t1 - t0 < 16:
        return None
    return (cx + dx * t0, cy + dy * t0), (cx + dx * t1, cy + dy * t1)


def scanlines(img, angle, max_lines=48):
    """Yield (p0, p1) scan segments at `angle` degrees, evenly spread over the image."""
    a = math.radians(angle)
    dx, dy = math.cos(a), math.sin(a)
    nx, ny = -dy, dx                     # normal
    cx, cy = (img.w - 1) / 2, (img.h - 1) / 2
    extent = abs(img.w * nx) + abs(img.h * ny)
    if angle % 180 == 0:
        ys = range(img.h) if img.h <= max_lines else [int(round(k * (img.h - 1) / (max_lines - 1))) for k in range(max_lines)]
        for y in ys:
            yield (0.0, float(y)), (float(img.w - 1), float(y))
        return
    steps = max_lines
    for k in range(steps):
        off = (k + 0.5) / steps * extent - extent / 2
        seg = _clip_line(img, cx + nx * off, cy + ny * off, dx, dy)
        if seg:
            yield seg


def _scan_angle(img, angle, max_lines):
    hits = {}
    nlines = 0
    for p0, p1 in scanlines(img, angle, max_lines):
        got = _line_samples(img, p0, p1)
        if got is None:
            continue
        samples, (ox, oy, dx, dy) = got
        nlines += 1
        edges = edges_from_samples(samples)
        if len(edges) < 12:
            continue
        b, w = runs_from_edges(edges)
        for cand, ts, te, _rev in decode_line(b, w):
            key = (cand.symbology, cand.text)
            h = hits.setdefault(key, {"votes": 0, "pts": [], "mod": [], "err": []})
            h["votes"] += 1
            h["pts"].append((ox + dx * ts, oy + dy * ts)); h["pts"].append((ox + dx * te, oy + dy * te))
            h["mod"].append(cand.module); h["err"].append(cand.error)
    return hits, nlines


def scan_image(img, max_lines=48, rotate=True, angles=None, min_votes=None):
    """Find and decode every 1D barcode in a grayscale Image. Returns list[Detection], best first.

    Tries horizontal scanlines first; if nothing is found and `rotate` is true, tries other
    angles (including vertical) until some angle yields a decode.
    """
    if angles is None:
        angles = [0.0]
        if rotate:
            for a in range(5, 91, 5):
                angles.extend([float(a), float(-a)] if a != 90 else [90.0])
    found = []
    for angle in angles:
        hits, nlines = _scan_angle(img, angle, max_lines)
        need_unchecked = 2 if nlines >= 4 else 1
        for (sym, text), h in hits.items():
            need = min_votes if min_votes is not None else (1 if sym in CHECKED else need_unchecked)
            if angle % 180 != 0 and min_votes is None:
                need = max(need, 2)
            if h["votes"] < need:
                continue
            xs = [p[0] for p in h["pts"]]; ys = [p[1] for p in h["pts"]]
            found.append(Detection(sym, text, h["votes"], angle,
                                   (round(min(xs), 1), round(min(ys), 1), round(max(xs), 1), round(max(ys), 1)),
                                   _median(h["mod"]), sum(h["err"]) / len(h["err"]),
                                   gs1=(sym == "Code 128" and text.startswith(code128.FNC1)),
                                   extra=_extra(sym, text)))
        if found:
            break
    found.sort(key=lambda d: (-d.votes, d.quality))
    return _dedupe(found)


def _extra(sym, text):
    if sym == "Code 39":
        return {"mod43_valid": len(text) > 1 and code39.check_char(text[:-1]) == text[-1]}
    if sym == "ITF":
        return {"mod10_valid": len(text) > 1 and itf.mod10(text[:-1]) == text[-1]}
    return {}


def _dedupe(dets):
    """Drop weaker detections whose bbox overlaps a stronger one's (e.g. a mis-read of the same symbol)."""
    keep = []
    for d in dets:
        dup = False
        for k in keep:
            ox = min(d.bbox[2], k.bbox[2]) - max(d.bbox[0], k.bbox[0])
            oy = min(d.bbox[3], k.bbox[3]) - max(d.bbox[1], k.bbox[1])
            wd = max(1.0, d.bbox[2] - d.bbox[0]); wk = max(1.0, k.bbox[2] - k.bbox[0])
            if ox > 0.8 * min(wd, wk) and oy >= -1 and k.angle == d.angle and d.votes < k.votes:
                dup = True; break
        if not dup:
            keep.append(d)
    return keep
