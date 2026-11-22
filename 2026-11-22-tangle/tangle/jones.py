"""Kauffman bracket and Jones polynomial.

<K> is computed by a frontier dynamic programme (a transfer-matrix over crossings):
instead of enumerating all 2^n smoothing states we sweep the crossings in a
frontier-minimising order and keep, for every distinct *connectivity pattern of the
open edges*, the running polynomial in A.  For braid closures the number of
patterns stays small, so 30+ crossing diagrams are routine.
"""
from collections import defaultdict
from . import poly as P

D = {2: -1, -2: -1}          # d = -A^2 - A^-2
_dpow = [{0: 1}]


def d_power(k):
    while len(_dpow) <= k:
        _dpow.append(P.mul(_dpow[-1], D))
    return _dpow[k]


def crossing_order(link):
    """Greedy sweep order keeping the frontier of half-open edges small."""
    xs = link.crossings
    if link.braid:
        return list(range(len(xs)))
    left, order, open_edges = set(range(len(xs))), [], set()
    while left:
        best = max(sorted(left), key=lambda k: (sum(1 for e in set(xs[k]) if e in open_edges), -k))
        left.discard(best)
        order.append(best)
        for e in set(xs[best]):
            if xs[best].count(e) == 1:
                open_edges.symmetric_difference_update({e})
    return order


def _connect(ends, x, y):
    """Add an arc x--y to the path-end table `ends` (mutated). Returns loops closed (0/1)."""
    if x == y:
        return 1                                 # an edge that closes on itself
    px, py = ends.get(x), ends.get(y)
    if px is None and py is None:
        ends[x], ends[y] = y, x
        return 0
    if px is None:                               # x fresh, y an end
        del ends[y]
        ends[x], ends[py] = py, x
        return 0
    if py is None:
        del ends[x]
        ends[y], ends[px] = px, y
        return 0
    if px == y:                                  # x and y are the two ends of one path
        del ends[x], ends[y]
        return 1
    del ends[x], ends[y]
    ends[px], ends[py] = py, px
    return 0


def kauffman_bracket(link, max_states=2_000_000):
    """Normalised bracket (<unknot> = 1) as {A-exponent: coeff}."""
    xs = link.crossings
    states = {(): {0: 1}}
    for k in crossing_order(link):
        a, b, c, d = xs[k]
        options = ((1, ((a, b), (c, d))),        # A-smoothing
                   (-1, ((a, d), (b, c))))       # A^-1 smoothing
        nxt = {}
        for key, pol in states.items():
            base = {}
            for u, v in key:
                base[u], base[v] = v, u
            for ex, arcs in options:
                ends = dict(base)
                loops = 0
                for x, y in arcs:
                    loops += _connect(ends, x, y)
                nk = tuple(sorted((u, v) for u, v in ends.items() if u < v))
                term = P.shift(pol, ex)
                if loops:
                    term = P.mul(term, d_power(loops))
                cur = nxt.get(nk)
                nxt[nk] = term if cur is None else P.add(cur, term)
        states = nxt
        if len(states) > max_states:
            raise MemoryError("diagram too wide for the frontier DP")
    total = states.get((), {})
    total = P.mul(total, d_power(link.free_loops))
    # unknot-normalise: divide by d = -A^-2 (A^4 + 1)
    return P.divide_exact(total, D)


def jones(link):
    """Jones polynomial as {q: coeff} meaning t^(q/4) (integers q; knots have 4|q)."""
    br = kauffman_bracket(link)
    w = link.writhe
    f = P.shift(br, -3 * w)
    if w % 2:
        f = P.scale(f, -1)
    return {-e: c for e, c in f.items()}


def mirror_jones(j):
    return {-q: c for q, c in j.items()}


def fmt_jones(j):
    return P.fmt(j, "t", unit=4)
