# Beacon

A from-scratch 2D robot SLAM (Simultaneous Localization And Mapping)
simulator in pure Python 3 stdlib — no numpy, no robotics libraries.

**Status: Phase 2 (core build) complete.** All 4 required features are
implemented and demonstrably work end-to-end:

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
