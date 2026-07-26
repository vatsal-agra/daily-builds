# Kinesis — Evolving Virtual Creatures

## The concept

Build Karl Sims' 1994 "Evolving Virtual Creatures" idea from scratch: a
population of procedurally-generated jointed rigid-body creatures, each
driven by its own evolved neural/oscillator controller, competing on a
single objective — walk as far as possible in a fixed time window. A
genetic algorithm mutates and recombines both **body plan** (how many
limbs, how long, how they branch) and **controller** (motor rhythm)
across generations. There is no hand-designed gait, no imitation data,
no reward shaping beyond "distance traveled" — locomotion has to emerge
from selection pressure alone, on top of a real constraint-based physics
engine we also write from scratch.

## Why this is interesting

- It is a *closed loop*: physics correctness, genome expressiveness, and
  selection pressure all have to work together or nothing evolves. A bug
  in any one of the three shows up as "population fitness never improves"
  — a much harder failure mode to fix than a wrong function return value,
  which makes this a genuinely good adversarial-review target.
- It produces its own content: the specific gaits, limb counts, and body
  shapes that win are not decided in advance by us — they're an *output*
  of the run, discovered from a random initial population.
- It combines three previously-unshipped domains in this repo's history
  (constraint-based 2D rigid body dynamics with joint motors, genome →
  phenotype developmental encoding, population-based evolutionary search)
  in one product, rather than any one of them in isolation.
- It's visually legible: a browser replay of "generation 1 flails and
  falls over" next to "generation 40 walks in a straight line" is an
  immediate, undeniable demonstration that the whole system works, not
  just a passing test suite.

## Architecture

```
genome.py    — genotype: recursive limb-growth grammar (body plan) +
               per-joint CPG oscillator parameters (controller).
               mutation, crossover, random-genome generation.
body.py      — genome -> phenotype: expands the grammar into a tree of
               rigid segments and revolute joints (a "torso" root plus
               recursively attached, optionally mirrored, limbs).
physics.py   — from-scratch 2D rigid body engine: semi-implicit Euler
               integration, sequential-impulse solver for revolute-joint
               point constraints + joint motors (PD servo torque) +
               ground contact (per-corner, with friction), Baumgarte
               stabilization for constraint drift. No engine deps.
simulate.py  — wires a phenotype + physics world together, steps the CPG
               controller each tick, runs for a fixed sim duration,
               records a position trace, computes fitness (distance
               traveled, penalized for falling/toppling and for
               excess motor energy).
ga.py        — population container: tournament selection, elitism,
               structural + parametric crossover, mutation, generation
               loop, fitness history tracking, checkpoint save/load.
viz.py       — renders self-contained HTML: an animated canvas replay of
               any recorded trace, a fitness-over-generations chart, and
               a gallery grid of a population's creatures.
cli.py       — `evolve / replay / viz / gallery / demo / test` subcommands.
```

Design scope decision, stated up front (not a shortcut discovered later):
segments do not collide with each other, only with the ground. Sims-style
creature evolution traditionally disables self-collision too — with it
enabled, early random genomes near-universally lock into unsolvable
interpenetrating configurations and evolution cannot get started. This is
documented here and in the README, not quietly assumed.

## Feature list

**Required (core, must fully work end-to-end):**
1. **Genome → phenotype body-plan generator.** A compact recursive genome
   (max depth, per-node branch count/angle/length/width, mirroring flag)
   expands deterministically into a tree of rigid segments connected by
   revolute joints — producing bipeds, quadrupeds, snake-like chains, and
   asymmetric forms depending on genome, not hand-picked templates.
2. **From-scratch 2D constraint-based rigid body physics engine.** Real
   sequential-impulse solver: revolute joint (point-to-point) constraints,
   PD-servo joint motors with torque limits, ground contact with friction
   and restitution, Baumgarte position correction. Verified against known
   analytic cases (free fall, single pendulum period, resting equilibrium).
3. **Evolved CPG controller, coupled to morphology.** Each joint gets its
   own sinusoidal central-pattern-generator (amplitude, frequency
   multiplier, phase, offset — all genes), so the controller genome has
   to co-evolve with however many joints that particular body plan has.
4. **Genetic algorithm that measurably improves locomotion fitness over
   generations.** Tournament selection + elitism + structural/parametric
   crossover + mutation, run for many generations, with a regression test
   proving mean/best fitness trends upward from a random-genome baseline.

**Stretch (2+, at least 1 shipped):**
5. Interactive self-contained HTML visualizer: canvas replay of any saved
   trace (creature drawn as its real segments/joints, ground line, live
   distance readout, scrub + play/pause), plus a fitness-over-generations
   line chart.
6. Population gallery HTML: a grid showing every creature in a generation
   with its body plan silhouette and fitness, sorted best-first, for
   browsing the whole population rather than just the champion.
7. Checkpoint save/load (JSON) so an evolution run can be paused, resumed,
   or replayed later without re-simulating.

## Fitness function (stated precisely, to be tested, not hand-waved)

`fitness = horizontal_distance_traveled - fall_penalty - energy_penalty`,
where `fall_penalty` triggers if the torso's lowest point crosses below a
"toppled" height threshold and stays there, and `energy_penalty` is a
small coefficient on summed |motor torque| so evolution can't win by
spamming max-torque jitter that happens to net positive drift.
