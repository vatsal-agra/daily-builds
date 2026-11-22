"""Search small braid words for each prime knot <= 7 crossings.

Identification is independent of the library's own catalog: a candidate word is
accepted for a Rolfsen name only if (a) it closes to ONE component, (b) Jones span ==
word length (so the diagram is minimal & alternating), and (c) its symmetrised
Alexander polynomial equals the published table below (typed from the standard
knot tables, NOT computed by this code)."""
import itertools, json, sys
sys.path.insert(0, ".")
from tangle.link import Link
from tangle import jones, alexander

PUBLISHED = {   # Alexander polynomials, coefficient lists low->high (symmetric form)
    "3_1": [1, -1, 1], "4_1": [-1, 3, -1], "5_1": [1, -1, 1, -1, 1], "5_2": [2, -3, 2],
    "6_1": [2, -5, 2], "6_2": [-1, 3, -3, 3, -1], "6_3": [1, -3, 5, -3, 1],
    "7_1": [1, -1, 1, -1, 1, -1, 1], "7_2": [3, -5, 3], "7_3": [2, -3, 3, -3, 2],
    "7_4": [4, -7, 4], "7_5": [2, -4, 5, -4, 2], "7_6": [1, -5, 7, -5, 1], "7_7": [1, -5, 9, -5, 1],
}
CROSS = {k: int(k[0]) for k in PUBLISHED}


def norm(co):
    deg = len(co) - 1
    sg = 1 if sum(co) > 0 else -1          # Delta(1) = +1 normalisation
    return {i - deg // 2: c * sg for i, c in enumerate(co)}


def main():
    want = {k: norm(v) for k, v in PUBLISHED.items()}
    found = json.load(open('tools/discovered.json')) if len(sys.argv) > 1 else {}
    for strands in (2, 3, 4):
        letters = [g for i in range(1, strands) for g in (i, -i)]
        for length in range(3, 10 if strands < 4 else 9):
            todo = [k for k in want if CROSS[k] <= length and k not in found and not (strands == 2 and length > CROSS[k])]
            if length > 8 and strands == 4:
                continue
            if not todo:
                continue
            for first in range(1, strands):
                for rest in itertools.product(letters, repeat=length - 1):
                    w = (first,) + rest
                    if any(w[i] == -w[i + 1] for i in range(length - 1)):
                        continue
                    if {abs(g) for g in w} != set(range(1, strands)):
                        continue
                    L = Link.from_braid(list(w), strands)
                    if not L.is_knot():
                        continue
                    if length > 7 and strands == 4:
                        continue
                    A = alexander(L)
                    hit = [k for k in todo if A == want[k] and CROSS[k] <= length]
                    if not hit:
                        continue
                    J = jones(L)
                    span = (max(J) - min(J)) // 4
                    if span != CROSS[hit[0]]:
                        continue
                    found[hit[0]] = [strands, list(w)]
                    todo.remove(hit[0])
                    print(hit[0], strands, w, flush=True)
                    if not todo:
                        break
                if not todo:
                    break
    missing = sorted(set(want) - set(found))
    print("missing:", missing)
    json.dump(found, open("tools/discovered.json", "w"), indent=1)


main()
