"""Image comparison helpers used by the tests and tools/compare.py."""
from .raster import read_png_rgb


def diff_stats(a, b, thresh=48):
    """a, b: (w, h, rows). Returns dict(mad, bad_frac, strict_bad_frac). 'bad' = a pixel that differs by
    more than `thresh` from the reference AND from every pixel in its 3x3 neighbourhood
    (forgives 1px anti-aliasing / hinting shifts)."""
    wa, ha, ra = a
    wb, hb, rb = b
    if (wa, ha) != (wb, hb):
        return {"size_mismatch": (wa, ha, wb, hb), "mad": 255.0, "bad_frac": 1.0, "strict_bad_frac": 1.0}
    total = 0
    bad = strict = 0
    for y in range(ha):
        A, B = ra[y], rb[y]
        if A == B:
            continue
        for x in range(wa):
            i = 3 * x
            d = max(abs(A[i] - B[i]), abs(A[i + 1] - B[i + 1]), abs(A[i + 2] - B[i + 2]))
            if d == 0:
                continue
            total += abs(A[i] - B[i]) + abs(A[i + 1] - B[i + 1]) + abs(A[i + 2] - B[i + 2])
            if d > thresh:
                strict += 1
                ok = False
                for yy in (y - 1, y, y + 1):
                    if not 0 <= yy < ha:
                        continue
                    for xx in (x - 1, x, x + 1):
                        if not 0 <= xx < wa:
                            continue
                        j = 3 * xx
                        R = rb[yy]
                        if max(abs(A[i] - R[j]), abs(A[i + 1] - R[j + 1]), abs(A[i + 2] - R[j + 2])) <= thresh:
                            ok = True
                            break
                    if ok:
                        break
                if not ok:
                    bad += 1
    n = wa * ha
    return {"mad": total / (3.0 * n), "bad_frac": bad / n, "strict_bad_frac": strict / n}


def load(path):
    with open(path, "rb") as f:
        return read_png_rgb(f.read())
