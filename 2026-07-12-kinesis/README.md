# Kinesis

**Evolving virtual creatures, built entirely from scratch** — in the
spirit of Karl Sims' 1994 "Evolving Virtual Creatures": a population of
procedurally-generated jointed rigid-body creatures, each driven by its
own evolved motor controller, competing on a single objective — walk as
far as possible. No hand-designed gait, no imitation data, no reward
shaping beyond "distance traveled." A genetic algorithm mutates and
recombines both body plan and controller across generations, on top of
a real constraint-based 2D physics engine also written from scratch.

Status: **shipped.** All 4 required features and all 3 stretch features
are implemented, adversarial-reviewed, tested (49 tests, all green), and
demonstrated end-to-end via `demo.sh`.

## What it is

- **`kinesis/genome.py`** — a compact, mutable, GP-style tree genotype: a
  recursive limb-growth grammar (body plan) plus per-joint CPG (central
  pattern generator) motor parameters. The same rules produce bipeds,
  quadrupeds, snake-like chains, and asymmetric forms depending on what a
  particular genome happens to encode — nothing is a hand-picked template.
- **`kinesis/body.py`** — expands a genome into a phenotype: a tree of
  rigid segments connected by revolute joints, positioned by forward
  kinematics so every joint's anchor points exactly coincide at
  construction (the solver starts from zero constraint error).
- **`kinesis/physics.py`** — a from-scratch 2D constraint-based rigid
  body engine: semi-implicit Euler integration, a sequential-impulse
  (Gauss-Seidel) solver for revolute joints (point-to-point constraint +
  PD-servo motor + one-sided angle limit) and ground contact (Coulomb
  friction), with Baumgarte position-bias stabilization. The same family
  of algorithm real engines like Box2D use — nothing here calls into an
  external physics library.
- **`kinesis/simulate.py`** — wires a genome + physics world together,
  steps the CPG controller each tick, and scores the run: fitness
  rewards distance traveled and penalizes toppling over and gratuitous
  motor effort.
- **`kinesis/ga.py`** — tournament selection with elitism, subtree-graft
  crossover, gaussian-perturbation + structural mutation, run for many
  generations, with fitness history tracking and JSON checkpointing.
- **`kinesis/viz.py`** — self-contained HTML: an animated canvas replay
  of any recorded run, a population gallery, and a fitness-over-generations
  chart. No CDN, no build step, no server.
- **`kinesis/cli.py`** — `evolve` / `replay` / `gallery` / `fitness-chart`
  / `demo` / `test` subcommands.

## Run it

```
cd 2026-07-12-kinesis

# quick smoke run (~1 minute)
python3 -m kinesis.cli demo

# a real run
python3 -m kinesis.cli evolve --generations 60 --pop-size 80 --duration 6.0 --out data/population.json
python3 -m kinesis.cli replay --checkpoint data/population.json --rank 0 --out replay.html
python3 -m kinesis.cli gallery --checkpoint data/population.json --out gallery.html
python3 -m kinesis.cli fitness-chart --checkpoint data/population.json --out fitness.html

# continue a previous run instead of starting over
python3 -m kinesis.cli evolve --resume data/population.json --generations 40 --out data/population.json

# full test suite (49 tests, ~2-4 minutes) and the full feature demo
python3 -m kinesis.cli test
./demo.sh
```

Open any of the generated `.html` files directly in a browser — they're
fully self-contained (no server needed).

## Feature list

**Required (all 4 fully implemented, no stubs):**
1. Genome &rarr; phenotype body-plan generator (recursive limb grammar,
   deterministic expansion, mirrored limb pairs).
2. From-scratch 2D constraint-based rigid body physics engine
   (sequential-impulse solver, motorized/limited revolute joints, ground
   contact + friction) — verified against analytic free-fall and
   physical-pendulum-period formulas.
3. Evolved CPG controller coupled to morphology (every joint gets its
   own oscillator genes; the controller genome co-evolves with however
   many joints that body plan happens to have).
4. Genetic algorithm that measurably improves locomotion fitness over
   generations (tournament selection, elitism, crossover, mutation) —
   proven both by a guaranteed-by-construction monotonic-best-fitness
   test and a from-random-baseline improvement test.

**Stretch (all 3 implemented):**
5. Interactive self-contained HTML replay viewer (canvas animation,
   camera follows the creature, scrub + play/pause, distance readout).
6. Population gallery HTML (every creature in a generation, sorted by
   fitness, with a rest-pose silhouette).
7. Checkpoint save/load with a real `evolve --resume` — pause a long
   run and continue it later without re-simulating anything already
   evaluated.

## Why this, today

Most of this repo's recent builds have been single from-scratch systems
(a VCS, a crypto suite, a physics playground, a database). Kinesis
combines three of those domains — constraint-based rigid body dynamics,
a developmental genome-to-phenotype encoding, and population-based
evolutionary search — into one closed loop where all three have to work
correctly together or nothing evolves. That made it a genuinely
different kind of adversarial-review target: a bug doesn't show up as a
wrong return value, it shows up as "population fitness stops improving"
or "the champion is doing something suspicious," which is a much harder
failure mode to notice and a much more interesting one to hunt down (see
[REVIEW.md](REVIEW.md) — several of the 10 real bugs found were exactly
this kind: silent, no crash, just wrong). It's also the first project in
this repo's history to produce its own content: the specific gaits, limb
counts, and body shapes that win aren't decided in advance, they're an
*output* of a run starting from a random population.

## What the adversarial review found

10 real issues, all fixed and re-verified — see [REVIEW.md](REVIEW.md)
for full detail on each. Highlights:

- **Two physics bugs that looked like "creative" evolved behavior but
  weren't**: an unbounded Baumgarte position-correction bias let a
  single bad frame explode into an unphysical 10-rotation, 28 m/s launch
  (fixed with a correction clamp, the same fix Box2D uses); a fixed
  global motor-torque constant gave small limbs an effectively enormous
  angular acceleration, letting evolution "win" via thrashing instead of
  walking (fixed by scaling torque to each joint's own moment of
  inertia).
- **Two genome-invariant bugs**: the depth-repair pass after crossover
  picked "the node with the largest local subtree height" to prune —
  which is *always* the root (subtree height strictly decreases going
  down any path) — so it silently never trimmed anything, and genome
  depth could grow well past the documented bound. A related bug in
  random-genome generation (`_grow`) checked node counts against the
  wrong subtree's size, letting a *freshly generated* genome (not just
  one from crossover) exceed the segment cap — caught by the plainest
  possible test ("generate 20 genomes, check the documented invariant"),
  not a clever one.
- **A NaN-propagation correctness bug** with no crash and no obvious
  symptom: a numerically unstable genome's NaN fitness could silently
  corrupt GA selection, because `max(..., key=...)` treats every NaN
  comparison as `False` — so a NaN landing first in iteration order can
  never be beaten by a later, genuinely better individual.
- Several CLI/API robustness issues: raw tracebacks on missing/malformed
  files, a crash discarding a long evolution run because the output
  directory didn't exist, and a duplicate-history-entry bug found while
  building the `--resume` feature itself.

## Where a human could take this next

- **True neuroevolution instead of fixed-topology CPGs.** Each joint's
  oscillator is currently 4 genes (amplitude/frequency/phase/offset)
  with no sensor feedback beyond the CPG's own clock. A small recurrent
  network per creature (sensing joint angles and ground contact) would
  let genuinely reactive behaviors emerge — recovering from a stumble,
  adapting gait to a slope — the way Sims' original work did.
- **3D.** The physics engine, genome, and GA are all 2D-sagittal-plane
  by construction (see the "no self-collision, mirrored limbs share an
  attach point" design note in `PLAN.md`). A 3D rigid-body engine with
  real left/right limb pairs and out-of-plane balance would be a much
  harder and more interesting physics problem.
- **Terrain and obstacles.** Currently a flat infinite ground plane.
  Slopes, gaps, and obstacles would select for robustness, not just raw
  speed, and could support co-evolving environment difficulty
  (a curriculum) alongside the creatures.
- **Multi-objective selection.** Fitness is currently a single scalar
  (distance, penalized for topple/energy). Pareto-front selection across
  distance/energy/stability would surface a *diversity* of viable
  strategies (efficient plodders vs. fast sprinters) instead of
  collapsing to one winner.
- **Speciation.** NEAT-style genome distance + fitness sharing would let
  structurally different body plans (bipeds vs. snakes) coexist and
  develop in parallel instead of one early lineage dominating the
  tournament.
