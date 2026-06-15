# Tumble

A from-scratch 2D physics sandbox — **Verlet integration + Position-Based
Dynamics** — with an interactive browser playground, a Python reference engine,
a headless SVG renderer/CLI, and a JS engine that is verified **bit-for-bit
identical** to the Python one.

> Status: **Phase 4 (stretch + polish) complete.** Required features 1–4 plus
> stretch features: tearable cloth, JSON scene save/load + presets, headless
> SVG renderer & CLI `check`, in-playground SVG snapshot download, motion
> trails, velocity-preserving drag, and validated/hardened scene import.

## Quick start

```bash
# CLI (pure Python stdlib, no deps)
python3 -m tumble scenes                              # list preset scenes
python3 -m tumble sim --scene cloth --steps 300 -v    # run headless + diagnostics
python3 -m tumble render --scene ballpit --steps 200 --out shot.svg
python3 -m tumble check                               # physics invariants on all scenes

# Playground: open web/index.html in any browser (no server, no deps)
```

See `PLAN.md` for the architecture and full feature list. Build in progress
(adversarial review, stretch features, verification and ship still to come).
