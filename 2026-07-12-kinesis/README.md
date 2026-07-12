# Kinesis

Status: **Phase 4 — stretch features + polish complete.** All 3 planned
stretch features are shipped (HTML replay viewer, population gallery,
and now checkpoint resume via `evolve --resume`), verified visually in
headless Chromium, plus CLI input validation and clean error messages
throughout. See [REVIEW.md](REVIEW.md) for every bug found (including
one caught while building the resume feature itself).

Evolving virtual creatures from scratch: procedural body plans, a
from-scratch 2D constraint-based physics engine, evolved CPG motor
controllers, and a genetic algorithm that selects for walking distance
alone. See [PLAN.md](PLAN.md) for the full design and feature list.

## Quick check

```
cd 2026-07-12-kinesis
python3 -m kinesis.cli evolve --generations 6 --pop-size 16 --duration 4.0 --seed 5 --out /tmp/pop.json
python3 -m kinesis.cli replay --checkpoint /tmp/pop.json --rank 0 --out /tmp/replay.html
```

A 6-generation, 16-genome smoke run reliably improves mean population
fitness (e.g. -0.5 &rarr; +1.7) and produces an upright, non-toppled
champion that travels several meters. `replay.html` is a self-contained
animated canvas viewer of the recorded run.

## Notable bugs found and fixed while building this (not yet the formal
adversarial review, just correctness issues caught during core build)

- A missing clamp on the Baumgarte position-correction bias let a single
  bad frame (e.g. a limb slamming into its angle limit) explode into an
  unphysical multi-rotation, multi-meter-per-frame launch on the next
  step. Fixed by clamping the positional error before it's converted to
  a bias velocity (mirrors Box2D's `b2_maxLinearCorrection`).
- A fixed global motor torque constant gave small/light limbs an
  effectively enormous angular acceleration (`alpha = torque / inertia`),
  which evolution could exploit as a thrashing launch instead of a real
  gait. Fixed by scaling each joint's torque limit to its own child
  segment's moment of inertia.
- The genome's depth-repair pass (used after crossover) picked "the node
  with the largest local subtree height" to prune — which is *always*
  the root itself (subtree height strictly decreases going down any
  path), so the loop always immediately no-op'd and depth could grow
  well past the documented `MAX_DEPTH`. Fixed by walking the actual
  deepest root-to-leaf chain.

This README will be rewritten with final run instructions, full feature
list, and results once every phase is complete.
