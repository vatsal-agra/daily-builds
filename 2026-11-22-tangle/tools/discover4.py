"""Second-pass search: 4-strand braids of length 8-9 for the knots 6_1, 7_2, 7_4, 7_6
(braid index 4, minimal braid diagrams are not alternating).  Same acceptance rule as
discover.py (published Alexander polynomial + Jones span), with a cheap determinant prefilter."""
import itertools, json, sys, random
from fractions import Fraction
sys.path.insert(0, ".")
sys.path.insert(0, "tools")
from tangle.link import Link
from tangle import jones, alexander
from tangle.alexander import alexander_matrix_at, _det
PUB = {"6_1": [2, -5, 2], "7_2": [3, -5, 3], "7_4": [4, -7, 4], "7_6": [1, -5, 7, -5, 1]}
DET = {"6_1": 9, "7_2": 11, "7_4": 15, "7_6": 19}
CR = {k: int(k[0]) for k in PUB}
want = {k: {i - (len(v) - 1) // 2: c * (1 if sum(v) > 0 else -1) for i, c in enumerate(v)} for k, v in PUB.items()}  # Delta(1) = +1 normalisation
found = json.load(open("tools/discovered.json"))
need = [k for k in PUB if k not in found]
letters = [1, -1, 2, -2, 3, -3]
random.seed(7)
tried = 0
while need and tried < 3_000_000:
    length = random.choice([8, 9, 9, 10])
    w = [random.choice(letters) for _ in range(length)]
    if any(w[i] == -w[i + 1] for i in range(length - 1)) or {abs(g) for g in w} != {1, 2, 3}:
        continue
    tried += 1
    L = Link.from_braid(w, 4)
    if not L.is_knot():
        continue
    M, na = alexander_matrix_at(L, Fraction(-1))
    if na != L.n:
        continue
    d = abs(_det([r[:-1] for r in M[:-1]]))
    hit = [k for k in need if DET[k] == d]
    if not hit:
        continue
    A = alexander(L)
    hit = [k for k in hit if A == want[k]]
    if not hit:
        continue
    J = jones(L)
    if (max(J) - min(J)) // 4 != CR[hit[0]]:
        continue
    found[hit[0]] = [4, w]
    need.remove(hit[0])
    print(hit[0], w, "tried", tried, flush=True)
    json.dump(found, open("tools/discovered.json", "w"), indent=1)
print("still missing:", need, "tried", tried)
