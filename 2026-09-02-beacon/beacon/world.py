"""Ground-truth 2D environments the robot never sees directly.

A World is a rectangular arena bounded by walls plus some interior wall
segments (rooms, a maze, scattered obstacles). It exposes raycast() as the
only way anything queries it "physically" -- the lidar module is the sole
caller, standing in for a real range sensor hitting real geometry.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from .geometry import Point, Segment, raycast


class World:
    def __init__(self, width: float, height: float, walls: List[Segment], name: str = "world"):
        self.width = width
        self.height = height
        self.name = name
        self.walls: List[Segment] = list(walls)

    def raycast(self, origin: Point, angle: float, max_range: float) -> Optional[float]:
        return raycast(origin, angle, self.walls, max_range)

    def point_in_bounds(self, p: Point) -> bool:
        return 0.0 <= p[0] <= self.width and 0.0 <= p[1] <= self.height

    def collides(self, p: Point, radius: float) -> bool:
        """True if a disc of `radius` centered at p overlaps any wall or the
        outer boundary. Used to keep the simulated robot from driving
        through walls, and by the planner's inflation."""
        if p[0] - radius < 0 or p[0] + radius > self.width:
            return True
        if p[1] - radius < 0 or p[1] + radius > self.height:
            return True
        for (x1, y1), (x2, y2) in self.walls:
            if point_segment_distance(p, (x1, y1), (x2, y2)) < radius:
                return True
        return False


def point_segment_distance(p: Point, a: Point, b: Point) -> float:
    px, py = p
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-12:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    cx, cy = ax + t * dx, ay + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def _border(width: float, height: float) -> List[Segment]:
    return [
        ((0, 0), (width, 0)),
        ((width, 0), (width, height)),
        ((width, height), (0, height)),
        ((0, height), (0, 0)),
    ]


def make_open_world(width: float = 20.0, height: float = 20.0) -> World:
    """A bounded arena with a handful of scattered box obstacles -- the
    easiest map, mostly open space."""
    walls = _border(width, height)
    boxes = [
        (5, 5, 2, 2),
        (13, 4, 1.5, 3),
        (8, 12, 3, 1.5),
        (15, 14, 2, 2),
    ]
    for x, y, w, h in boxes:
        walls += _box(x, y, w, h)
    return World(width, height, walls, name="open")


def make_office_world(width: float = 20.0, height: float = 20.0) -> World:
    """A few interior rooms with doorway gaps -- forces the robot through
    corridors, a harder localization case than open space."""
    walls = _border(width, height)
    # Vertical corridor wall with a doorway gap.
    walls.append(((10, 0), (10, 8)))
    walls.append(((10, 11), (10, 20)))
    # Horizontal wall with a doorway gap.
    walls.append(((0, 10), (4, 10)))
    walls.append(((7, 10), (20, 10)))
    # A couple of room-corner obstacles.
    walls += _box(3, 3, 2, 2)
    walls += _box(15, 3, 2, 3)
    walls += _box(14, 15, 2, 2)
    return World(width, height, walls, name="office")


def make_maze_world(width: float = 20.0, height: float = 20.0) -> World:
    """A tight-corridor maze -- the hardest map: narrow passages punish a
    poorly-converged particle filter and a sloppy planner alike."""
    walls = _border(width, height)
    segs = [
        ((4, 0), (4, 14)),
        ((4, 14), (16, 14)),
        ((16, 14), (16, 4)),
        ((16, 4), (8, 4)),
        ((8, 4), (8, 10)),
        ((8, 10), (12, 10)),
        ((0, 16), (12, 16)),
        ((12, 16), (12, 20)),
    ]
    walls += segs
    return World(width, height, walls, name="maze")


def _box(x: float, y: float, w: float, h: float) -> List[Segment]:
    return [
        ((x, y), (x + w, y)),
        ((x + w, y), (x + w, y + h)),
        ((x + w, y + h), (x, y + h)),
        ((x, y + h), (x, y)),
    ]


BUILTIN_WORLDS = {
    "open": make_open_world,
    "office": make_office_world,
    "maze": make_maze_world,
}


def make_world(name: str) -> World:
    if name not in BUILTIN_WORLDS:
        raise ValueError(f"unknown world '{name}', choices: {sorted(BUILTIN_WORLDS)}")
    return BUILTIN_WORLDS[name]()
