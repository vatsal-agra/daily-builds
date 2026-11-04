# Adversarial review (phase 3)

Method: attacked the build as a hostile reviewer — differential fuzzing against the naive
oracle, hostile inputs (huge coordinates, empty/odd files, B0 rules, bad flags), huge step
counts, hash-consing-hostile (chaotic) patterns, and a read of every function for lazy shortcuts.
Every item below was reproduced first, then fixed; the "fresh run-through" at the bottom re-ran
all the reproductions.

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | HIGH | `verify` reported 23 mismatches on random rules with `S0`. Root cause was in the **oracle**, not Hashlife: the naive simulator only visited cells with ≥1 live neighbour, so an isolated live cell never survived under `S0`. A wrong oracle would have "proved" a correct engine wrong (or a wrong engine right). | Naive now keeps live cells with zero neighbours when `S0` is set; 300 trials / ~2,800 comparisons now 0 mismatches. |
| 2 | HIGH | `BBox` walked the quadtree as a *tree*, not a DAG. After `run gosper-gun -gens 2^40` (only ~900 distinct nodes) it tried to visit ~10^11 leaves and hung for minutes. | Memoised per-node bounding boxes: linear in distinct nodes. 2^40 run + bbox now ~10 ms. |
| 3 | HIGH | Chaotic patterns (a 150×150 soup under Seeds, B2/S) make Hashlife's node table grow without bound: no error, 100 s+ of CPU, memory climbing toward OOM. | Hard node budget (`Universe.Budget`, 6M) enforced inside `join`; a hop that exceeds it aborts with `ErrBudget`, the table is compacted, the sim stays valid at the last good generation. Message tells the user to use smaller steps. |
| 4 | MED | Cells with coordinates beyond the quadtree's int64-safe range (e.g. RLE `1000000000000000bo`) would have been placed in a too-small tree and silently corrupted. | `SetCells` validates ±2^50 and returns an error; RLE run-length and cell-count caps (20M cells) added. |
| 5 | MED | `verify -size 0` panicked (`rand.Intn(0)`); `analyze -growth 99` would shift past 2^56. | All numeric flags validated with a clear message. |
| 6 | LOW | `-h` printed usage then `flag: help requested` and exit 1. | Help exits 0 silently. |
| 7 | LOW | Growth exponent could print as `t^-0.00`. | Values within ±0.005 are snapped to 0. |
| 8 | LOW | stdin patterns were named `-`; stdin reader compared `err.Error()` to the string "EOF". | Named `stdin`; uses `io.ReadAll` with a 256 MB cap. |
| 9 | LOW | `FindSettle` horizon code contained a dead first computation of the prediction and a confusing index formula. | Rewritten: `pop(H)` is read from the periodic tail at `cur - ((per - (H-cur) mod per) mod per)`; verified by the 2^24 look-ahead on R-pentomino/acorn matching exactly. |
| 10 | LOW | `periodicTail` had a no-op `if` and a redundant condition. | Simplified; picks the smallest valid period. |

## Known limitations (documented, not bugs)
* Spaceship detection compares pure translations, so a glide-reflection ship is reported at its
  doubled period (glider: period 4, which is the correct minimal translation period).
* "Settles" is a population-series property verified by a Hashlife look-ahead jump, not a proof:
  a ship that collides with debris after the horizon would not be seen.
* B0 rules are rejected (an empty universe would not stay empty on an infinite plane).

## Fresh run-through
Re-ran: all odd-input probes (empty RLE, far-away cell, B0, CRLF files, missing `!`, bad MC reference,
bad flags, `-h`), the 2^40 / 2^50 / 2^56 jumps, the Seeds soup, and `verify -n 300`.
Result: zero of the listed issues reproduce.
