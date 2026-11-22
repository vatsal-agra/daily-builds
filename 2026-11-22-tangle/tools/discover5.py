"""Exhaustive 4-strand search (lengths 7..8) for 6_1 and 7_6, same acceptance rule as discover4.py."""
import itertools, json, sys
from fractions import Fraction
sys.path.insert(0, ".")
from tangle.link import Link
from tangle import jones, alexander
from tangle.alexander import alexander_matrix_at, _det
PUB = {"6_1": [2, -5, 2], "7_6": [1, -5, 7, -5, 1]}
DET = {"6_1": 9, "7_6": 19}
CR = {"6_1": 6, "7_6": 7}
want = {k: {i - (len(v) - 1) // 2: c * (1 if sum(v) > 0 else -1) for i, c in enumerate(v)} for k, v in PUB.items()}  # Delta(1) = +1 normalisation
found = json.load(open("tools/discovered.json"))
need = [k for k in PUB if k not in found]
letters = [1, -1, 2, -2, 3, -3]
for length in (7, 8):
    for first in (1, 2, 3):
        for rest in itertools.product(letters, repeat=length - 1):
            w = (first,) + rest
            if any(w[i] == -w[i + 1] for i in range(length - 1)) or {abs(g) for g in w} != {1, 2, 3}:
                continue
            L = Link.from_braid(list(w), 4)
            if not L.is_knot():
                continue
            M, na = alexander_matrix_at(L, Fraction(-1))
            if na != L.n:
                continue
            d = abs(_det([r[:-1] for r in M[:-1]]))
            hit = [k for k in need if DET[k] == d]
            if not hit:
                continue
            if alexander(L) != want[hit[0]]:
                continue
            J = jones(L)
            if (max(J) - min(J)) // 4 != CR[hit[0]]:
                continue
            found[hit[0]] = [4, list(w)]
            need.remove(hit[0])
            print(hit[0], w, flush=True)
            json.dump(found, open("tools/discovered.json", "w"), indent=1)
            if not need:
                sys.exit(0)
print("missing", need)
