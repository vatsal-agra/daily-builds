"""Barnes-Hut octree: approximate O(N log N) gravity.

Two passes over the bodies:
  1. `insert` builds the tree's *structure* only (which octant each body
     falls into, subdividing leaves that already hold a body).
  2. `finalize` walks the finished tree bottom-up, computing each node's
     total mass and center of mass from its children.

Then for any target body, `compute_force_on` walks the tree top-down: if a
node is "far enough away" relative to its size (the opening-angle test,
governed by theta), the whole subtree is treated as one point mass at its
center of mass. Otherwise we recurse into its children. Leaves are always
resolved exactly (direct summation over the handful of bodies at that
leaf), never approximated — the theta test only ever applies to internal
(multi-body) nodes.
"""

import math

from .vector import Vec3
from .body import DEFAULT_G

# Depth at which we give up subdividing and just lump any further bodies
# that land in the same tiny cube together as one leaf. Only reachable if
# bodies are at (or extremely near) the exact same position -- each level
# halves the cube, so 48 levels shrinks even an astronomically large
# bounding box down to below double-precision distinguishability.
MAX_DEPTH = 48


class OctreeNode:
    __slots__ = (
        "center", "half_size", "children", "body", "bodies_here",
        "mass", "com",
    )

    def __init__(self, center, half_size):
        self.center = center
        self.half_size = half_size
        self.children = None      # None, or a list of 8 (slot may be None)
        self.body = None          # single Body, if this is a plain leaf
        self.bodies_here = None   # >1 Body, if max depth was hit
        self.mass = 0.0
        self.com = center

    def octant_index(self, pos):
        idx = 0
        if pos.x >= self.center.x:
            idx |= 1
        if pos.y >= self.center.y:
            idx |= 2
        if pos.z >= self.center.z:
            idx |= 4
        return idx

    def make_child(self, idx):
        h = self.half_size / 2.0
        dx = h if (idx & 1) else -h
        dy = h if (idx & 2) else -h
        dz = h if (idx & 4) else -h
        return OctreeNode(Vec3(self.center.x + dx, self.center.y + dy, self.center.z + dz), h)


def _insert(node, body, depth):
    if node.children is not None:
        idx = node.octant_index(body.position)
        if node.children[idx] is None:
            node.children[idx] = node.make_child(idx)
        _insert(node.children[idx], body, depth + 1)
        return

    if node.body is None and node.bodies_here is None:
        node.body = body
        return

    if depth >= MAX_DEPTH:
        if node.bodies_here is None:
            node.bodies_here = [node.body] if node.body is not None else []
            node.body = None
        node.bodies_here.append(body)
        return

    existing = node.body
    node.body = None
    node.children = [None] * 8
    _insert(node, existing, depth)
    _insert(node, body, depth)


def _finalize(node):
    if node.children is not None:
        total_mass = 0.0
        com_sum = Vec3(0.0, 0.0, 0.0)
        for c in node.children:
            if c is not None:
                _finalize(c)
                total_mass += c.mass
                com_sum += c.com * c.mass
        node.mass = total_mass
        node.com = (com_sum / total_mass) if total_mass > 0.0 else node.center
        return

    leaf_bodies = node.bodies_here if node.bodies_here is not None else (
        [node.body] if node.body is not None else []
    )
    total_mass = 0.0
    com_sum = Vec3(0.0, 0.0, 0.0)
    for b in leaf_bodies:
        total_mass += b.mass
        com_sum += b.position * b.mass
    node.mass = total_mass
    node.com = (com_sum / total_mass) if total_mass > 0.0 else node.center


def build_tree(bodies, padding=1e-3):
    """Build a Barnes-Hut octree over the alive bodies. Returns None if
    there are no alive bodies (an all-dead / empty simulation)."""
    alive = [b for b in bodies if b.alive]
    if not alive:
        return None

    xs = [b.position.x for b in alive]
    ys = [b.position.y for b in alive]
    zs = [b.position.z for b in alive]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    minz, maxz = min(zs), max(zs)

    center = Vec3((minx + maxx) / 2.0, (miny + maxy) / 2.0, (minz + maxz) / 2.0)
    half = max(maxx - minx, maxy - miny, maxz - minz) / 2.0
    # Floor + pad: a single body (or a perfectly symmetric cloud) gives
    # half == 0, and points sitting exactly on a boundary plane need a
    # margin so octant_index() doesn't misroute them.
    half = max(half, 1e-9) * (1.0 + padding)

    root = OctreeNode(center, half)
    for b in alive:
        _insert(root, b, 0)
    _finalize(root)
    return root


def _leaf_bodies(node):
    if node.bodies_here is not None:
        return node.bodies_here
    if node.body is not None:
        return [node.body]
    return []


def _accel_from_node(node, target, G, theta, eps_sq):
    if node is None or node.mass == 0.0:
        return Vec3(0.0, 0.0, 0.0)

    if node.children is None:
        acc = Vec3(0.0, 0.0, 0.0)
        for b in _leaf_bodies(node):
            if b is target:
                continue
            d = b.position - target.position
            dist_sq = d.norm_sq() + eps_sq
            if dist_sq == 0.0:
                continue
            acc += d * (G * b.mass * (dist_sq ** -1.5))
        return acc

    d = node.com - target.position
    dist_sq = d.norm_sq()
    dist = math.sqrt(dist_sq)
    s = node.half_size * 2.0  # full width of this node's cube
    if dist > 0.0 and (s / dist) < theta:
        eff_dist_sq = dist_sq + eps_sq
        return d * (G * node.mass * (eff_dist_sq ** -1.5))

    acc = Vec3(0.0, 0.0, 0.0)
    for c in node.children:
        if c is not None:
            acc += _accel_from_node(c, target, G, theta, eps_sq)
    return acc


def compute_accelerations(bodies, G=DEFAULT_G, theta=0.5, softening=0.0):
    """Return a list of Vec3 accelerations, one per body (dead bodies get
    zero), via Barnes-Hut. theta=0 forces exhaustive recursion into every
    leaf, which makes this mathematically equivalent to brute force
    (module floating-point summation order)."""
    if theta < 0.0:
        raise ValueError(f"theta must be >= 0, got {theta}")

    root = build_tree(bodies)
    eps_sq = softening * softening
    accel = []
    for b in bodies:
        if not b.alive or root is None:
            accel.append(Vec3(0.0, 0.0, 0.0))
            continue
        accel.append(_accel_from_node(root, b, G, theta, eps_sq))
    return accel


def node_count(root):
    """Count nodes in the tree (used for benchmarking/reporting)."""
    if root is None:
        return 0
    n = 1
    if root.children is not None:
        for c in root.children:
            if c is not None:
                n += node_count(c)
    return n
