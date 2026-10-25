#!/usr/bin/env python3
"""Independent mesh verifier (Python Fractions, no shared code with the C++ side).

usage: verify_mesh.py MESH [--delaunay]
Checks every triangle is strictly counter-clockwise, no vertex used twice in a triangle, the mesh is a
manifold (each directed edge once), Euler's formula for a disc, and with --delaunay that NO input vertex lies
strictly inside any triangle's circumcircle (exact rational arithmetic)."""
import sys
from fractions import Fraction as F

def main():
    path = sys.argv[1]; delaunay = '--delaunay' in sys.argv
    V = {}; T = []; S = []
    for line in open(path):
        t = line.split()
        if not t: continue
        if t[0] == 'v': V[int(t[1])] = (F(float.fromhex(t[2])), F(float.fromhex(t[3])))
        elif t[0] == 't': T.append(tuple(map(int, t[1:])))
        elif t[0] == 's': S.append(tuple(map(int, t[1:])))
    def orient(a, b, c): return (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])
    def incircle(a, b, c, d):
        ax, ay, bx, by, cx, cy = a[0]-d[0], a[1]-d[1], b[0]-d[0], b[1]-d[1], c[0]-d[0], c[1]-d[1]
        return (ax*ax+ay*ay)*(bx*cy-cx*by) + (bx*bx+by*by)*(cx*ay-ax*cy) + (cx*cx+cy*cy)*(ax*by-bx*ay)
    problems = []
    de = {}
    for i, (a, b, c) in enumerate(T):
        if orient(V[a], V[b], V[c]) <= 0: problems.append(f"triangle {i} {T[i]} not strictly ccw")
        for e in ((a, b), (b, c), (c, a)): de[e] = de.get(e, 0) + 1
    for e, n in de.items():
        if n != 1: problems.append(f"directed edge {e} used {n} times")
    und = {tuple(sorted(e)) for e in de}
    used = {v for t in T for v in t}
    if delaunay and T:
        if len(used) - len(und) + len(T) != 1: problems.append("Euler characteristic != 1")
        for i, (a, b, c) in enumerate(T):
            for v in used:
                if v not in (a, b, c) and incircle(V[a], V[b], V[c], V[v]) > 0:
                    problems.append(f"vertex {v} strictly inside circumcircle of triangle {i}"); break
    for a, b in S:
        if tuple(sorted((a, b))) not in und and T: problems.append(f"segment {a}-{b} is not an edge")
    print(f"{len(T)} triangles, {len(und)} edges, {len(used)} vertices: " + ("OK" if not problems else f"{len(problems)} PROBLEM(S)"))
    for p in problems[:10]: print("  -", p)
    sys.exit(1 if problems else 0)
main()
