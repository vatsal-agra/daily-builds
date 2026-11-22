"""Named knots and links.

Every braid word of a prime knot below was FOUND BY SEARCH (tools/discover*.py) and
accepted only if its Alexander polynomial equals the published table and its Jones span
equals the crossing number; nothing here is copied from memory unchecked.  The catalog's
*handedness* is whatever the found word happens to be: names match up to mirror image
and identify() reports which.
"""
from .link import Link, LinkError, parse_braid
from .catalog_data import PRIME


def torus_braid(p, q):
    """T(p,q) as the closure of (s1...s_{p-1})^q on p strands (p >= 2; q may be negative)."""
    if p < 2:
        raise LinkError("torus knot T(p,q) needs p >= 2 strands")
    base = list(range(1, p))
    word = base * abs(q)
    if q < 0:
        word = [-g for g in word]
    return p, word


def connected_sum(b1, b2):
    """Braid whose closure is the connected sum of the closures of b1 and b2."""
    (n1, w1), (n2, w2) = b1, b2
    return n1 + n2 - 1, list(w1) + [g + (1 if g > 0 else -1) * (n1 - 1) for g in w2]


def mirror_braid(b):
    return b[0], [-g for g in b[1]]


def _simple():
    out = {"0_1": (1, [])}                      # the unknot: one strand, no crossings
    for k, (n, w) in PRIME.items():
        out[k] = (n, list(w))
    return out


def _build():
    cat = _simple()
    t31, f41 = cat["3_1"], cat["4_1"]
    cat["3_1#3_1"] = connected_sum(t31, t31)                       # granny
    cat["3_1#m3_1"] = connected_sum(t31, mirror_braid(t31))        # square
    cat["3_1#4_1"] = connected_sum(t31, f41)
    cat["4_1#4_1"] = connected_sum(f41, f41)
    cat["T(2,6) link"] = torus_braid(2, 6)
    cat["Hopf link"] = (2, [1, 1])
    cat["Solomon link"] = (2, [1, 1, 1, 1])
    cat["Borromean rings"] = (3, [1, -2, 1, -2, 1, -2])
    cat["2-component unlink"] = (2, [])
    cat["3-component unlink"] = (3, [])
    return cat


BRAIDS = _build()


def names():
    return list(BRAIDS)


def get(name):
    """Catalog name, 'T(p,q)', or case-insensitive alias -> Link."""
    import re
    m = re.fullmatch(r"\s*[Tt]\((-?\d+),\s*(-?\d+)\)\s*", name)
    if m:
        p, q = int(m.group(1)), int(m.group(2))
        n, w = torus_braid(p, q)
        return Link.from_braid(w, n, name=f"T({p},{q})")
    key = {k.lower(): k for k in BRAIDS}.get(name.strip().lower())
    if key is None:
        raise LinkError(f"unknown knot {name!r}; try one of: " + ", ".join(BRAIDS))
    n, w = BRAIDS[key]
    return Link.from_braid(w, n, name=key)
