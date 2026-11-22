"""Oriented link diagrams: planar-diagram (PD) codes, braid closures, orientation tracing.

PD convention (KnotTheory / Bar-Natan): X[a,b,c,d] lists the four edge labels around a
crossing counter-clockwise, starting from the *incoming under* strand.  So the under
strand runs a -> c and the over strand runs b <-> d.  Crossing sign is derived from the
orientation of the components, never trusted from the caller.
"""
import re
from collections import defaultdict


class LinkError(ValueError):
    pass


# ----------------------------------------------------------------- braid parsing
def parse_braid(text, strands=None):
    """'1 -2 1 -2', 's1 s2^-1 s1', '1,1,1' or 's1^3' -> (strands, [letters])."""
    word = []
    for tok in re.split(r"[\s,;]+", text.strip().replace("σ", "s")):
        if not tok:
            continue
        m = re.fullmatch(r"[sS]?(-?\d+)(?:\^(-?\d+))?", tok)
        if not m:
            raise LinkError(f"cannot parse braid token {tok!r}")
        g, pw = int(m.group(1)), m.group(2)
        if g == 0:
            raise LinkError("generator index 0 is invalid (generators are 1-based)")
        if pw is None:
            word.append(g)
        else:
            pw = int(pw)
            if m.group(1).startswith("-"):
                raise LinkError(f"ambiguous token {tok!r}: write s{abs(g)}^{-pw}")
            word.extend([g if pw >= 0 else -g] * abs(pw))
    need = max((abs(g) for g in word), default=0) + 1
    if strands is None:
        strands = max(need, 1)
    if strands < need:
        raise LinkError(f"braid uses generator s{need-1}, needs at least {need} strands, got {strands}")
    if strands < 1:
        raise LinkError("a braid needs at least 1 strand")
    return strands, word


def parse_pd(text):
    """'X[1,4,2,5] X[3,6,4,1]' or '[[1,4,2,5],[3,6,4,1]]' -> list of 4-tuples."""
    bad = re.sub(r"[Xx\[\](),;\s]|-?\d+", "", text)
    if bad:
        raise LinkError(f"unexpected text {bad[:12]!r} in PD code (expected e.g. X[1,4,2,5] X[3,6,4,1] ...)")
    if re.search(r"\d-", text):
        raise LinkError("labels must be separated by commas or spaces (found 'digit-')")
    nums = [int(x) for x in re.findall(r"-?\d+", text)]
    if not nums:
        raise LinkError("empty PD code")
    if len(nums) % 4:
        raise LinkError(f"PD code needs groups of 4 labels, got {len(nums)} numbers")
    return [tuple(nums[i:i + 4]) for i in range(0, len(nums), 4)]


def _walk(xs):
    """Straight-ahead walk of a 4-valent diagram -> list of components, each a list of
    passes (crossing, entry_slot, exit_slot).  Every crossing strand is walked once."""
    occ = defaultdict(list)
    for k, c in enumerate(xs):
        for s, e in enumerate(c):
            occ[e].append((k, s))
    seen = set()
    comps = []
    for k0 in range(len(xs)):
        for r0 in (0, 1):
            if (k0, r0) in seen:
                continue
            path = []
            k, s = k0, r0
            while (k, s % 2) not in seen:
                seen.add((k, s % 2))
                ex = (s + 2) % 4
                path.append((k, s, ex))
                lab = xs[k][ex]
                a, b = occ[lab]
                k, s = b if a == (k, ex) else a
            if (k, s) != (k0, r0):
                raise LinkError("diagram is not a consistent straight-ahead link (bad PD code)")
            comps.append(path)
    return comps


def _braid_crossings(word, strands):
    cur = list(range(1, strands + 1))
    nxt = strands + 1
    xs = []
    for g in word:
        i = abs(g) - 1
        eL, eR = cur[i], cur[i + 1]
        nL, nR = nxt, nxt + 1
        nxt += 2
        xs.append((eL, nL, nR, eR) if g > 0 else (eR, eL, nL, nR))
        cur[i], cur[i + 1] = nL, nR
    return xs, cur


# ----------------------------------------------------------------- the Link class
class Link:
    """An oriented link diagram.

    Orientation is encoded by the PD code (the under strand runs a -> c).  A component that is
    over at every one of its crossings carries no orientation information in a *PD*; it is
    then oriented arbitrarily (braid-built links always orient strands downward)."""

    def __init__(self, crossings, free_loops=0, braid=None, name=None):
        self.crossings = [tuple(c) for c in crossings]
        self.free_loops = free_loops
        self.braid = braid          # (strands, word) when built from a braid
        self.name = name
        self._validate()
        self._trace()

    # ---- constructors
    @classmethod
    def from_braid(cls, word, strands=None, name=None):
        if isinstance(word, str):
            strands, word = parse_braid(word, strands)
        else:
            word = list(word)
            need = max((abs(g) for g in word), default=0) + 1
            strands = max(strands or 1, need)
            if any(g == 0 for g in word):
                raise LinkError("generator index 0 is invalid")
        xs, cur = _braid_crossings(word, strands)
        ren, loops = {}, 0
        for p in range(strands):
            if cur[p] == p + 1:
                loops += 1          # strand never touched: a free circle
            else:
                ren[cur[p]] = p + 1
        xs = [tuple(ren.get(e, e) for e in c) for c in xs]
        return cls(xs, loops, braid=(strands, word), name=name)


    @classmethod
    def from_plat(cls, word, strands=4, name=None, nested_caps=False):
        """Plat closure: strands (1,2),(3,4).. are joined by cups on top; the bottom caps
        join the same pairs, or (1,4),(2,3) when nested_caps (4 strands only)."""
        if strands % 2 or strands < 2:
            raise LinkError("plat closure needs an even number of strands")
        word = list(word)
        if any(g == 0 or abs(g) >= strands for g in word):
            raise LinkError("generator index out of range for this plat")
        xs, cur = _braid_crossings(word, strands)
        parent = {}

        def find(x):
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x, y):
            parent[find(x)] = find(y)
        if nested_caps and strands != 4:
            raise LinkError("nested caps are only defined for 4-strand plats")
        for j in range(0, strands, 2):
            union(j + 1, j + 2)
        for p, q in ([(0, 3), (1, 2)] if nested_caps else [(j, j + 1) for j in range(0, strands, 2)]):
            union(cur[p], cur[q])
        xs = [tuple(find(e) for e in c) for c in xs]
        used = {e for c in xs for e in c}
        labels = set(range(1, strands + 1)) | {e for c in _braid_crossings(word, strands)[0] for e in c}
        loops = len({find(e) for e in labels} - used)
        # orient: rotate each crossing so its under strand runs a -> c along a chosen walk
        xs = [tuple(c) for c in xs]
        for path in _walk(xs):
            for k, s, ex in path:
                if s == 2:
                    xs[k] = xs[k][2:] + xs[k][:2]
        return cls(xs, loops, name=name)

    @classmethod
    def from_conway(cls, coeffs, name=None):
        """2-bridge (rational) knot/link C(a1,...,ak) as a 4-plat s2^a1 s1^-a2 s2^a3 ..."""
        if not coeffs or any(not isinstance(a, int) or a == 0 for a in coeffs):
            raise LinkError("Conway notation needs a non-empty list of non-zero integers")
        word = []
        for i, a in enumerate(coeffs):
            g, sg = (2, 1) if i % 2 == 0 else (1, -1)
            word += [sg * g * (1 if a > 0 else -1)] * abs(a)
        return cls.from_plat(word, 4, name=name, nested_caps=len(coeffs) % 2 == 0)

    @classmethod
    def from_pd(cls, crossings, free_loops=0, name=None):
        return cls(crossings, free_loops, name=name)

    # ---- validation
    def _validate(self):
        count = defaultdict(int)
        for c in self.crossings:
            if len(c) != 4:
                raise LinkError(f"crossing {c} does not have 4 edges")
            for e in c:
                count[e] += 1
        bad = {e: k for e, k in count.items() if k != 2}
        if bad:
            e, k = sorted(bad.items())[0]
            raise LinkError(f"edge {e} appears {k} time(s); in a valid PD code every edge appears exactly twice")
        if self.free_loops < 0:
            raise LinkError("free_loops must be >= 0")
        self._check_planar()

    def _check_planar(self):
        """Euler characteristic of the surface the diagram lives on must be that of the sphere:
        V - E + F = 2 per connected piece, with faces traced from the ccw rotation system."""
        xs = self.crossings
        if not xs:
            return
        occ = defaultdict(list)
        for k, c in enumerate(xs):
            for s_, e in enumerate(c):
                occ[e].append((k, s_))
        other = {}
        for e, (d1, d2) in occ.items():
            other[d1], other[d2] = d2, d1
        seen, faces = set(), 0
        for d in other:
            if d in seen:
                continue
            faces += 1
            while d not in seen:
                seen.add(d)
                k, s_ = other[d]
                d = (k, (s_ + 1) % 4)
        parent = list(range(len(xs)))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        for (k1, _), (k2, _) in occ.values():
            parent[find(k1)] = find(k2)
        pieces = len({find(k) for k in range(len(xs))})
        if len(xs) - 2 * len(xs) + faces != 2 * pieces:
            raise LinkError("not a planar diagram: the PD code does not embed in the sphere "
                            f"(Euler characteristic V-E+F = {len(xs) - 2 * len(xs) + faces}, expected {2 * pieces}); "
                            "check the edge order around each crossing (counter-clockwise from the incoming under-strand)")

    # ---- orientation tracing
    def _trace(self):
        xs = self.crossings
        comps = _walk(xs)
        orient = []
        for path in comps:
            o = None
            for k, s, ex in path:
                if s % 2 == 0:                       # an under pass
                    this = 1 if s == 0 else -1
                    if o is None:
                        o = this
                    elif o != this:
                        raise LinkError("inconsistent orientation: under-strands a->c of one component disagree "
                                        f"(crossing {list(xs[k])})")
            if o is None and self.braid:
                # over-only component: orient it the way the braid runs (downwards)
                k, s, ex = path[0]
                g = self.braid[1][k]
                down_entry = 3 if g > 0 else 1
                o = 1 if s == down_entry else -1
            orient.append(o or 1)
        sign = [0] * len(xs)
        comp_of = {}                                  # (crossing, strand 0/1) -> component
        for ci, path in enumerate(comps):
            for k, s, ex in path:
                comp_of[(k, s % 2)] = ci
                if s % 2 == 1:
                    entry = s if orient[ci] == 1 else ex
                    sign[k] = 1 if entry == 3 else -1
        self._comps, self._orient, self.signs, self._comp_of = comps, orient, sign, comp_of

    # ---- derived facts
    @property
    def n(self):
        return len(self.crossings)

    @property
    def num_components(self):
        return len(self._comps) + self.free_loops

    @property
    def writhe(self):
        return sum(self.signs)

    def is_knot(self):
        return self.num_components == 1

    def components(self):
        """Edge-label lists, one per component with crossings, in orientation order."""
        out = []
        for ci, path in enumerate(self._comps):
            labs = []
            for k, s, ex in path:
                if s % 2 == 0:
                    labs.append(self.crossings[k][0 if self._orient[ci] == 1 else 2])
            # over-only components: collect via over passes
            if not labs:
                for k, s, ex in path:
                    labs.append(self.crossings[k][s])
            out.append(labs)
        return out

    def linking_numbers(self):
        """{(i,j): lk} for components i<j that have crossings."""
        res = {}
        nc = len(self._comps)
        for i in range(nc):
            for j in range(i + 1, nc):
                tot = sum(self.signs[k] for k in range(self.n)
                          if {self._comp_of[(k, 0)], self._comp_of[(k, 1)]} == {i, j})
                res[(i, j)] = tot // 2
        return res

    def mirror(self):
        """Flip every crossing (same projection, over<->under)."""
        new = []
        for c, sg in zip(self.crossings, self.signs):
            a, b, cc, d = c
            new.append((d, a, b, cc) if sg > 0 else (b, cc, d, a))
        br = None
        if self.braid:
            br = (self.braid[0], [-g for g in self.braid[1]])
        L = Link(new, self.free_loops, braid=br, name=(f"mirror({self.name})" if self.name else None))
        return L

    def pd_code(self):
        """Canonical PD: edges renumbered 1..2n along the oriented components."""
        ren, nxt = {}, 1
        for labs in self.components():
            # walk edges in order; for each component list under-in labels, expand to all edges
            pass
        # simple, robust renumbering: follow each component pass by pass
        for ci, path in enumerate(self._comps):
            seq = path if self._orient[ci] == 1 else [(k, ex, s) for k, s, ex in reversed(path)]
            for k, s, ex in seq:
                lab = self.crossings[k][ex]
                if lab not in ren:
                    ren[lab] = nxt
                    nxt += 1
        return [tuple(ren[e] for e in c) for c in self.crossings]

    def pd_string(self):
        s = " ".join("X[%d,%d,%d,%d]" % c for c in self.pd_code()) or "(no crossings)"
        return s + (f"  (+{self.free_loops} free loop(s))" if self.free_loops else "")

    def summary(self):
        w = "0" if self.writhe == 0 else format(self.writhe, "+d")
        return f"{self.num_components} component(s), {self.n} crossing(s), writhe {w}"
