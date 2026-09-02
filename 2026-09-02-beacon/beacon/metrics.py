"""Ground-truth-vs-estimate scoring. Every function here is an oracle used
only by tests, the CLI report, and the visualizer -- nothing in slam.py,
pf_localizer.py, or occupancy_grid.py ever calls into this module, which is
exactly the point: the estimation algorithms must never see what this
module is allowed to see.
"""

from __future__ import annotations

import math
from typing import List, Sequence, Tuple

from .occupancy_grid import OccupancyGrid
from .robot import Pose
from .world import World, point_segment_distance


def pose_rmse(true_poses: Sequence[Pose], est_poses: Sequence[Pose]) -> float:
    assert len(true_poses) == len(est_poses) and true_poses, "need matching, non-empty pose logs"
    sq = 0.0
    for (tx, ty, _), (ex, ey, _) in zip(true_poses, est_poses):
        sq += (tx - ex) ** 2 + (ty - ey) ** 2
    return math.sqrt(sq / len(true_poses))


def final_pose_error(true_pose: Pose, est_pose: Pose) -> float:
    return math.hypot(true_pose[0] - est_pose[0], true_pose[1] - est_pose[1])


def ground_truth_grid(world: World, resolution: float, wall_thickness: float = 0.15) -> OccupancyGrid:
    """Rasterize the true World into an occupancy grid at the same
    resolution as the SLAM map, purely so map quality can be scored
    cell-for-cell. A cell counts as truly occupied if its center falls
    within `wall_thickness` of some wall segment."""
    grid = OccupancyGrid(world.width, world.height, resolution)
    for r in range(grid.rows):
        for c in range(grid.cols):
            wx, wy = grid.cell_to_world(c, r)
            occupied = any(
                point_segment_distance((wx, wy), a, b) <= wall_thickness for a, b in world.walls
            )
            grid.set_log_odds(c, r, 6.0 if occupied else -6.0)
    return grid


def map_quality(
    est_grid: OccupancyGrid, truth_grid: OccupancyGrid
) -> Tuple[float, float]:
    """Returns (occupied_iou, explored_accuracy):
      - occupied_iou: IoU between cells the estimate believes are occupied
        and cells that truly are, restricted to cells the robot actually
        explored (unknown cells can't be credited or blamed).
      - explored_accuracy: fraction of explored cells whose free/occupied
        classification matches ground truth.
    """
    assert est_grid.cols == truth_grid.cols and est_grid.rows == truth_grid.rows

    inter = union = 0
    correct = total = 0
    for r in range(est_grid.rows):
        for c in range(est_grid.cols):
            if est_grid.is_unknown(c, r):
                continue
            total += 1
            est_occ = est_grid.is_occupied(c, r)
            true_occ = truth_grid.is_occupied(c, r)
            if est_occ == true_occ:
                correct += 1
            if est_occ or true_occ:
                union += 1
                if est_occ and true_occ:
                    inter += 1

    iou = (inter / union) if union else 1.0
    acc = (correct / total) if total else 0.0
    return iou, acc


def explored_fraction(est_grid: OccupancyGrid) -> float:
    known = sum(
        1
        for r in range(est_grid.rows)
        for c in range(est_grid.cols)
        if not est_grid.is_unknown(c, r)
    )
    return known / (est_grid.cols * est_grid.rows)
