
# Daily Build Ledger

## 2026-06-11 — Atlasforge
- **What:** Procedural fantasy world generator rendering interactive single-file HTML maps (terrain → climate → rivers → biomes → named settlements), deterministic per seed.
- **Stack:** Pure Python 3 stdlib (incl. hand-rolled PNG encoder), inline SVG/JS; jsdom for DOM tests only.
- **Features shipped:** deterministic fractal terrain w/ domain warp; priority-flood hydrology with never-dangling rivers + lakes; wind-advected climate w/ rain shadows; 18 Whittaker biomes; habitability-placed settlements w/ Markov names + founding history; interactive map (4 layers, pan/zoom, inspector, gazetteer fly-to); JSON export; CLI; 31-test suite + demo.sh.
- **Verdict:** Shipped. All 4 required + 3 stretch features done; adversarial review caught a broken default CLI path (fixed) — 31/31 tests green, ~2 s per 160×160 world.

## 2026-06-12 — RegexLab
- **What:** From-scratch regex engine (parser → Thompson NFA → Pike VM with captures → Hopcroft-minimized DFA) with an interactive single-file HTML visualizer that steps the VM over any test string, live threads highlighted in the real automaton.
- **Stack:** Pure Python 3 stdlib; generated HTML embeds a JS mirror of the Pike VM (no deps); Playwright/Chromium for browser tests only.
- **Features shipped:** full parser w/ positioned errors (greedy+lazy quantifiers, classes, anchors, `\b`); `match/fullmatch/search/finditer/findall` w/ groups — differentially fuzzed vs `re`, zero diffs incl. the 3.7 must-advance rule; subset-construction DFA + Hopcroft (Moore-cross-checked, textbook 4-state `(a|b)*abb`); interactive viz (tape, transport, keyboard, NFA+DFA views, capture table); `explain`, verified `gen`, first-class `fuzz` CLI; linear-time — `(a+)+$` ReDoS case in <1 ms.
- **Verdict:** Shipped. 4/4 required + 3/3 stretch; adversarial review found 12 issues (worst: search died at dead spots, `\D` lost negation) — all fixed; 50/50 tests green incl. headless-Chromium JS≡Python parity.
