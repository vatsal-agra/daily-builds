"""Braid-word simplifier: a best-first search over Markov-equivalent braid words.

Moves (all sound, i.e. they preserve the link type of the closure):
  free reduction      s_i s_i^-1 -> (empty)               (Reidemeister II)
  braid relation      s_i s_j s_i <-> s_j s_i s_j          (Reidemeister III, same signs, |i-j|=1)
  conjugation rel.    s_i s_j s_i^-1 <-> s_j^-1 s_i s_j  (a consequence of the braid relation)
  commutation         s_i s_j <-> s_j s_i,  |i-j| >= 2
  conjugation         cyclic rotation of the word
  destabilisation     w s_{n-1}^{+-1} (w in B_{n-1}) -> w   (Markov; Reidemeister I)
 expanding moves, used only when the search is stuck:
  insertion           w -> w s_i s_i^-1 (anywhere)
  stabilisation       w -> w s_n^{+-1} on n+1 strands
Finding the empty one-strand word *proves* the diagram is the unknot.  Failing to find
it proves nothing (the search is bounded), and the report says so.
"""
import heapq
from itertools import count


def canon(word):
    if not word:
        return ()
    w = tuple(word)
    return min(w[i:] + w[:i] for i in range(len(w)))


def _rotations(w):
    return [w[i:] + w[:i] for i in range(len(w))]


def neighbours(n, w, expand, extra_ok=True):
    """Yield (n2, word2, description)."""
    L = len(w)
    seen = set()
    for r in _rotations(w):
        # free reduction at the front
        if L >= 2 and r[0] == -r[1]:
            yield n, r[2:], f"cancel s{abs(r[0])} s{abs(r[0])}^-1"
        if L >= 3 and r[0] == r[2] and r[0] * r[1] > 0 and abs(abs(r[0]) - abs(r[1])) == 1:
            yield n, (r[1], r[0], r[1]) + r[3:], f"braid relation at s{abs(r[0])} s{abs(r[1])}"
        if L >= 3 and r[2] == -r[0] and r[0] * r[1] > 0 and abs(abs(r[0]) - abs(r[1])) == 1:
            yield n, (-r[1], r[0], r[1]) + r[3:], f"conjugation relation s{abs(r[0])}^{r[0]//abs(r[0]):+d} through s{abs(r[1])}"
        if L >= 2 and abs(abs(r[0]) - abs(r[1])) >= 2:
            yield n, (r[1], r[0]) + r[2:], f"commute s{abs(r[0])} s{abs(r[1])}"
        if n >= 2 and abs(r[-1]) == n - 1 and sum(1 for g in r if abs(g) == n - 1) == 1:
            key = r[:-1]
            if key not in seen:
                seen.add(key)
                yield n - 1, key, f"destabilise s{n-1}"
        if expand:
            for g in range(1, n):
                for s in (1, -1):
                    yield n, (s * g, -s * g) + r, f"insert s{g}^{s:+d} s{g}^{-s:+d}"
    if expand:
        for s in (1, -1):
            yield n + 1, tuple(w) + (s * n,), f"stabilise to {n+1} strands"


def simplify(n, word, node_budget=40000, max_growth=4):
    """Returns dict(strands, word, steps, proved_unknot, nodes, initial_len)."""
    start = (n, canon(word))
    tick = count()
    heap = [(len(start[1]), 0, next(tick), start)]
    parent = {start: (None, "start")}
    best = start
    nodes = 0
    limit = len(start[1]) + max_growth
    while heap and nodes < node_budget:
        ln, g, _, st = heapq.heappop(heap)
        nodes += 1
        if (len(st[1]), st[0]) < (len(best[1]), best[0]):
            best = st
        if st[1] == () and st[0] == 1:
            break
        stuck = ln >= len(best[1]) and g > 0 or False
        for n2, w2, why in neighbours(st[0], st[1], expand=False):
            key = (n2, canon(w2))
            if key not in parent:
                parent[key] = (st, why)
                heapq.heappush(heap, (len(key[1]), g, next(tick), key))
        # expanding moves are queued with a penalty so shorter states are explored first
        if len(st[1]) <= len(best[1]) + 2:
            for n2, w2, why in neighbours(st[0], st[1], expand=True):
                if len(w2) <= len(st[1]) or n2 > st[0]:
                    key = (n2, canon(w2))
                    if key not in parent and len(key[1]) <= limit and key[0] <= n + 2:
                        parent[key] = (st, why)
                        heapq.heappush(heap, (len(key[1]) + 3, g + 1, next(tick), key))
    steps, st = [], best
    while st is not None:
        prev, why = parent[st]
        if prev is not None:
            steps.append(f"{why}  ->  {fmt_word(st[1])} on {st[0]} strand(s)")
        st = prev
    steps.reverse()
    return {"strands": best[0], "word": list(best[1]), "steps": steps,
            "proved_unknot": best[1] == () and best[0] == 1, "nodes": nodes,
            "initial_len": len(word)}


def fmt_word(w):
    return " ".join(f"s{g}" if g > 0 else f"s{-g}^-1" for g in w) or "(empty)"


def scramble(n, word, steps=30, seed=0, max_len=40):
    """Apply `steps` random sound moves (including expanding ones) -> (n', word')."""
    import random
    rng = random.Random(seed)
    w = tuple(word)
    for _ in range(steps):
        opts = list(neighbours(n, w, expand=True))
        opts = [o for o in opts if len(o[1]) <= max_len and o[0] <= n + 1]
        if not opts:
            break
        n, w, _ = rng.choice(opts)
    return n, list(w)
