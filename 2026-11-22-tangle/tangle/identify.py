"""Identify a link diagram by invariants against the catalog.

Knots are matched on (Jones, Alexander) up to mirror image.  Links are matched up to the
orientation of their components: Jones is evaluated for every relative orientation (one
bracket, 2^(c-1) writhes) and the single-variable Alexander polynomial, which is orientation
dependent, is not used; components and determinant (orientation independent) are."""
from . import catalog
from .jones import jones, jones_orientations, mirror_jones
from .alexander import alexander, determinant

_table = None


def _key(j):
    return tuple(sorted(j.items()))


def invariants(link):
    return {"components": link.num_components, "jones": jones(link), "alexander": alexander(link),
            "determinant": determinant(link)}


def crossing_lower_bound(J):
    """Jones span is a lower bound for the crossing number (equality for alternating knots)."""
    return (max(J) - min(J)) // 4 if J else 0


def _variants(link):
    """Set of Jones keys over all component orientations (a singleton for knots)."""
    if link.num_components == 1 or not link._comps:
        return {_key(jones(link))}
    return {_key(j) for _, j in jones_orientations(link)}


def table():
    global _table
    if _table is None:
        _table = []
        for name in catalog.names():
            L = catalog.get(name)
            inv = invariants(L)
            inv["variants"] = _variants(L)
            _table.append((name, L.n, inv))
    return _table


def identify(link):
    """Returns dict(matches=[(name, relation)], invariants=..., verdict=str).

    relation: 'same' (same handedness as the catalog diagram), 'mirror', or 'both'
    (amphichiral as far as Jones can tell)."""
    inv = invariants(link)
    J, A = inv["jones"], inv["alexander"]
    knot = inv["components"] == 1
    qv = _variants(link)
    qv_mirror = {_key(mirror_jones(dict(k))) for k in qv}
    matches = []
    for name, n, ci in table():
        if ci["components"] != inv["components"] or ci["determinant"] != inv["determinant"]:
            continue
        if knot and ci["alexander"] != A:
            continue
        same, mir = bool(qv & ci["variants"]), bool(qv_mirror & ci["variants"])
        if same and mir:
            matches.append((name, "both"))
        elif same:
            matches.append((name, "same"))
        elif mir:
            matches.append((name, "mirror"))
    inv["chiral"] = _key(J) not in {_key(mirror_jones(J))} if knot else not bool(qv & qv_mirror)
    inv["crossing_lower_bound"] = crossing_lower_bound(J)
    if matches:
        names = ", ".join(f"{n}" + {"same": "", "mirror": " (mirror image)", "both": " (amphichiral)"}[r]
                          for n, r in matches)
        verdict = (f"matches catalog entry: {names}" if len(matches) == 1
                   else f"ambiguous: invariants cannot separate {names}")
        if not knot:
            verdict += "  [up to orientation of components]"
    else:
        verdict = (f"not in catalog (prime knots <= 7 crossings, a few composites and links); "
                   f"crossing number >= {inv['crossing_lower_bound']} "
                   "(Jones span: a lower bound, tight for alternating diagrams)")
    return {"matches": matches, "invariants": inv, "verdict": verdict}
