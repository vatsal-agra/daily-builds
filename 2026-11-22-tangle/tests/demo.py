"""Runnable end-to-end demo: exercises every feature and ASSERTS on the results.

    python3 tests/demo.py            # prints a narrated run, exits non-zero on any failure
"""
import os
import random
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from tangle import Link, jones, alexander, determinant, colorings, catalog, poly as P
from tangle.identify import identify
from tangle.jones import fmt_jones, jones_orientations, mirror_jones
from tangle.link import parse_pd
from tangle.simplify import simplify, scramble
from tangle.draw import render_svg
from tangle.gallery import build_gallery

EX = os.path.join(ROOT, "examples")
os.makedirs(EX, exist_ok=True)
step = 0


def ok(msg):
    global step
    step += 1
    print(f"[{step:02d}] ok  {msg}")


# F1 - diagram model: braid, PD, signs, components, mirror, validation
L = Link.from_braid("1 1 1")
assert L.signs == [1, 1, 1] and L.num_components == 1 and L.writhe == 3
assert Link.from_pd(parse_pd(L.pd_string())).signs == L.signs
ok("F1  braid -> PD -> reparsed PD keeps crossing signs")
H = catalog.get("Hopf link")
assert H.linking_numbers() == {(0, 1): 1} and H.num_components == 2
ok("F1  Hopf link: 2 components, lk = +1")
try:
    Link.from_pd(parse_pd("X[1,5,2,4] X[3,6,4,1] X[5,2,6,3]"))
    raise SystemExit("non-planar PD accepted!")
except Exception as e:
    assert "not a planar" in str(e)
ok("F1  non-planar PD rejected")

# F2 - Jones
assert fmt_jones(jones(L)) == "t + t^3 - t^4"
assert fmt_jones(jones(catalog.get("4_1"))) == "t^-2 - t^-1 + 1 - t + t^2"
assert jones(Link.from_braid(" ".join(["1", "-2"] * 20))) is not None          # 40-crossing braid, frontier DP
ok("F2  Jones: trefoil, figure-eight, 40-crossing braid")

# F3 - Alexander, determinant, colorings
assert alexander(catalog.get("5_2")) == {-1: 2, 0: -3, 1: 2}
assert determinant(catalog.get("7_7")) == 21
assert colorings(catalog.get("4_1"), 5)["nontrivial"] == 20
ok("F3  Alexander(5_2)=2t^-1-3+2t, det(7_7)=21, 4_1 has 20 non-trivial 5-colorings")

# F4 - identification, chirality, orientation robustness
r = identify(catalog.get("6_2").mirror())
assert r["matches"] == [("6_2", "mirror")]
ok("F4  mirror of 6_2 identified as 6_2 (mirror image)")
pd41 = Link.from_pd(parse_pd("X[4,2,5,1] X[8,6,1,5] X[6,3,7,4] X[2,7,3,8]"))
assert identify(pd41)["matches"] == [("4_1", "both")]
ok("F4  KnotTheory PD of 4_1 identified (amphichiral)")
assert [m[0] for m in identify(catalog.get("Solomon link"))["matches"]] == ["Solomon link"]
ok("F4  link identification up to component orientation")

# F5 - simplifier / unknot prover
res = simplify(3, [1, 2, -1, -2])
assert res["proved_unknot"]
for knot in ("3_1", "5_2", "7_4"):
    assert not simplify(*catalog.get(knot).braid, node_budget=2000)["proved_unknot"]
proved = 0
for seed in range(10):
    n, w = scramble(1, [], steps=14, seed=seed)
    proved += simplify(n, w, 60000)["proved_unknot"]
assert proved >= 9
ok(f"F5  simplifier proves {proved}/10 scrambled unknots, never 'proves' a real knot unknotted")

# F6 - SVG
for name in ("3_1", "6_3", "Borromean rings"):
    for theme in ("light", "dark"):
        svg = render_svg(catalog.get(name), title=name,
                         caption=[f"Jones {fmt_jones(jones(catalog.get(name)))}"], theme=theme)
        ET.fromstring(svg)
        if theme == "light":
            open(os.path.join(EX, name.replace(" ", "_") + ".svg"), "w").write(svg)
ok("F6  SVG drawings written to examples/")

# F7 - scrambler with invariance self-check
rng = random.Random(2026)
checked = 0
for name in ("3_1", "5_2", "6_3", "7_5", "Borromean rings"):
    base = catalog.get(name)
    for _ in range(4):
        n, w = scramble(*base.braid, steps=30, seed=rng.randint(0, 10 ** 9))
        S = Link.from_braid(w, n)
        assert jones(S) == jones(base) and S.num_components == base.num_components
        if base.is_knot():
            assert alexander(S) == alexander(base)
            assert identify(S)["matches"][0][0] == name
        checked += 1
ok(f"F7  {checked} scrambled diagrams: invariants unchanged, still identified")

# F8 - links
B = catalog.get("Borromean rings")
assert B.num_components == 3 and set(B.linking_numbers().values()) == {0} and determinant(B) == 16
assert len(jones_orientations(B)) == 4
ok("F8  Borromean rings: 3 components, all pairwise lk = 0, det 16, 4 orientation classes of Jones")

# gallery + CLI
open(os.path.join(EX, "gallery.html"), "w").write(build_gallery())
ok("    gallery written to examples/gallery.html")
out = subprocess.run([sys.executable, "-m", "tangle", "analyze", "--torus", "2,7"], cwd=ROOT,
                     capture_output=True, text=True)
assert out.returncode == 0 and "7_1" in out.stdout, out.stderr
out = subprocess.run([sys.executable, "-m", "tangle", "analyze", "--braid", "1 q"], cwd=ROOT,
                     capture_output=True, text=True)
assert out.returncode == 1 and "Traceback" not in out.stderr
ok("    CLI as a subprocess: success path and clean failure")

print(f"\nDEMO PASSED ({step} checks)")
