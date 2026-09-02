# Beacon

A from-scratch 2D robot SLAM (Simultaneous Localization And Mapping)
simulator in pure Python 3 stdlib — no numpy, no robotics libraries.

**Status: Phase 3 (adversarial review) complete.** See `REVIEW.md` for the
full list of bugs found by actually watching multi-hundred-step runs step
by step (a frontier-search bug that ended exploration at 26% coverage, a
collision-triggered pose-estimate runaway that spiked error to 60-80m in a
20x20 world, a planning deadlock, an infinite-stall bug, unbounded
recursion, and an unverified claim) and the fixes for each, verified by
re-running the exact scenario that exposed it.

All 4 required features are implemented and demonstrably work end-to-end:

1. Noisy differential-drive robot + ray-cast lidar (`robot.py`, `lidar.py`)
2. Log-odds occupancy-grid mapping (`occupancy_grid.py`)
3. Particle-filter localization / MCL (`pf_localizer.py`, `distance_field.py`)
4. Closed-loop online SLAM tying 1-3 together, with autonomous frontier
   exploration and A* planning as the control loop that drives it
   (`slam.py`, `frontier.py`, `planner.py`)

Try it now:

```
python3 -m beacon.cli run --world office --max-steps 400
```

See `PLAN.md` for the full architecture and feature list. Adversarial
review, polish, the stretch-feature HTML visualizer, and the test suite
are next.
