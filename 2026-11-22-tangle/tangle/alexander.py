"""Alexander polynomial, knot determinant, Fox p-colorings.

All three come from the same Wirtinger-style relations on *arcs* (maximal
over-passes).  At a crossing with incoming-under arc x, outgoing-under arc y and
over arc z:   positive:  (1-t) z + t x - y = 0     negative:  (t-1) z + x - t y = 0.
"""
from fractions import Fraction
from . import poly as P


def arcs(link):
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b, c, d in link.crossings:
        for e in (a, b, c, d):
            find(e)
        parent[find(b)] = find(d)
    roots = sorted({find(e) for c in link.crossings for e in c})
    idx = {r: i for i, r in enumerate(roots)}
    rows = [(idx[find(a)], idx[find(c)], idx[find(b)]) for a, b, c, d in link.crossings]
    return len(roots), rows


def _det(m):
    n = len(m)
    m = [row[:] for row in m]
    det = Fraction(1)
    for i in range(n):
        piv = next((r for r in range(i, n) if m[r][i] != 0), None)
        if piv is None:
            return Fraction(0)
        if piv != i:
            m[i], m[piv] = m[piv], m[i]
            det = -det
        det *= m[i][i]
        for r in range(i + 1, n):
            f = m[r][i] / m[i][i]
            if f:
                for c in range(i, n):
                    m[r][c] -= f * m[i][c]
    return det


def alexander_matrix_at(link, t0):
    narcs, rows = arcs(link)
    n = link.n
    M = [[Fraction(0)] * narcs for _ in range(n)]
    for r, ((x, y, z), s) in enumerate(zip(rows, link.signs)):
        if s > 0:
            M[r][z] += 1 - t0
            M[r][x] += t0
            M[r][y] -= 1
        else:
            M[r][z] += t0 - 1
            M[r][x] += 1
            M[r][y] -= t0
    return M, narcs


def alexander_raw(link):
    """Alexander polynomial up to units: {exp>=0: int}, or {} if it vanishes."""
    n = link.n
    if n == 0:
        return {0: 1} if link.num_components == 1 else {}
    if link.free_loops:
        return {}
    narcs, _ = arcs(link)
    if narcs != n:
        return {}                                 # an over-only component: split link
    pts = [Fraction(i) for i in range(n + 1)]
    vals = []
    for t0 in pts:
        M, _ = alexander_matrix_at(link, t0)
        vals.append(_det([row[:-1] for row in M[:-1]]))
    co = P.interpolate(pts, vals)
    out = {}
    for e, c in enumerate(co):
        if c.denominator != 1:
            raise ArithmeticError("non-integral Alexander coefficient (bug)")
        if c:
            out[e] = int(c)
    return out


def alexander(link):
    """Normalised Alexander polynomial.

    Knots: symmetric Laurent form with Delta(1)=+1 (Conway normalisation).
    Links: lowest exponent 0, positive leading coefficient (defined up to +-t^k).
    Returns {} for the zero polynomial (split links)."""
    raw = alexander_raw(link)
    if not raw:
        return {}
    lo = min(raw)
    p = {e - lo: c for e, c in raw.items()}
    deg = max(p)
    if link.is_knot():
        if deg % 2:
            raise ArithmeticError("odd-degree knot Alexander polynomial (bug)")
        p = P.shift(p, -deg // 2)
        if sum(p.values()) < 0:
            p = P.scale(p, -1)
    elif p[max(p)] < 0:
        p = P.scale(p, -1)
    return p


def determinant(link):
    if link.n == 0:
        return 1 if link.num_components == 1 else 0
    raw = alexander_raw(link)
    return abs(sum(c * (-1) ** e for e, c in raw.items())) if raw else 0


def _rank_mod(M, p):
    M = [[x % p for x in row] for row in M]
    rank, rows, cols = 0, len(M), len(M[0]) if M else 0
    for c in range(cols):
        piv = next((r for r in range(rank, rows) if M[r][c]), None)
        if piv is None:
            continue
        M[rank], M[piv] = M[piv], M[rank]
        inv = pow(M[rank][c], -1, p)
        M[rank] = [x * inv % p for x in M[rank]]
        for r in range(rows):
            if r != rank and M[r][c]:
                f = M[r][c]
                M[r] = [(x - f * y) % p for x, y in zip(M[r], M[rank])]
        rank += 1
    return rank


def colorings(link, p):
    """Fox p-colorings (p an odd prime). Returns dict(total, nontrivial, colorable)."""
    if p < 3 or any(p % q == 0 for q in range(2, int(p ** 0.5) + 1)):
        raise ValueError("p must be an odd prime")
    narcs, rows = arcs(link)
    M = []
    for x, y, z in rows:
        r = [0] * narcs
        r[z] += 2
        r[x] -= 1
        r[y] -= 1
        M.append(r)
    rank = _rank_mod(M, p) if M else 0
    total = p ** (narcs - rank) * p ** link.free_loops
    trivial = p ** link.num_components if link.num_components else 1
    # trivial colourings = constant on each component
    return {"p": p, "total": total, "nontrivial": total - trivial, "colorable": total > trivial}
