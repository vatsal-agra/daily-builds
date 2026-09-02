# Beacon

A from-scratch 2D robot SLAM (Simultaneous Localization And Mapping)
simulator, in pure Python 3 standard library — no numpy, no robotics
libraries, no third-party dependencies of any kind.

## What it is

A mobile robot dropped into an unknown building has to answer two
questions at once, each dependent on the other: *"where am I?"* and
*"what does this place look like?"* Guess the map wrong and localization
drifts; guess the pose wrong and the map gets smeared. That coupled
chicken-and-egg problem is SLAM — the algorithm family that lets a robot
vacuum, a warehouse AMR, or a Mars rover build a usable map of its
surroundings from nothing but noisy wheel odometry and a noisy range
sensor, with no GPS and no ground truth.

Beacon builds the real pieces from scratch and wires them into a genuine
closed loop, not two separate demos glued together:

- a noisy differential-drive **motion model** (the standard velocity
  motion model from *Probabilistic Robotics*, not flat Gaussian jitter)
- a ray-cast **lidar** against real wall geometry, with range noise,
  dropouts, and a max range
- a log-odds **occupancy-grid mapper** (Bresenham-traced free/occupied
  fusion)
- a **particle filter** (Monte Carlo Localization) using the
  likelihood-field observation model for O(1)-per-beam weighting
- **A\* path planning** over the robot's own live, partially-built map
- **frontier-based autonomous exploration** — no human waypoints; the
  robot picks its own next destination from what its own map currently
  looks like, and stops on its own once there's nothing left to reveal
- an interactive **HTML replay visualizer** with play/pause/scrub/speed
  controls and toggleable layers

The critical architectural rule, enforced in code and checked by a test
(`test_ground_truth_never_leaks_into_the_grid_or_planner`): the simulator
knows the robot's *true* pose (it's generating the world), but the mapper
and planner only ever see the particle filter's *estimate*. If the
estimate drifts, the map the robot itself would act on drifts with it —
exactly the failure mode real SLAM has to fight, faithfully reproduced
here, and exactly the failure mode the adversarial-review pass in
`REVIEW.md` caught in the act (a single systemic bug that spiked pose
error from sub-meter to 60-80 meters in a 20×20m world) and fixed.

## How to run it

```bash
cd 2026-09-02-beacon

# run one closed-loop SLAM session headless, print a metrics report
python3 -m beacon.cli run --world office --max-steps 400

# run all three built-in maps (open / office / maze) as a sanity check
python3 -m beacon.cli demo

# generate an interactive HTML replay -- open the file in any browser
python3 -m beacon.cli viz --world office --max-steps 400 --out run.html

# drive to explicit waypoints instead of autonomous frontier exploration
python3 -m beacon.cli run --mode waypoints \
    --waypoint 10,2 --waypoint 15,10 --waypoint 3,15

# full verification: test suite + every CLI path + browser smoke test
./demo.sh
```

No install step, no `pip install` needed to run the simulator itself
(`playwright`, used only by `demo.sh`'s optional browser smoke test, is
the one exception, and that step degrades gracefully without it).

## Feature list

**Required (all 4 implemented and verified end-to-end):**

1. Noisy differential-drive robot + ray-cast lidar — `robot.py`, `lidar.py`
2. Log-odds occupancy-grid mapping — `occupancy_grid.py`
3. Particle-filter localization (MCL, likelihood-field model) —
   `pf_localizer.py`, `distance_field.py`
4. Closed-loop online SLAM tying 1-3 together — `slam.py`

**Stretch (both implemented):**

5. A* path planning + explicit point-to-point navigation (`--mode
   waypoints`) — `planner.py`
6. Frontier-based autonomous exploration (`--mode explore`, the default)
   + the interactive HTML replay visualizer — `frontier.py`, `viz.py`

## Why I chose this today

Every prior build in this repo's history that touches "systems built from
scratch" has modeled a *deterministic* system: a language runtime, a data
structure, a renderer, a chess engine (a solved, fully-observable game).
Nothing here had modeled a noisy *physical* agent that has to trust its
own uncertain sensors enough to build a world model while its own position
estimate is simultaneously uncertain. SLAM is the canonical version of
that problem, it combines several individually-interesting, individually-
checkable classical algorithms (ray-segment intersection, Bresenham
tracing, log-odds fusion, sequential importance resampling, A*, frontier
detection), and — because it's a simulation — it's honestly, numerically
self-verifying: ground truth is known to the test harness and never to the
algorithm, so "did SLAM actually work" has a hard, checkable answer
(pose RMSE, map IoU) instead of an eyeballed screenshot.

## Verify it

```bash
./demo.sh                                    # everything, ~60s
python3 -m unittest discover -s tests -v     # just the 80-test suite, ~25s
```

`demo.sh` runs the full test suite, then exercises the CLI's `run`,
`demo`, `waypoints`-mode, and `viz` paths for real, then headless-browser-
smokes the generated visualizer for JS console errors (skipped gracefully,
with a note, if `playwright` isn't installed). Exits non-zero on any
failure.

`REVIEW.md` documents six real bugs an adversarial pass found by watching
multi-hundred-step runs step by step rather than trusting "it ran without
throwing" — including a frontier-search dead end that silently ended
exploration at 26% map coverage, and a collision-triggered particle-filter
runaway that is the single most important bug in this codebase: a case
where *every* particle is wrong in the exact same coherent way, which is
structurally invisible to a particle filter's own weighting (nothing in
the weight spread disagrees), so it can only be prevented, not corrected
after the fact.

## Where a human could take this next

- **Real global localization.** The particle filter here is pose
  *tracking* (roughly-known start, the standard MCL setup) by design —
  see `REVIEW.md` finding #6 for why a naive first attempt at full
  kidnapped-robot-style global localization was descoped rather than
  overclaimed. Augmented MCL (injecting a small fraction of random
  particles when average likelihood drops) is the standard next step.
- **Loop closure.** Nothing here detects "I'm back somewhere I've already
  mapped" and corrects accumulated drift retroactively — the missing
  piece between this and pose-graph SLAM (e.g. GTSAM-style).
- **A learned or richer sensor model.** The likelihood-field model is a
  reasonable, fast approximation; a full beam model (with its own hit/
  short/random/max mixture) or a real point-cloud scan-matcher (ICP)
  would be a natural, much heavier upgrade.
- **Multi-robot SLAM.** The map-building/localization split here already
  factors cleanly enough that a second robot sharing the same occupancy
  grid (with its own separate particle filter) is a plausible extension.
- **3D.** Everything here — ray casting, the occupancy grid, the
  likelihood field, the particle filter's pose representation — has a
  known, well-trodden 3D generalization (voxel grids / octrees, SE(3)
  poses); it's a real jump in complexity, not a small one.
