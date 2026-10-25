#!/usr/bin/env python3
"""Differential test of the exact predicates against a Python Fraction oracle on adversarial inputs.

Cases: random; near-collinear / near-cocircular at many scales (coordinates perturbed by a few ulps);
exactly collinear / cocircular lattice points; huge and tiny magnitudes; translation-offset points.
Prints a summary and exits 1 on the first disagreement (filtered answer, exact answer or oracle)."""
import math, random, subprocess, sys, os
from fractions import Fraction as F

here = os.path.dirname(os.path.abspath(__file__))
exe = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, '..', 'build', 'pred_cli')
N = int(sys.argv[2]) if len(sys.argv) > 2 else 6000
rng = random.Random(20261025)

def hx(v): return float(v).hex()

def orient(a, b, c):
    return (F(a[0])-F(c[0]))*(F(b[1])-F(c[1])) - (F(a[1])-F(c[1]))*(F(b[0])-F(c[0]))

def incircle(a, b, c, d):
    adx, ady = F(a[0])-F(d[0]), F(a[1])-F(d[1])
    bdx, bdy = F(b[0])-F(d[0]), F(b[1])-F(d[1])
    cdx, cdy = F(c[0])-F(d[0]), F(c[1])-F(d[1])
    return ((adx*adx+ady*ady)*(bdx*cdy-cdx*bdy) + (bdx*bdx+bdy*bdy)*(cdx*ady-adx*cdy)
            + (cdx*cdx+cdy*cdy)*(adx*bdy-bdx*ady))

def sgn(v): return (v > 0) - (v < 0)

def nudge(x, ulps):
    for _ in range(abs(ulps)):
        x = math.nextafter(x, math.inf if ulps > 0 else -math.inf)
    return x

def rnd(scale): return rng.uniform(-1, 1) * scale

def case_orient():
    k = rng.randrange(6)
    s = 10.0 ** rng.choice([-30, -8, -1, 0, 1, 6, 30, 100])
    off = rng.choice([0.0, 1e3, 1e9, 0.1]) * s
    a = (rnd(s)+off, rnd(s)+off); b = (rnd(s)+off, rnd(s)+off)
    if k == 0:
        c = (rnd(s)+off, rnd(s)+off)
    elif k == 1:   # near collinear on the segment, jittered by ulps
        t = rng.uniform(-2, 3)
        c = (a[0]+t*(b[0]-a[0]), a[1]+t*(b[1]-a[1]))
        c = (nudge(c[0], rng.randint(-3, 3)), nudge(c[1], rng.randint(-3, 3)))
    elif k == 2:   # exactly collinear lattice points
        m = rng.randint(1, 50); d = (rng.randint(-9, 9), rng.randint(-9, 9))
        a = (float(rng.randint(-99, 99)), float(rng.randint(-99, 99)))
        b = (a[0]+d[0]*m, a[1]+d[1]*m); c = (a[0]+d[0]*(m+rng.randint(-5, 9)), a[1]+d[1]*(m+rng.randint(-5, 9)))
        c = (a[0]+d[0]*rng.randint(-20, 60), a[1]+d[1]*rng.randint(-20, 60))
    elif k == 3:   # classic Shewchuk-style: points on y=x, nudged
        base = rng.uniform(0.5, 1)
        a = (base, base); b = (12.0, 12.0); c = (24.0, 24.0)
        a = (nudge(a[0], rng.randint(-2, 2)), nudge(a[1], rng.randint(-2, 2)))
    elif k == 4:   # two points equal
        c = a if rng.random() < .5 else b
    else:          # nearly identical points
        c = (nudge(a[0], rng.randint(-2, 2)), nudge(a[1], rng.randint(-2, 2)))
    return ('o', [a, b, c])

def case_incircle():
    k = rng.randrange(6)
    s = 10.0 ** rng.choice([-20, -3, 0, 2, 8, 30])
    pts = [(rnd(s), rnd(s)) for _ in range(4)]
    if k == 1:   # d almost on the circle: pick 4 points on a circle, jitter d
        cx, cy, r = rnd(s), rnd(s), abs(rnd(s))+s*1e-3
        th = [rng.uniform(0, 2*math.pi) for _ in range(4)]
        pts = [(cx+r*math.cos(t), cy+r*math.sin(t)) for t in th]
        pts[3] = (nudge(pts[3][0], rng.randint(-3, 3)), nudge(pts[3][1], rng.randint(-3, 3)))
    elif k == 2:  # exactly cocircular lattice points (3-4-5 family)
        R = rng.choice([5, 25, 65, 85, 125, 325])
        sols = [(x, y) for x in range(-R, R+1) for y in range(-R, R+1) if x*x+y*y == R*R]
        pts = [tuple(map(float, rng.choice(sols))) for _ in range(4)]
    elif k == 3:  # unit-square corners (cocircular) with offsets
        o = rng.choice([0.0, 1e8, 0.3])
        pts = [(o, o), (o+1, o), (o+1, o+1), (o, o+1)]
        rng.shuffle(pts)
    elif k == 4:  # nearly coincident
        pts[1] = (nudge(pts[0][0], 1), nudge(pts[0][1], -1))
    elif k == 5:  # nearly collinear triple + d
        t = rng.uniform(0.1, 0.9)
        pts[2] = (pts[0][0]+t*(pts[1][0]-pts[0][0]), pts[0][1]+t*(pts[1][1]-pts[0][1]))
        pts[2] = (nudge(pts[2][0], rng.randint(-2, 2)), nudge(pts[2][1], rng.randint(-2, 2)))
    return ('i', pts)

cases = []
for _ in range(N):
    cases.append(case_orient())
    cases.append(case_incircle())
inp = "".join(k + " " + " ".join(hx(c) for p in pts for c in p) + "\n" for k, pts in cases)
res = subprocess.run([exe], input=inp, capture_output=True, text=True, check=True)
out = res.stdout.split("\n")
zero = {'o': 0, 'i': 0}
mism = 0
for (k, pts), line in zip(cases, out):
    fast, exact = map(int, line.split())
    truth = sgn(orient(*pts) if k == 'o' else incircle(*pts))
    if truth == 0: zero[k] += 1
    if not (fast == exact == truth):
        mism += 1
        if mism <= 5: print("MISMATCH", k, pts, "filtered", fast, "exact", exact, "oracle", truth)
print(f"{len(cases)} cases ({zero['o']} exactly collinear, {zero['i']} exactly cocircular); mismatches: {mism}")
print(res.stderr.strip())
sys.exit(1 if mism else 0)
