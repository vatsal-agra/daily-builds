# Atlasforge

Procedural fantasy world generator — pure Python, zero dependencies,
renders an interactive single-file HTML map.

**Status:** Phase 4 (stretch + polish) complete. All 3 stretch features
shipped: settlements with Markov names, JSON export, founding history.
Polish: generated realm titles, zoom-revealed village labels, keyboard
layer shortcuts, compass, hardened input handling.

Quick try: `python3 -m atlasforge.cli --seed 42 -o world.html` (run from this
folder), then open `world.html` in a browser.

## Progress

- [x] Phase 1 — Plan
- [x] Phase 2 — Core build (terrain, hydrology, biomes, HTML map)
- [x] Phase 3 — Adversarial review (incl. settlements + Markov names,
      pulled forward to fix the broken default CLI path)
- [x] Phase 4 — Stretch + polish (all 3 stretch features + UI/UX pass)
- [ ] Phase 5 — Verification
- [ ] Phase 6 — Ship
