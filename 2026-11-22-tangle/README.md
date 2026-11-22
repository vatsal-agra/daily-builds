# Tangle — a knot-theory laboratory

Give Tangle a knot or link — as a **braid word**, a **PD code**, a **catalog name** or a **torus knot** —
and it tells you what it is. It computes the invariants topologists use to tell knots apart, identifies the
knot against a catalog it built itself, proves diagrams are the unknot by explicit Reidemeister/Markov
moves, and draws the result as SVG. Pure Python 3 standard library; no dependencies.

```
$ python3 -m tangle analyze --name 5_2
braid        : s1 s1 s1 s2 s1^-1 s2  on 3 strands
PD code      : X[12,6,1,5] X[6,2,7,1] X[2,8,3,7] X[3,11,4,10] X[11,8,12,9] X[9,5,10,4]
structure    : 1 component(s), 6 crossing(s), writhe +4
Jones  V(t)  : t - t^2 + 2t^3 - t^4 + t^5 - t^6
Alexander    : 2t^-1 - 3 + 2t
determinant  : 7
genus bound  : g >= 1   (from the degree of the Alexander polynomial)
Fox colorings: p=3: no; p=5: no; p=7: 42 non-trivial
chirality    : chiral: the Jones polynomial differs from that of its mirror image
VERDICT      : matches catalog entry: 5_2
```

## Run it
```
python3 -m tangle analyze --braid "1 -2 1 -2"                       # braid word (also: "s1 s2^-1 s1 s2^-1")
python3 -m tangle analyze --pd "X[1,4,2,5] X[3,6,4,1] X[5,2,6,3]"   # KnotTheory-style PD code
python3 -m tangle analyze --torus 3,5                                # torus knot T(3,5)
python3 -m tangle analyze --name "Borromean rings" --json
python3 -m tangle simplify --braid "1 2 -1 -2"                       # unknot prover, prints every move
python3 -m tangle draw --name 6_3 -o 6_3.svg --theme dark
python3 -m tangle scramble --name 6_3 --steps 25 --seed 2            # random sound moves; invariants must not change
python3 -m tangle catalog                                            # the catalog + invariants
python3 -m tangle gallery -o gallery.html                            # every diagram + invariants, light/dark

python3 -m unittest discover -s tests                                # 59 tests
python3 tests/demo.py                                                # asserted end-to-end demo (14 checks)
```
A pre-built gallery and SVGs are in `examples/`.

## Features
| | Feature | Notes |
|-|---------|-------|
| 1 | **Diagram model** | braid words & PD codes (KnotTheory convention), orientation tracing, crossing signs, components, writhe, linking numbers, mirror, **planarity check** (Euler characteristic on the rotation system), strict parsing with clear errors |
| 2 | **Jones polynomial** | Kauffman bracket by a frontier / transfer-matrix DP over connectivity patterns — a 40-crossing braid is instant (a 2^n state sum would not finish). Self-checks exponent residues. Cross-validated against an independent brute-force state sum |
| 3 | **Alexander polynomial, determinant, Fox p-colorings** | Wirtinger/Fox matrix, sparse determinant modulo a Mersenne prime chosen above a *proved* coefficient bound (so it is exact), 100 crossings in ~0.1 s. Colorings by rank over GF(p) |
| 4 | **Identification** | catalog of all 14 prime knots ≤ 7 crossings (braid words *found by search* and accepted only if they reproduce the published Alexander polynomial and Jones span), composites, links; matches up to mirror image and reports chirality; links matched up to orientation of components |
| 5 | Braid simplifier / unknot prover | free reduction, braid & conjugation relations, commutation, Markov destabilisation, best-first search with stabilisation/insertion when stuck; prints the move log; *never* claims knottedness it cannot prove |
| 6 | SVG renderer | braid closures with real over/under gaps, per-component colour, light & dark themes |
| 7 | Scrambler + invariance self-check | random sound moves (incl. stabilisation) — invariants must survive and the scrambled diagram must still be identified |
| 8 | Links | linking numbers, multi-component Jones for every orientation class from one bracket, Hopf / Solomon / Borromean / T(2,6) in the catalog |
| + | Conway-notation (2-bridge) constructor | an independent route to 3_1, 4_1, 5_2, 6_1, 7_2, 7_3, 7_6 used to cross-check the braid catalog |
| + | HTML gallery | `tangle gallery` |

## How we know it's right
- Alexander polynomials and determinants of all 14 prime knots agree with the published tables (typed from the standard tables into the test suite, not computed by the code).
- Jones polynomials of trefoil, figure-eight, 5_1, Hopf link, unlinks agree with the literature; the KnotTheory PD codes of 3_1 and 4_1 reproduce KnotTheory's Jones polynomials (convention check).
- Two independent engines must agree: `|V(−1)| = |Δ(−1)|` (Jones vs Alexander), `V(1) = (−2)^(c−1)`, p-colorable ⇔ p | det.
- Closed forms: Alexander of T(p,q), Jones of T(2,n); 2-bridge knots built through Conway notation match the braid catalog.
- Frontier DP == brute-force 2^n state sum on random braids; modular Alexander == exact-Fraction Alexander on random braids.
- Invariance: scrambled diagrams (up to 40 crossings) keep every invariant and are still identified.
- REVIEW.md: 13 findings from a hostile pass, each pinned by a regression test.

## Honest limits
- Catalog scope: prime knots ≤ 7 crossings, four composites, five links. Anything else is reported as "not in catalog" with the Jones-span crossing-number lower bound (tight only for alternating diagrams — e.g. T(3,4)=8₁₉ is reported ≥ 5).
- Invariants can separate, never prove equality: matching Jones+Alexander is strong evidence, not a proof.
- The simplifier is a bounded search: "PROVED unknot" is a certificate (the move list), failure is not evidence of knottedness.
- Drawing and simplifying need a braid representation (every PD can be braided by Vogel's algorithm — not implemented).
- Catalog handedness is whatever the found braid word is; names match up to mirror image and the tool says which.
- A PD component that is *over at every crossing* carries no orientation information in a PD code and is oriented arbitrarily.

## Why I chose this today
The ledger is full of logic, numerics, codecs, compilers and graphics, but no topology. Knot theory is the rare
field where three unrelated algorithms (a statistical-mechanics state sum, Fox calculus over Z[t], linear algebra
over GF(p)) all describe the same object, so every result can be checked against a different one. That made it
possible to build something with real, falsifiable ground truth — and to write an adversarial review that found
real bugs (it accepted non-planar PD codes; link colorings were wrong).

## Where a human could take this next
- Vogel's algorithm / Seifert circles to braid *any* PD, so imported knots can be drawn and simplified.
- HOMFLY-PT and Kauffman polynomials (a larger skein algebra) to separate what Jones+Alexander cannot, and Khovanov homology.
- Extend the catalog to 10-crossing knots (the Rolfsen/Hoste–Thistlethwaite table) via a PD-code loader.
- Signature and Seifert-matrix invariants; unknotting-number bounds.
- Planar-diagram editing (drag crossings, apply Reidemeister moves interactively) in a web UI.
- A link/knot *generator* that enumerates diagrams and builds the catalog up to N crossings automatically.

## Layout
```
tangle/   poly link jones alexander catalog catalog_data identify simplify draw gallery cli
tools/    discover*.py — the search that found the catalog braid words (+ discovered.json)
tests/    test_tangle.py  test_review.py  test_polish.py  demo.py
examples/ gallery.html + SVGs
PLAN.md   REVIEW.md
```
