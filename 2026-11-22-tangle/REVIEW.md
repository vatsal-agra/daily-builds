# REVIEW — adversarial pass on Tangle (Phase 3)

Method: read every module as a hostile reviewer, then attacked with malformed PDs, nonsense
braids, big diagrams, links with reversed orientation and fuzzed PD mutations
(probe scripts run before fixing; results below are what *actually* happened).

| # | Severity | Finding (as observed) | Fix |
|---|----------|------------------------|-----|
| 1 | **High** | **Non-planar "PD codes" are accepted.** `X[1,5,2,4] X[3,6,4,1] X[5,2,6,3]` (a trefoil PD with two labels swapped) passes validation and returns `V = 1`, `signs=[1,-1,-1]`: confident garbage. Every edge appears twice, so the only check passed. | Euler-characteristic planarity check by tracing faces of the rotation system (`V - E + F = 1 + #components`); rejected with a clear `LinkError`. |
| 2 | **High** | **Fox colorings are wrong for links.** "Trivial" colorings were counted as `p^components`; the standard definition is *monochromatic* (`p`). A 2-component unlink reported 0 non-trivial 3-colorings (it has 6). | Trivial = `p`. Test added (unlink, Hopf, Solomon). |
| 3 | **High** | **Link identification is orientation-fragile.** Jones/Alexander of a link depend on component orientation. `identify` compared against the catalog's orientation only, so the Solomon link with one component reversed would be "not in catalog". | Jones of every orientation class is computed from ONE bracket (`V = (-A^3)^-w <K>`, only the writhe changes); identification matches any orientation variant and the Alexander check is dropped for links (orientation dependent) in favour of components + determinant + Jones variants. |
| 4 | Medium | `parse_pd` silently accepts junk: `"abc 1 2 3 4 xyz"` parses; `"X[1.5,2,3,4]"` is read as five numbers (error message misleading). | Strict character whitelist; message names the offending token. |
| 5 | Medium | Alexander polynomial uses Fraction Gaussian elimination at n+1 points: 0.9 s at 60 crossings, super-cubic beyond; "exact" only because Fractions. | Sparse modular elimination over a Mersenne prime chosen from a *proved* coefficient bound (4^(n-1) by row-norm argument) -> still exact, orders of magnitude faster. |
| 6 | Medium | Jones had no internal consistency check: a bug producing exponents of the wrong residue class would print a plausible polynomial. | After computing, assert exponent residue (`q ≡ 2(c-1) mod 4`); raises `ArithmeticError` on violation. |
| 7 | Medium | `scramble` output is ugly: 38-crossing words that are mostly `s s^-1` litter; unreadable and slow to re-verify. | Expanding moves chosen with low probability, growth capped relative to the starting length. |
| 8 | Medium | Frontier DP has no guard against pathological wide diagrams (10 strands x 50 crossings = 1.6 s; wider would eat RAM). | `max_states` cap (default 400k) raises a clear error telling the user to simplify first. |
| 9 | Low | `simplify` on a *link* prints "not a proof of knottedness" — nonsense wording; also silent when a 0-crossing multi-strand word results (n-component unlink). | Link/knot-aware verdicts: reports "reduced to an n-component unlink" when empty word on n>1 strands. |
| 10 | Low | Report formatting: `lk(1,2) = +0`; unknot prints an empty PD line; chirality line reads "achiral-looking". | Cleaned wording (`0`, `(no crossings)`, "Jones equals its mirror image"). |
| 11 | Low | CLI silently ignores flags that do not apply (`--strands` with `--name`, `--loops` with `--braid`). | Error out instead of ignoring. |
| 12 | Low | Documented limitation never stated: components that are over at every crossing of an imported PD have no orientation information in the PD; we orient them arbitrarily. | Stated in README + `Link` docstring; braid-built links always orient strands downward (already fixed in phase 2 after a test caught a sign flip for exactly this case). |
| 13 | Info | `T(3,4)` (= 8_19, non-alternating) is reported "not in catalog, crossing number >= 5". True but unhelpful: Jones span is only a lower bound there. | Verdict now says the bound is tight only for alternating diagrams; catalog scope stated up front. |

## Fresh run-through
After the fixes every item above is exercised by a regression test in `tests/test_review.py`
(planar rejection, fuzzing of 300 mutated PDs, orientation-reversed Solomon link, colorings on
links, modular Alexander == Fraction Alexander on 200 random braids, wide-diagram cap, CLI
flag misuse, text formatting). Gate: all listed issues are reproduced by a test that fails on
the phase-2 code and passes now (see `tests/test_review.py` docstrings).
