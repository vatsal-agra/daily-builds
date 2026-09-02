# Beacon

A from-scratch 2D robot SLAM (Simultaneous Localization And Mapping)
simulator in pure Python 3 stdlib — no numpy, no robotics libraries.

**Status: Phase 4 (stretch + polish) complete.**

All 4 required features are implemented and demonstrably work end-to-end:

1. Noisy differential-drive robot + ray-cast lidar (`robot.py`, `lidar.py`)
2. Log-odds occupancy-grid mapping (`occupancy_grid.py`)
3. Particle-filter localization / MCL (`pf_localizer.py`, `distance_field.py`)
4. Closed-loop online SLAM tying 1-3 together, with autonomous frontier
   exploration and A* planning as the control loop that drives it
   (`slam.py`, `frontier.py`, `planner.py`)

Both stretch features are shipped too. A* point-to-point navigation
(`--mode waypoints`) and frontier-based autonomous exploration
(`--mode explore`, the default) were both structurally required just to
drive the closed-loop SLAM demo, so they landed during Phase 2/3; Phase 4
added the second stretch deliverable, a self-contained interactive HTML
replay visualizer (`beacon.cli viz`) with play/pause/scrub/speed controls,
toggleable layers (ground truth, SLAM occupancy grid, particle cloud,
lidar rays, planned path, pose trail), and a live HUD — plus CLI input
validation with clean one-line error messages instead of Python
tracebacks.

See `REVIEW.md` for the adversarial-review findings from Phase 3: bugs
found by actually watching multi-hundred-step runs step by step, not just
checking that they ran without throwing (a frontier-search bug that ended
exploration at 26% map coverage, a collision-triggered pose-estimate
runaway that spiked error to 60-80m in a 20x20 world, a planning deadlock,
an infinite-stall bug, unbounded recursion, and an unverified claim in
PLAN.md) — and the fix for each, verified by re-running the exact scenario
that exposed it.

## Try it

```
# run one SLAM session headless and print a metrics report
python3 -m beacon.cli run --world office --max-steps 400

# run all three built-in maps as a quick sanity check
python3 -m beacon.cli demo

# generate an interactive HTML replay you can open in a browser
python3 -m beacon.cli viz --world maze --max-steps 800 --out maze_run.html
```

`--world {open,office,maze}` picks the map (increasing difficulty).
`--mode {explore,waypoints}` picks the control policy; in waypoints mode,
pass one or more `--waypoint X,Y`.

See `PLAN.md` for the full architecture and feature list. The test suite
(`tests/`) and `demo.sh` are next.
