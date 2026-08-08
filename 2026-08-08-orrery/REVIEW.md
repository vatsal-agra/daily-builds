# Adversarial review (Phase 3)

Methodology: attacked the CLI and library directly as a hostile user —
invalid/extreme arguments, missing/corrupt files, degenerate scenario
configurations, numerically pathological physics setups (near-singular
close encounters, absurd timesteps), and a real-browser pass over every
generated HTML report (headless Chromium via Playwright, checking for
JS console/page errors) plus a visual read of the screenshots.

## Bugs found and fixed

1. **CRITICAL — raw `ZeroDivisionError` traceback on `--n 0` / negative
   `--n`.** `orrery run --scenario plummer_cluster --n 0` (or a negative
   count) crashed with an unguarded Python traceback instead of a clean
   error: `_sample_plummer` divided `total_mass / n` with `n <= 0`
   (`range(-3)` silently iterates zero times, so a negative count didn't
   even fail loudly at the loop — it failed later, confusingly, inside
   `_recenter`'s momentum division). Fixed with upfront validation in
   `plummer_cluster`, `galaxy_collision`, and `_sample_plummer` itself
   (defense in depth), all raising a clear `ValueError` the CLI already
   knows how to report cleanly.

2. **CRITICAL — raw, uncaught `OverflowError` on a close encounter with
   zero softening.** Two bodies at a physically tiny but nonzero
   separation (`distance^2` around `1e-206`, reachable in any
   `softening=0` run — including the Kepler-oracle-style two-body setups
   this project's own tests use) blow `dist_sq ** -1.5` past float range.
   This raised a bare `(34, 'Numerical result out of range')`
   `OverflowError` from deep inside `bruteforce.py`/`octree.py`, which
   `Simulation.step`'s "did the state go non-finite" safety net never got
   a chance to catch (the exception happens *while computing* the
   acceleration, before that check runs) — so it surfaced as an
   unhandled traceback all the way up through the CLI. Fixed by catching
   `OverflowError` at both force-computation call sites (brute force, and
   both the leaf and internal-node branches of Barnes-Hut) and re-raising
   as the same `FloatingPointError` the rest of the system already
   handles cleanly, with a message naming the two bodies involved and the
   actual fix (use `softening > 0`). Verified the "genuinely diverged"
   guard itself still fires correctly and cleanly on injected non-finite
   state (an artificially huge finite velocity that overflows position to
   `inf` in one drift step) — that path was already correct; only the
   overflow-*during*-force-computation path was missing a catch.

3. **UX bug — a UI field that could never work.** The trajectory viewer's
   "Selected body" panel has a `|v|` (speed) row. It was permanently
   hardcoded to an em dash placeholder, because per-frame velocity was
   never included in the data exported to the HTML report in the first
   place — the feature was wired up on the display side but the data it
   needed was never sent. Fixed by exporting velocity components per body
   per frame and computing the real speed magnitude client-side.

4. **UX bug — every body rendered at (almost) the same size.** Marker
   radius mixed a body's *physical* radius (meaningful in AU, where even
   the Sun's radius is ~0.06) with the camera's *zoom* scale, so nearly
   every body — including the Sun next to Mercury — clamped to the same
   2.2px minimum. The screenshot from the first working build showed a
   solar system where you could not tell the star from the planets.
   Fixed with marker size driven by each body's mass *relative to the
   other currently-alive bodies in that frame* (log-scaled, independent
   of both physical units and camera zoom), which reads correctly for
   both a six-order-of-magnitude range (Sun vs. Mercury) and a
   near-uniform one (Plummer cluster stars).

5. **UX bug — the default camera view was useless for realistic orbit
   scales.** "Fit all" scales to the single farthest body ever recorded;
   for the solar system (Mercury at 0.4 AU vs. Neptune at 30 AU) that
   compresses everything inside Jupiter's orbit into a handful of
   overlapping pixels at screen center — the interesting part of the
   scene is invisible by default. Added a second camera preset, "Fit
   inner (median)", that frames a few times the *median* body distance
   instead of the max, with the existing pan/zoom available to reach the
   rest.

6. **Minor — silently ignored flags.** `--n`/`--seed` did nothing when
   passed with a scenario that doesn't take a body count (`solar_system`,
   `binary_star`, `figure_eight`) — no error, no acknowledgment, just
   silently discarded. Now prints a one-line note to stderr instead of
   pretending the flag had no bearing on the run.

## A finding that wasn't a bug, but needed evidence, not a claim

The plan promised a Barnes-Hut speed benchmark. The first version of it
used N up to only 300 — and at that range, **Barnes-Hut is slower than
brute force** (0.28x-0.68x "speedup" at N=10/30/100 in pure Python): tree
construction overhead dominates until there are enough bodies for
O(N log N) to actually beat O(N²). That's real and expected, not a
regression, but shipping a benchmark whose N range never crosses the
break-even point would have quietly misrepresented the feature. Extended
the default benchmark range to N=1000, where Barnes-Hut wins by ~2.3x
(and by ~4.7x at N=2500 in ad hoc testing), and added an explicit demo
check that the crossover actually happens by N=1000 rather than assuming
it. The benchmark report now shows the honest curve, overhead included.

## Things deliberately checked and found correct (not re-litigated)

- Checkpoint load/resume against: a missing file, corrupt JSON, JSON
  missing required fields, and a checkpoint with an empty body list — all
  four produce a clean one-line `ERROR:` message and exit code 1, no
  tracebacks.
- Pathologically large `dt` (up to `1e30`) does *not* crash — the
  simulation runs to completion with a large, honestly-reported energy
  drift (this is expected: an unreasonable timestep is bad physics, not
  undefined behavior; the printed drift number is the signal a user
  should notice). The genuine-divergence guard (`FloatingPointError` on
  non-finite state) was separately confirmed to fire correctly when state
  actually does go non-finite (tested with an injected extreme velocity
  that overflows position to `inf` in a single step).
- A single-body Plummer "cluster" (`--n 1`) is a legitimate degenerate
  case: recentering zeroes the lone body's velocity, since its own
  momentum defines the frame's center of mass. Correct, not a bug.
- Every scenario (`solar_system`, `binary_star`, `figure_eight`,
  `plummer_cluster`, `galaxy_collision`) run through the CLI end-to-end,
  including `--bruteforce`, `--collisions`, and `--method euler`
  combinations, and every generated HTML report opened in headless
  Chromium with zero page/console errors.

## Gate

A fresh run-through (`orrery demo`, plus the manual adversarial commands
above, plus a full Playwright pass over every generated report) after
these fixes hits none of the issues listed above.
