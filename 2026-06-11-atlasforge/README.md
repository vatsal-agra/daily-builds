# Atlasforge

Procedural fantasy world generator — pure Python, zero dependencies,
renders an interactive single-file HTML map.

**Status:** Phase 3 (adversarial review) complete — 7 findings fixed, 2
accepted with rationale. See [REVIEW.md](REVIEW.md) and [PLAN.md](PLAN.md).

Quick try: `python3 -m atlasforge.cli --seed 42 -o world.html` (run from this
folder), then open `world.html` in a browser.

## Progress

- [x] Phase 1 — Plan
- [x] Phase 2 — Core build (terrain, hydrology, biomes, HTML map)
- [x] Phase 3 — Adversarial review (incl. settlements + Markov names,
      pulled forward to fix the broken default CLI path)
- [ ] Phase 4 — Stretch + polish
- [ ] Phase 5 — Verification
- [ ] Phase 6 — Ship
