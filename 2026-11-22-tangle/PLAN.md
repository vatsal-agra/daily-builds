# Tangle — PLAN

## Concept
A from-scratch **knot-theory laboratory**. Give it a knot or link as a braid word
(`1 1 1`), a planar-diagram (PD) code, a catalog name (`4_1`) or a torus knot
(`T(3,5)`), and it tells you *what it is*: it computes the invariants that
topologists use to tell knots apart, **identifies** the knot against a catalog it
builds itself, detects chirality (mirror images), tries to **prove** a diagram is
the unknot by simplifying it, and draws it as SVG.

## Why it's interesting
- First topology / knot-theory build in this repo (everything prior is logic,
  numerics, codecs, compilers, graphics…).
- The invariants are three different mathematical worlds computed by three
  different algorithms that must *agree* with published tables:
  - Jones polynomial — Kauffman bracket state sum (statistical-mechanics flavour),
    done with a frontier/transfer-matrix DP rather than brute-force 2^n.
  - Alexander polynomial — Fox calculus / Wirtinger presentation + exact
    determinant (algebraic topology).
  - Fox p-colorings — linear algebra over GF(p) (combinatorics).
- Identification of a knot from a *scrambled* diagram is a real, checkable test:
  we apply random Reidemeister-type braid moves and Tangle must still say the same thing.

## Architecture (pure stdlib Python 3, no dependencies)
```
tangle/
  poly.py       Laurent polynomials over Z (dict exp->coef), exact division, pretty print
  link.py       Link = PD crossings + free loops; braid->PD; orientation tracing,
                crossing signs, components, writhe, linking numbers, mirror, validation
  jones.py      Kauffman bracket via frontier DP -> Jones polynomial
  alexander.py  Alexander polynomial (exact, Lagrange-interpolated Fraction determinants),
                determinant, Fox p-colorings (GF(p) rank)
  catalog.py    named knots (braid words, discovered + verified by search), torus knots,
                connected sums, invariant table
  identify.py   invariant matching, mirror/chirality, unknot verdicts
  simplify.py   braid-word simplifier (free reduction, braid relations, commutation,
                conjugation, Markov destabilisation) -> unknot proofs
  draw.py       SVG renderer for braid closures with over/under gaps
  cli.py        command line
tests/          unittest suite + demo script
```

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | Diagram model: braid words and PD codes, orientation tracing, crossing signs, components, validation with clear errors, mirror | **required** |
| 2 | Jones polynomial via Kauffman bracket (frontier DP; works on 30+ crossing braids) | **required** |
| 3 | Alexander polynomial (symmetrised, Conway-normalised), knot determinant, Fox p-colorings | **required** |
| 4 | Identification: build own catalog (≤7 crossings + composites), match invariants, report chirality & ambiguity honestly | **required** |
| 5 | Braid simplifier / unknot prover (relations + Markov moves, best-first search) with a printed move log | stretch |
| 6 | SVG diagram renderer (over/under gaps, per-component colour) | stretch |
| 7 | Scrambler + invariance self-check (random equivalence moves must preserve invariants) | stretch |
| 8 | Links: linking numbers, multi-component Jones | stretch |

Target: implement all 4 required, and as many stretch as time allows (aim: 5, 6, 7, 8).
