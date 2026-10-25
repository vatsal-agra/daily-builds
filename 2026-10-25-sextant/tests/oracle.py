#!/usr/bin/env python3
"""Independent exact oracle: reads lines "o ax ay bx by cx cy" / "i ax ay bx by cx cy dx dy" with
coordinates as hex floats, prints the exact sign computed with Python Fractions (shares no code with C++)."""
import sys
from fractions import Fraction as F

def f(s): return F(float.fromhex(s))

def orient(a, b, c):
    return (a[0]-c[0])*(b[1]-c[1]) - (a[1]-c[1])*(b[0]-c[0])

def incircle(a, b, c, d):
    adx, ady = a[0]-d[0], a[1]-d[1]
    bdx, bdy = b[0]-d[0], b[1]-d[1]
    cdx, cdy = c[0]-d[0], c[1]-d[1]
    return ((adx*adx+ady*ady)*(bdx*cdy-cdx*bdy) + (bdx*bdx+bdy*bdy)*(cdx*ady-adx*cdy)
            + (cdx*cdx+cdy*cdy)*(adx*bdy-bdx*ady))

def sgn(v): return (v > 0) - (v < 0)

for line in sys.stdin:
    t = line.split()
    if not t: continue
    v = [f(x) for x in t[1:]]
    pts = [(v[i], v[i+1]) for i in range(0, len(v), 2)]
    print(sgn(orient(*pts)) if t[0] == 'o' else sgn(incircle(*pts)))
