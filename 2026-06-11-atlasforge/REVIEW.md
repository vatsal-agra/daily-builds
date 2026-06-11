# Adversarial Review — Phase 3

Findings from attacking the phase-2 build as a hostile reviewer. Each item
lists severity, evidence, and the fix applied. A fresh run-through after the
fixes must hit none of these.

## F1 — CRITICAL: default CLI invocation crashes

`python3 -m atlasforge.cli --seed 1` raises
`ModuleNotFoundError: No module named 'atlasforge.settlements'` with a raw
traceback. The CLI defaults to `with_settlements=True` but the module was
deferred to phase 4 — i.e. the tool's *front door* was broken and only the
`--no-settlements` path was ever exercised. Worse, the error escapes the
`except ValueError` handler, so the user gets a stack trace instead of a
message.

**Fix:** implement `settlements.py` for real (habitability scoring, seeded
RNG, Markov name generator, founding history) and flip
`generate(with_settlements=...)` default to `True` so the API and CLI agree.
This pulls stretch feature #5 forward; phase 4 still adds stretch #7 polish
on top.

## F2 — HIGH: map JS breaks in DOM environments without Pointer Events APIs

`wrap.setPointerCapture(ev.pointerId)` is called unguarded and
`clientToMap` constructs `new DOMPoint(...)` unconditionally. In any DOM
without those APIs (jsdom used for our tests, older WebKit) the first
pointer event throws and kills panning/inspection.

**Fix:** feature-guard both (`setPointerCapture?.()`, check for
`DOMPoint`/`getScreenCTM` before use, with graceful no-op fallback).

## F3 — MEDIUM (UX): inspector lies about ocean rainfall

Water cells carry a fixed placeholder moisture of 0.5, and the inspector
dutifully reports "rainfall 50%" over open ocean. Misleading data presented
as simulation output.

**Fix:** inspector now shows "open water · depth" for water cells and omits
the rainfall/temperature readout that doesn't apply; land readout unchanged.

## F4 — MEDIUM (simulation quality): marsh over-classification

On seed 42 marsh covered 645 cells vs 224 grassland — every low coastal
strip with decent rain became swamp. Threshold was `alt < 0.06, moisture >
0.82`.

**Fix:** tightened to `alt < 0.04, moisture > 0.9` and required near-water
adjacency (coast or lake neighbor), bringing marsh back to an accent biome
(measured 141-237 cells across seeds 42/7/123) instead of a coastal carpet.

Found while fixing: the Markov name generator emitted clunkers —
unpronounceable starts ("Stmarroor"), stutters ("Thermermer"), and towns
literally named "Marsh" on a map full of marshes. Added rejection filters
(min length 5, no triple-consonant onset, no repeated trigram, biome-word
blocklist).

## F5 — MEDIUM: size limits inconsistent + silent slow path

`worldgen.generate` accepted up to 1.5M cells while the CLI caps at
1024×1024 (~1.05M), and a 512×512 run takes ~15 s with `--quiet` giving no
hint why nothing is happening.

**Fix:** worldgen cap aligned to 1,048,576 cells (=1024²) with the limit
stated in the error; CLI prints an up-front "large map, this may take a
minute" notice (stderr, suppressed only by `--quiet`).

## F6 — LOW (naming/API): `positive_int` is not a positive-int validator

It validates "integer in [16, limit]". Renamed to `dimension` so the
argparse error and the code agree on what is being checked.

## F7 — LOW (JS hygiene): deprecated `substr`

`String.prototype.substr` is legacy. Replaced with `slice`.

## F8 — ACCEPTED: river count scales down on small / land-heavy maps

A 64×64 map at 95% land yields ~1 river because the source threshold is
taken from the top `n/60` accumulation cells, and one giant drainage basin
concentrates them on a single stem. This is geographically defensible (one
basin ⇒ one great river) and rivers never dangle (verified across 12 seeds
plus both land-fraction extremes), so behavior is kept; a code comment now
explains the scaling.

## F9 — ACCEPTED (with rationale): unexpected exceptions still traceback

Only `ValueError`/`OSError` get clean CLI messages. A genuine bug should
fail loudly with a stack trace rather than a vague "something went wrong",
so no blanket `except Exception` was added. F1 removed the only known way
to hit this path in normal use.

## Verification of fixes

`tests/test_atlasforge.py` (phase 5) encodes every non-accepted finding as
a regression test: default-flags CLI run, jsdom DOM smoke test (F2), marsh
share bound (F4), size-cap error message (F5), and the river-termination
sweep that backed F8.
