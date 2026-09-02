# Adversarial review

Attacked the Phase 2 build as a hostile reviewer: ran real multi-hundred-step
SLAM sessions on all three built-in maps and watched what actually happened
step by step, rather than trusting that "it runs without throwing" meant it
worked. This is the log of what broke and how it was fixed. Every fix below
was verified by re-running the same scenario that exposed it.

## Findings

### 1. CRITICAL — frontier search silently ended exploration early because
   it only ever considered the 40 nearest-by-straight-line frontier
   candidates

`select_frontier_goal` sorted all frontier cells by Euclidean distance and
tried A* against only the first 40. In the maze map this is actively wrong:
straight-line-nearest is not path-distance-nearest once walls are involved,
so the 40 "nearest" candidates could all be genuinely unreachable (behind a
wall) while a perfectly reachable frontier sat just past them in path terms.
The bug's actual, observed effect: a run that stopped itself after 131
steps with `exploration_done=True` and 26% of the map explored, while a
frontier count taken immediately after showed 233 frontier cells still on
the board.

**Fix:** replaced the "sort by straight-line distance, retry-A*-per-candidate"
approach with a single multi-target Dijkstra expansion from the robot's own
cell that stops the instant it first touches *any* frontier cell. This is
simultaneously the *correct* nearest-reachable-frontier answer (shortest
path, not as-the-crow-flies) and cheaper than up to 40 separate A* searches.
Re-running the maze scenario after the fix: exploration continued past 700
steps and self-terminated naturally near 1400 steps with 76% of the map
explored (the rest genuinely behind gaps narrower than the robot, verified
by hand against the map).

### 2. CRITICAL — a systematic, uncorrectable pose-estimate runaway
   triggered by physical wall collisions

Longer runs occasionally spiked from sub-meter pose error to 60-80 meters
of error in a 20x20 world -- an obvious, unmissable failure once actually
watched over many steps rather than checked only at a single final step.
Root cause, found by logging every step around the spike: when the robot's
noisy motion would drive it into a wall, `Robot.drive()` correctly rejects
the translation (the robot "bumps" and stays in place) -- but the particle
filter's `predict()` was still being handed the full *commanded* velocity,
so every single particle got advanced by the same coherent distance the
real robot never actually traveled. This is the one failure mode a
particle filter structurally cannot self-correct: it's not disagreement
between particles (which weighting and resampling can fix), it's *all of
them* being wrong together in the same direction, so nothing in the weight
spread ever flags it. Left unfixed, a handful of un-corrected collisions
during exploration was enough to permanently corrupt both the pose estimate
and, through it, the occupancy grid built at that estimate -- exactly the
map-and-localization feedback loop the whole project is about, breaking in
the least recoverable possible way.

**Fix:** two changes, one necessary and one sufficient on its own but both
worth having:
- The estimator is allowed to read the robot's own bump/stall signal (a
  real, physically measurable onboard sensor on a real robot -- motor
  current spike or a literal contact switch -- not ground-truth pose
  leaking in). On a collision step, the particle filter is predicted with
  `v=0` instead of the commanded value, matching what actually happened.
- Independently, a path that produces two collisions in a row is now
  abandoned and replanned rather than retried forever against the same
  wall, and inflation was tightened (`ceil(radius/resolution) + 1` cells
  instead of `round(...)`, since the 8-connected circle test under-covers
  diagonal neighbors) so paths stop clipping corners at all in the first
  place.

Re-running all three maps for 500+ steps after both fixes: final pose error
stayed under 0.7m on every map (previously up to 80m), and pose RMSE across
the whole run stayed under 0.5m.

### 2b. Downstream of #2 — the local "unblock near the robot" escape hatch
   let paths route straight back through the very wall causing the
   collision

Added while chasing #2: to stop the robot from being planning-trapped by
its own inflation radius (see #3), cells near the robot's current position
were unconditionally exempted from the blocked set. That's too broad --
it also exempted cells that are *genuinely* occupied, so a freshly
replanned path could immediately route back into the same wall the robot
had just bounced off. **Fix:** the exemption now only forgives cells that
are blocked purely as inflation fallout (near an obstacle) -- a cell that
is itself classified occupied stays blocked regardless of proximity.

### 3. Planning deadlock: a robot standing near any obstacle could find
   "no path to anywhere," including a goal two cells away

`compute_blocked` inflates obstacles by the robot's radius before running
A*, which is correct -- but if the robot's *own current cell* ends up
inside that inflated region (normal for a robot that has legitimately
pulled up close to a wall without colliding), A* had no legal first move:
every neighbor of the start was blocked, so it reported total
unreachability regardless of the actual goal. **Fix:** `compute_blocked`
takes an optional `keep_clear` cell (the robot's current position) and
un-blocks a matching radius around it after inflation -- see #2b for the
correction that keeps this safe.

### 4. Infinite stall: the robot's own cell could be selected as its own
   exploration goal

If the robot's current cell itself satisfied the frontier definition
(free, bordering an unknown cell), `select_frontier_goal` would return it
as the goal with a zero-length, one-cell path. The robot would "arrive"
instantly without moving, take an identical scan from the identical pose,
and -- if that unknown neighbor sat in a permanent sensor shadow (behind an
obstacle from every angle reachable from that exact cell) -- propose the
same non-move again on the very next replan, forever. **Fix:** the robot's
own cell is now excluded from frontier candidates outright, forcing the
search to find an actually-different cell that might see around the
obstruction.

### 5. Unbounded recursion in waypoint replanning

`_replan()` in `mode="waypoints"` called itself recursively to skip an
unreachable goal and try the next one in the queue. Correct in spirit, but
a long queue of bad waypoints would grow the Python call stack linearly
with no bound. **Fix:** rewritten as a `while`/`else` loop over the queue
-- functionally identical, no recursion.

### 6. Feature 3's literal claim ("converges from initial uncertainty and
   recovers after injected drift") was asserted in PLAN.md but never
   actually exercised in isolation

All prior verification ran the full closed-loop SLAM stack, which
conflates localization quality with mapping quality and makes it
impossible to check the particle filter's convergence/recovery behavior on
its own against a *known-correct* map. Also caught while building this
isolated test: a naive first attempt used full 360-degree initial heading
uncertainty and a fixed circular driving pattern, which is a genuinely hard
global-localization problem prone to perceptual aliasing in a symmetric
office layout -- not what the particle filter here claims to solve (it's a
pose *tracker* with a roughly-known start, the standard MCL setup, not a
kidnapped-robot solver). Kept the test but reworded the PLAN/README claim
to match what's actually being solved, and picked a wandering (not
perfectly repeating) driving pattern for the test so the robot doesn't
loop through the same ambiguous view over and over.

**Fix:** added `tests/test_pf_localizer.py`, which runs the particle
filter alone (real Robot + real lidar + a `metrics.ground_truth_grid()`
map handed in as the "known map") from realistic initial uncertainty
(0.6m/0.6m/~30 degrees) and separately injects a 1.3m position error
mid-run. Confirmed: converges to <0.1m mean error, and recovers to <0.2m
within roughly 20 steps of the injected drift.

## Non-issues considered and deliberately left as-is

- **A dropout beam and a genuine max-range miss both map to `range=None`.**
  Considered giving dropouts a distinct "carries no information at all"
  state, since a real dropout (e.g. a bad return) isn't the same claim as
  "nothing within range." Left as one shared `None` state: real lidar
  hardware reports both cases identically (a lost/ambiguous return also
  just shows up as "no return"), so collapsing them is realistic, not
  lazy -- and both the mapper and the particle filter already treat a
  `None` beam conservatively (free-space-only, or skipped entirely).
- **The occupancy grid marks free space out to `max_range` for a `None`
  beam.** This is the standard, correct occupancy-grid convention (a miss
  is real evidence of no obstacle within range), not a shortcut.
- **A perfectly stationary commanded motion (`v=w=0`) produces zero motion
  noise.** True to the current noise model (variance scales with commanded
  speed), and a reasonable idealization -- real wheel odometry doesn't
  meaningfully drift while genuinely stationary either.
