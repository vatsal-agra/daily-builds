# Beacon — a from-scratch 2D robot SLAM simulator

## Concept

A mobile robot dropped into an unknown building has to answer two questions
at once, each one dependent on the other: *"where am I?"* and *"what does
this place look like?"* Guess the map wrong and localization drifts; guess
the pose wrong and the map gets smeared. This coupled chicken-and-egg
problem is **SLAM** (Simultaneous Localization And Mapping) — the
algorithm family that lets a robot vacuum, a warehouse AMR, or a Mars rover
build a usable map of its surroundings using only noisy wheel odometry and
a noisy range sensor, with no GPS and no ground truth.

Beacon builds the real pieces from scratch: a noisy differential-drive
motion model, a ray-cast lidar, a log-odds occupancy-grid mapper, a
particle-filter (Monte Carlo Localization) pose tracker running the
*likelihood field* observation model, an A* planner that navigates the
robot's own live, partially-built map, and a frontier-exploration policy
that picks where to go next with no human driving it. It's a genuinely new
domain for this repo — every prior "from scratch" build here has been a
language runtime, a data structure, a renderer, or a solved deterministic
game; nothing has modeled a noisy physical agent perceiving and mapping an
environment it doesn't already know, with two probabilistic estimators
feeding each other in a loop.

## Why this is interesting

- It's the textbook problem that makes robotics "hard" — not moving a robot,
  but *trusting your own sensors enough to build a world model while your
  own position estimate is uncertain*. Getting it to actually converge
  (not just runnable code, but a map and a pose estimate that are provably
  close to ground truth after the fact) is a real correctness bar.
- It combines several classical algorithms that are each individually
  interesting and checkable against an oracle: ray-segment intersection,
  Bresenham line tracing, log-odds probability fusion, sequential importance
  resampling, A* over a grid, frontier-based exploration.
- It's naturally self-verifying: because this is a simulation, the ground
  truth pose and ground truth map are *known* to the test harness (never to
  the algorithm) — so "did SLAM actually work" is answerable with a hard
  number (pose RMSE, map IoU) instead of eyeballing a picture.

## Architecture

```
beacon/
  geometry.py       Vec2 math, segment-ray intersection, Bresenham grid
                     line tracing
  world.py          Ground-truth 2D environment: wall segments, built-in
                     maps (open/office/maze), World.raycast(pose, angle)
  robot.py          Differential-drive kinematics + odometry noise model
                     (the standard alpha1..alpha4 sample_motion_model)
  lidar.py          Ray-cast range sensor over the true World: N beams,
                     FOV, Gaussian range noise, random dropouts, max range
  occupancy_grid.py Log-odds occupancy grid: Bresenham-traced free/occupied
                     updates, probability query, inflation for planning,
                     PNG-free ASCII/JSON export
  distance_field.py Multi-source BFS distance transform over an occupancy
                     grid (powers the likelihood-field observation model)
  pf_localizer.py    Particle filter / MCL: predict (motion model),
                     update (likelihood-field weighting), effective-sample-
                     size-triggered systematic resampling, circular-mean
                     pose estimate
  planner.py         A* over an inflated occupancy grid, 8-connected,
                     returns a waypoint path; replans on failure
  frontier.py         Frontier detection (free cells adjacent to unknown)
                     + nearest-frontier selection for autonomous exploration
  slam.py             The orchestration loop: exploration policy -> planner
                     -> motion command -> true robot moves -> lidar scan at
                     true pose -> PF predict/update/resample using ONLY the
                     scan + control + its own current map estimate -> grid
                     updated at the PF's estimated pose (never the true
                     pose) -> repeat. Logs every frame for replay.
  metrics.py          Ground-truth-vs-estimate scoring used only by tests
                     and the CLI report: pose RMSE, map IoU/accuracy
  viz.py              Self-contained HTML canvas replayer generated from a
                     recorded run log
  cli.py              `run / demo / viz / bench` CLI entry point
tests/                 Unit + integration + differential tests
demo.sh                Exercises every feature end-to-end, asserts convergence
```

No third-party dependencies — pure Python 3 standard library, matching this
repo's house style. Grid sizes (~100x100 cells), particle counts (~300-500)
and beam counts (~48-72) are chosen so a full multi-map SLAM run completes
in a few seconds of pure-Python compute.

## Feature list

1. **[required] Noisy differential-drive robot + ray-cast lidar.** A real
   kinematic motion model with the standard odometry noise parameters
   (translation/rotation error compounding realistically, not just flat
   Gaussian jitter on x/y), and a lidar that ray-casts against actual wall
   geometry (not a lookup table) with configurable FOV/beam count/noise/
   dropout/max-range.

2. **[required] Log-odds occupancy-grid mapping.** Converts a stream of
   (pose, scan) pairs into a probabilistic occupancy grid via Bresenham ray
   tracing (mark traversed cells free, endpoint cell occupied), log-odds
   fusion with clamping, correctly handling max-range (non-hit) beams by
   marking free space only, not a phantom wall.

3. **[required] Particle-filter localization (Monte Carlo Localization).**
   Tracks robot pose using only odometry + lidar — never given ground
   truth — via the likelihood-field observation model (a precomputed
   distance-to-nearest-obstacle field, so per-beam weighting is O(1) rather
   than re-raycasting per particle), systematic resampling triggered by
   effective sample size, and a circular-mean pose estimate. Must converge
   from initial pose uncertainty to low error and *recover* after
   deliberately injected extra drift.

4. **[required] Closed-loop online SLAM.** Ties 2 and 3 together for real:
   the robot explores with *no* ground-truth pose ever touching the mapper
   — the occupancy grid is built at the particle filter's *estimated* pose
   each step, and the particle filter's likelihood-field weighting reads
   from that same live, still-imperfect grid. This is the actual chicken-
   and-egg SLAM loop, not two independent demos. Scored after the fact
   (test-only) against the true map/pose the algorithm never saw.

5. **[stretch] A* path planning + autonomous point-to-point navigation.**
   Plans over the robot's own live (partially unknown, obstacle-inflated)
   occupancy grid to reach a goal, drives it there via the same noisy
   motion model, and replans when the previously-planned path turns out to
   be blocked by a cell discovered late.

6. **[stretch] Frontier-based autonomous exploration + interactive HTML
   replay visualizer.** A policy that needs no preset waypoints: it finds
   frontier cells (known-free, adjacent-to-unknown), picks the nearest
   reachable one via the planner, and repeats until the map stops growing.
   Paired with a self-contained HTML/Canvas visualizer (embedded run-log
   JSON, vanilla JS, no dependencies) that replays a full run frame by
   frame — ground truth map, live SLAM occupancy heatmap, particle cloud,
   lidar rays, planned path — with play/pause/scrub/speed controls.

## Verification approach

Ground truth is available to the simulator (it's generating the world) but
is architecturally firewalled from every estimation algorithm — `slam.py`
only ever passes the PF's own estimate into the mapper, never the true
pose. Tests then use ground truth purely as an oracle: raycast correctness
against hand-computed intersections, Bresenham traces checked against a
brute-force "which cells does this segment cross" reference, A* path cost
checked against a BFS/Dijkstra oracle on the same grid, and — the real
gate — end-to-end SLAM runs on multiple built-in maps asserting final pose
RMSE and map IoU cross fixed thresholds, with a regression check that a
*disabled* particle filter (odometry-only dead reckoning) produces
measurably worse pose error than the full filter on the same run, proving
the lidar correction is doing real work and not just decoration.
