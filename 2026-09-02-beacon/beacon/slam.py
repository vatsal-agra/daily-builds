"""The orchestration loop that turns the individual pieces into actual
SLAM: exploration policy -> planner -> motion controller -> true robot
motion -> lidar scan -> particle-filter predict/update/resample -> map
update at the *estimated* pose.

This module is the one place ground truth and estimate coexist, and the
boundary is deliberate and enforced by what gets passed where:
  - `self.robot.pose`      is ground truth. It only ever feeds the true
                            World's raycast (lidar.scan) and the frame log
                            (for the visualizer / metrics to read *after*
                            the fact). It is never passed to `self.pf` or
                            `self.grid`.
  - `self.pf.estimate()`   is the only pose ever handed to
                            `self.grid.integrate_scan(...)` or to the
                            planner. If the estimate drifts, the map the
                            robot itself would act on drifts with it --
                            exactly the failure mode real SLAM has to
                            fight, faithfully reproduced here.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import frontier, planner
from .distance_field import DistanceField
from .geometry import normalize_angle
from .lidar import LidarSpec, scan as lidar_scan
from .occupancy_grid import OccupancyGrid
from .pf_localizer import ObservationModel, ParticleFilter
from .robot import MotionNoise, Pose, Robot
from .world import World, make_world

START_POSE = (2.0, 2.0, 0.0)


@dataclass
class SlamConfig:
    world_name: str = "office"
    resolution: float = 0.3
    num_particles: int = 300
    dt: float = 0.2
    max_v: float = 1.2
    max_w: float = 1.8
    goal_tolerance: float = 0.35
    robot_radius: float = 0.3
    lidar: LidarSpec = field(default_factory=LidarSpec)
    reality_noise: MotionNoise = field(default_factory=lambda: MotionNoise(0.01, 0.01, 0.01, 0.01, 0.0, 0.0))
    belief_noise: MotionNoise = field(default_factory=lambda: MotionNoise(0.05, 0.05, 0.05, 0.05, 0.01, 0.01))
    obs_model: ObservationModel = field(default_factory=ObservationModel)
    df_every: int = 4  # recompute the distance field every N steps
    seed: int = 42
    disable_pf_update: bool = False  # dead-reckoning baseline, for regression tests
    mode: str = "explore"  # "explore" (frontier) or "waypoints" (explicit goals)
    waypoints: Tuple[Tuple[float, float], ...] = ()


@dataclass
class Frame:
    t: int
    true_pose: Pose
    est_pose: Pose
    neff: float
    beam_endpoints: List[Tuple[float, float]]
    path_world: List[Tuple[float, float]]
    goal_reached_count: int
    collided: bool


def follow_path(
    pose: Pose,
    waypoints_world: List[Tuple[float, float]],
    index: int,
    goal_tolerance: float,
    max_v: float,
    max_w: float,
    k_theta: float = 2.5,
) -> Tuple[float, float, int, bool]:
    """Proportional pure-pursuit-ish controller: turns toward the next
    waypoint, throttling forward speed while turning sharply. Returns
    (v, w, new_index, finished)."""
    x, y, theta = pose
    n = len(waypoints_world)
    while index < n:
        tx, ty = waypoints_world[index]
        if math.hypot(tx - x, ty - y) < goal_tolerance:
            index += 1
            continue
        break
    if index >= n:
        return 0.0, 0.0, index, True

    tx, ty = waypoints_world[index]
    dx, dy = tx - x, ty - y
    desired_heading = math.atan2(dy, dx)
    angle_err = normalize_angle(desired_heading - theta)
    w = max(-max_w, min(max_w, k_theta * angle_err))
    slow = max(0.0, 1.0 - abs(angle_err) / (math.pi / 2))
    v = max_v * slow
    return v, w, index, False


class SlamRun:
    def __init__(self, config: SlamConfig):
        self.cfg = config
        self.rng = random.Random(config.seed)
        self.world: World = make_world(config.world_name)

        self.robot = Robot(
            self.world, START_POSE, radius=config.robot_radius,
            noise=config.reality_noise, rng=random.Random(config.seed + 1),
        )
        self.grid = OccupancyGrid(self.world.width, self.world.height, config.resolution)
        self.pf = ParticleFilter(
            num_particles=config.num_particles,
            init_pose=START_POSE,
            init_std=(0.15, 0.15, 0.1),
            motion_noise=config.belief_noise,
            obs_model=config.obs_model,
            rng=random.Random(config.seed + 2),
        )
        # Inflate a full cell more than the robot's own radius strictly
        # requires: the 8-connected "circle" test in planner.compute_blocked
        # under-covers diagonal neighbors (dc*dc+dr*dr<=r*r with r=1 only
        # keeps the 4 orthogonal cells), and the robot's continuous-space
        # center can sit anywhere within its cell, not just at the center.
        # Without the safety margin the planner routes paths that clip
        # corners the real, continuous-space collision check then rejects.
        self.robot_radius_cells = max(2, math.ceil(config.robot_radius / config.resolution) + 1)
        self.dfield: Optional[DistanceField] = None

        self.current_path_cells: List[Tuple[int, int]] = []
        self.current_path_world: List[Tuple[float, float]] = []
        self.path_index = 0
        self.goal_queue: List[Tuple[float, float]] = list(config.waypoints)
        self.exploration_done = False
        self.goals_reached = 0

        self.frames: List[Frame] = []
        self.true_poses: List[Pose] = []
        self.est_poses: List[Pose] = []
        self.consecutive_collisions = 0
        self.avoid_cells: Dict[Tuple[int, int], int] = {}
        self.current_goal_cell: Optional[Tuple[int, int]] = None

    # -- planning --------------------------------------------------------------
    def _replan(self) -> None:
        if self.cfg.mode == "waypoints":
            # Drop unreachable goals one at a time until one plans or the
            # queue empties -- a loop, not recursion, so a long list of
            # bad waypoints can never blow the call stack.
            while self.goal_queue:
                est = self.pf.estimate()
                start_cell = self.grid.world_to_cell(est[0], est[1])
                gx, gy = self.goal_queue.pop(0)
                goal_cell = self.grid.world_to_cell(gx, gy)
                self.current_goal_cell = goal_cell
                blocked = planner.compute_blocked(
                    self.grid, self.robot_radius_cells, allow_unknown=True, keep_clear=start_cell
                )
                path = planner.astar(
                    self.grid, start_cell, goal_cell, self.robot_radius_cells,
                    allow_unknown=True, blocked=blocked,
                )
                if path is not None:
                    break
            else:
                self.current_path_world = []
                self.exploration_done = True
                return
        else:  # frontier exploration
            est = self.pf.estimate()
            start_cell = self.grid.world_to_cell(est[0], est[1])
            avoid = {c for c, n in self.avoid_cells.items() if n >= 3}
            result = frontier.select_frontier_goal(
                self.grid, start_cell, self.robot_radius_cells, avoid=avoid
            )
            if result is None:
                self.current_path_world = []
                self.exploration_done = True
                return
            self.current_goal_cell, path = result

        self.current_path_cells = path
        self.current_path_world = [self.grid.cell_to_world(c, r) for c, r in path]
        self.path_index = 0

    def _path_blocked(self) -> bool:
        """Has the map, updated since this path was planned, revealed that
        an upcoming cell on it is actually occupied?"""
        for c, r in self.current_path_cells[self.path_index : self.path_index + 3]:
            if self.grid.is_occupied(c, r):
                return True
        return False

    # -- main loop --------------------------------------------------------------
    def step(self) -> bool:
        """Advance the simulation by one control cycle. Returns True while
        the run should keep going, False once exploration/waypoints are
        exhausted and the robot has nothing left to do."""
        cfg = self.cfg
        t = len(self.frames)

        if not self.current_path_world or self._path_blocked():
            self._replan()

        if not self.current_path_world:
            # Nothing to head toward yet. On the very first step this is
            # expected -- the map is entirely unknown, so frontier search
            # (which needs at least one *known-free* cell to expand from)
            # can't find anything until an initial in-place scan clears
            # some free space around the start pose. Only treat "no path"
            # as real completion once at least one scan has landed.
            if self.exploration_done and t > 0:
                return False
            v, w = 0.0, 0.0
            finished = True
        else:
            v, w, self.path_index, finished = follow_path(
                self.robot.pose, self.current_path_world, self.path_index,
                cfg.goal_tolerance, cfg.max_v, cfg.max_w,
            )
            if finished:
                self.goals_reached += 1
                self.current_path_world = []
                self.current_path_cells = []

        self.robot.drive(v, w, cfg.dt)
        beams = lidar_scan(self.world, self.robot.pose, cfg.lidar, self.rng)

        if self.robot.collided_last_step:
            self.consecutive_collisions += 1
            if self.current_goal_cell is not None:
                self.avoid_cells[self.current_goal_cell] = (
                    self.avoid_cells.get(self.current_goal_cell, 0) + 1
                )
            if self.consecutive_collisions >= 1:
                # This route looked clear on the (coarse, still-partial)
                # grid but the real robot keeps bumping into something --
                # abandon it now rather than grinding against a wall.
                self.current_path_world = []
                self.current_path_cells = []
        else:
            self.consecutive_collisions = 0

        # A real differential-drive base has a bump/stall signal available
        # onboard (motor current spike, contact switch, wheel-slip from an
        # IMU) -- using it here is not ground truth leaking in, it's a
        # legitimate sensor the estimator is allowed to read. Without it,
        # every particle would be advanced by the full commanded velocity
        # even though the robot demonstrably went nowhere, injecting a
        # systematic bias no amount of lidar correction can distinguish
        # from an actual, coherent world (all particles are "wrong" the
        # same way, so nothing in the weight spread flags it).
        v_for_pf = 0.0 if self.robot.collided_last_step else v
        self.pf.predict(v_for_pf, w, cfg.dt)

        if not cfg.disable_pf_update:
            if self.dfield is None or t % cfg.df_every == 0:
                self.dfield = DistanceField(self.grid)
            self.pf.update(beams, self.dfield, cfg.lidar.max_range)

        est_pose = self.pf.estimate()
        self.grid.integrate_scan(est_pose, beams, cfg.lidar.max_range)

        endpoints = []
        ex, ey, eth = self.robot.pose  # true pose, for the visualizer only
        for off, r in beams:
            if r is None:
                continue
            a = eth + off
            endpoints.append((ex + r * math.cos(a), ey + r * math.sin(a)))

        self.true_poses.append(self.robot.pose)
        self.est_poses.append(est_pose)
        self.frames.append(
            Frame(
                t=t,
                true_pose=self.robot.pose,
                est_pose=est_pose,
                neff=self.pf.last_neff,
                beam_endpoints=endpoints,
                path_world=list(self.current_path_world[self.path_index :]),
                goal_reached_count=self.goals_reached,
                collided=self.robot.collided_last_step,
            )
        )
        return True

    def run(self, max_steps: int = 500) -> "SlamRun":
        for _ in range(max_steps):
            if not self.step():
                break
        return self
