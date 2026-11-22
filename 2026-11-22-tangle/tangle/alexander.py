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


_MERSENNE_BITS = (127, 521, 607, 1279, 2203, 2281, 3217, 4253, 4423, 9689, 9941, 11213, 19937)


def _det_mod(rows, size, p):
    """Determinant mod p of a sparse matrix given as a list of {col: val} dict rows."""
    rows = [dict(r) for r in rows]
    det = 1
    for col in range(size):
        best = None
        for i in range(col, size):
            if rows[i].get(col):
                if best is None or len(rows[i]) < len(rows[best]):
                    best = i
        if best is None:
            return 0
        if best != col:
            rows[col], rows[best] = rows[best], rows[col]
            det = -det
        piv = rows[col]
        pv = piv[col]
        det = det * pv % p
        inv = pow(pv, -1, p)
        for i in range(col + 1, size):
            r = rows[i]
            f = r.get(col)
            if f:
                f = f * inv % p
                for c, v in piv.items():
                    nv = (r.get(c, 0) - f * v) % p
                    if nv:
                        r[c] = nv
                    else:
                        r.pop(c, None)
    return det % p


def _interpolate_mod(xs, ys, p):
    """Lagrange interpolation mod p -> coefficient list (low -> high)."""
    n = len(xs)
    full = [1]
    for x in xs:                                   # prod (X - x)
        nxt = [0] * (len(full) + 1)
        for k, c in enumerate(full):
            nxt[k + 1] = (nxt[k + 1] + c) % p
            nxt[k] = (nxt[k] - c * x) % p
        full = nxt
    out = [0] * n
    for xi, yi in zip(xs, ys):
        q = [0] * n                                # full / (X - xi) by synthetic division
        carry = 0
        for k in range(n, 0, -1):
            carry = (full[k] + carry * xi) % p
            q[k - 1] = carry
        denom = 0
        for c in reversed(q):
            denom = (denom * xi + c) % p
        w = yi * pow(denom, -1, p) % p
        for k in range(n):
            out[k] = (out[k] + w * q[k]) % p
    return out


def alexander_raw(link):
    """Alexander polynomial up to units: {exp>=0: int}, or {} if it vanishes.

    Computed as an (n-1)-minor of the n x n Wirtinger/Fox matrix, evaluated at n integer
    points modulo a Mersenne prime and interpolated.  The prime is chosen above twice the
    proved coefficient bound 4^(n-1) (each row's coefficients have absolute sum <= 4), so the
    symmetric lift of the residues is the exact integer polynomial."""
    n = link.n
    if n == 0:
        return {0: 1} if link.num_components == 1 else {}
    if link.free_loops:
        return {}
    narcs, arc_rows = arcs(link)
    if narcs != n:
        return {}                                 # an over-only component: split link
    bits = next(b for b in _MERSENNE_BITS if b > 2 * n + 4)
    p = (1 << bits) - 1
    xs = list(range(n))
    ys = []
    last = n - 1
    for t0 in xs:
        rows = []
        for (x, y, z), sg in list(zip(arc_rows, link.signs))[:-1]:
            r = {}

            def put(c, v):
                if c != last:
                    r[c] = (r.get(c, 0) + v) % p
            if sg > 0:
                put(z, 1 - t0); put(x, t0); put(y, -1)
            else:
                put(z, t0 - 1); put(x, 1); put(y, -t0)
            rows.append({c: v for c, v in r.items() if v})
        ys.append(_det_mod(rows, n - 1, p))
    co = _interpolate_mod(xs, ys, p)
    out = {}
    for e, c in enumerate(co):
        c = c - p if c > p // 2 else c
        if c:
            out[e] = c
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
    trivial = p                                   # monochromatic colourings
    return {"p": p, "total": total, "nontrivial": total - trivial, "colorable": total > trivial}
