# REVIEW — adversarial pass on Phase 2

I attacked the build as a hostile reviewer: hostile CLI inputs, resource abuse, odd samples,
benchmarks designed to expose the solver's weak spots, and a look at every produced artifact.
Every finding below was reproduced before it was fixed, and re-run afterwards.

| # | Severity | Finding (how it showed up) | Fix |
|---|----------|----------------------------|-----|
| 1 | High | **Animation HTML was 28.8 MB** for a 30x20 terrain flipbook (and a 1.6 MB PNG for a 900x600 map): the PNG encoder wrote stored (uncompressed) deflate blocks — a lazy shortcut. | Wrote real LZ77 (hash chains) + fixed-Huffman deflate and the PNG Sub filter. Same flipbook is now 1.9 MB, the PNG 34 KB. Output verified by Python's `zlib` and by a from-scratch inflate. |
| 2 | High | `--pin 3,3,+` on the `wires` sample failed with "glyph '+' is not in the sample": glyph lookup went colour→glyph and `+`, `-`, `|` share a colour, so only the first glyph survived. | `Image` now keeps a glyph→colour map for pins; ASCII export keeps its colour→glyph map. |
| 3 | High | `--scale 100000` aborted the process (`memory allocation of 1.5e15 bytes failed`). | Scale limited to 1..64 and 60 megapixels, reported as a normal error. |
| 4 | Medium | `--anim-frames 0 --anim f.html` happily wrote an HTML page with **zero frames** (broken viewer). | Frames must be 2..1000. |
| 5 | Medium | Periodic overlap output smaller than N (e.g. `--size 2x2 --wrap-out`, N=3) "succeeded": the NxN window wraps onto itself, so the result is meaningless though the verifier agreed. | Output must be at least N in both dimensions in either mode. |
| 6 | Medium | The *unsatisfiable* error always gave overlap-specific advice ("smaller --n, --wrap-in…") even for tiled pins, and said "pins/ground" when there were none (e.g. `maze --n 5 --size 60x40` is genuinely unfillable from a non-wrapping 15x15 sample). | Separate, accurate messages for overlap vs tiled. |
| 7 | Medium | No guard on state size: 250k+ cells x hundreds of patterns allocates GBs; a big photo as sample explodes T² propagator memory. | Limits: 250k cells, 12M cell-pattern pairs, 4000 unique patterns, each with a clear message. |
| 8 | Medium | Backtracking default budget (20 000/attempt) made *pure chronological backtracking thrash*: `dungeon --n 3 --wrap-in --wrap-out 50x50` took 8.3 s vs 0.7 s for restart-only. Benchmark exposed it. | Default is now a hybrid: backtrack up to 100 times per attempt, then restart. Same config: 0.3 s with backtracking (and 100% solved); `wires` wrap case is 6x faster than restart-only. |
| 9 | Low | `--ascii` on a PPM sample printed a wall of `#`. | Prints a note instead. |
| 10 | Low | Sample title was pasted unescaped into the flipbook HTML. | HTML-escaped. |
| 11 | Low | Only `.txt`/`.ppm` samples were supported — users' real images (PNG) could not be used. | Added a full PNG decoder (all five 8-bit colour types, all five filters, stored/fixed/dynamic inflate), tested against a zlib-compressed fixture with mixed filters. |

## Checked and found sound
* Determinism: same seed => byte-identical PNG.
* Undo exactness: after arbitrary backtracking, outputs still pass the independent validators
  (no stale support counts) — exercised by the wrap-around benchmarks that backtrack 100+ times.
* 1x1 and 2x1 periodic tiled grids (cell is its own neighbour) solve and verify.
* Bad numbers, missing values, unknown flags, ragged/empty sample files, missing files, pins
  outside the grid, unknown tile names: all give a one-line error and exit code 2.

## Known limitations (documented, not bugs)
* Chronological backtracking is not conflict-directed; on very constrained samples a restart is
  still sometimes better — hence the hybrid budget and the `bench` command.
* Overlap pins constrain the top-left pixel of a pattern cell, not an arbitrary pixel.
