"""Identify a link diagram by invariants against the catalog."""
from . import catalog
from .link import Link
from .jones import jones, mirror_jones
from .alexander import alexander, determinant

_table = None


def invariants(link):
    return {"components": link.num_components, "jones": jones(link), "alexander": alexander(link),
            "determinant": determinant(link)}


def crossing_lower_bound(J):
    """Jones span is a lower bound for the crossing number (equality for alternating knots)."""
    return (max(J) - min(J)) // 4 if J else 0


def table():
    global _table
    if _table is None:
        _table = []
        for name in catalog.names():
            L = catalog.get(name)
            inv = invariants(L)
            _table.append((name, L.n, inv))
    return _table


def identify(link):
    """Returns dict(matches=[(name, relation)], invariants=..., verdict=str).

    relation: 'same' (same handedness as the catalog diagram), 'mirror', or 'both'
    (amphichiral, i.e. equal to its own mirror image as far as Jones can tell)."""
    inv = invariants(link)
    J, A = inv["jones"], inv["alexander"]
    mJ = mirror_jones(J)
    matches = []
    for name, n, ci in table():
        if ci["components"] != inv["components"] or ci["alexander"] != A:
            continue
        same, mir = ci["jones"] == J, ci["jones"] == mJ
        if same and mir:
            matches.append((name, "both"))
        elif same:
            matches.append((name, "same"))
        elif mir:
            matches.append((name, "mirror"))
    if not matches:
        # Alexander of a mirror image is equal up to units for knots; already handled.
        pass
    inv["chiral"] = J != mJ
    inv["crossing_lower_bound"] = crossing_lower_bound(J)
    if matches:
        names = ", ".join(f"{n}" + {"same": "", "mirror": " (mirror image)", "both": " (amphichiral)"}[r]
                          for n, r in matches)
        verdict = (f"matches catalog entry: {names}" if len(matches) == 1
                   else f"ambiguous: invariants cannot separate {names}")
    else:
        verdict = (f"not in catalog; crossing number >= {inv['crossing_lower_bound']} "
                   "(Jones span lower bound)")
    return {"matches": matches, "invariants": inv, "verdict": verdict}
