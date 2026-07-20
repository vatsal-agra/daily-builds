"""
Impulse — a from-scratch 2D rigid-body physics engine.

Pure Python, zero dependencies. Implements:
  - Vec2 math
  - Circle / Polygon shapes with correct mass & moment-of-inertia
  - Semi-implicit Euler integration
  - Broad-phase uniform spatial hash grid
  - Narrow-phase SAT collision detection with clipped contact manifolds
    (circle-circle, circle-polygon, polygon-polygon)
  - Sequential-impulse solver: restitution, Coulomb friction, Baumgarte
    positional correction
  - Joints: DistanceJoint (rigid rod), SpringJoint (damped elastic),
    PinJoint (revolute / point-to-point constraint)

Every quantity is a plain float; no numpy. This file has no I/O — it is
imported both by the test suite and by server.py.
"""

import math

GRAVITY = (0.0, 500.0)          # px/s^2, +y is down (screen coordinates)
SLOP = 0.01                     # allowed penetration before correction kicks in
BAUMGARTE = 0.2                 # positional correction factor
VELOCITY_ITERATIONS = 10
MAX_LINEAR_CORRECTION = 4.0     # px per step, avoids explosive pop-out


# --------------------------------------------------------------------------
# Vector math
# --------------------------------------------------------------------------

class Vec2:
    __slots__ = ("x", "y")

    def __init__(self, x=0.0, y=0.0):
        self.x = float(x)
        self.y = float(y)

    def __add__(self, o):
        return Vec2(self.x + o.x, self.y + o.y)

    def __sub__(self, o):
        return Vec2(self.x - o.x, self.y - o.y)

    def __neg__(self):
        return Vec2(-self.x, -self.y)

    def __mul__(self, s):
        return Vec2(self.x * s, self.y * s)

    __rmul__ = __mul__

    def __repr__(self):
        return f"Vec2({self.x:.4f}, {self.y:.4f})"

    def dot(self, o):
        return self.x * o.x + self.y * o.y

    def length(self):
        return math.sqrt(self.x * self.x + self.y * self.y)

    def length_sq(self):
        return self.x * self.x + self.y * self.y

    def normalized(self):
        l = self.length()
        if l < 1e-12:
            return Vec2(0.0, 0.0)
        return Vec2(self.x / l, self.y / l)

    def perp(self):
        """90 degree CCW perpendicular."""
        return Vec2(-self.y, self.x)

    def rotated(self, angle):
        c, s = math.cos(angle), math.sin(angle)
        return Vec2(self.x * c - self.y * s, self.x * s + self.y * c)

    def to_tuple(self):
        return (self.x, self.y)


def cross_vv(a, b):
    """2D cross product of two vectors -> scalar (z component)."""
    return a.x * b.y - a.y * b.x


def cross_sv(s, v):
    """Cross product of scalar and vector -> vector."""
    return Vec2(-s * v.y, s * v.x)


def cross_vs(v, s):
    return Vec2(s * v.y, -s * v.x)


class Mat22:
    """2x2 matrix, used for the point-to-point (pin) joint effective mass."""

    def __init__(self, a11, a12, a21, a22):
        self.a11, self.a12, self.a21, self.a22 = a11, a12, a21, a22

    def inverse(self):
        det = self.a11 * self.a22 - self.a12 * self.a21
        if abs(det) < 1e-12:
            return Mat22(0, 0, 0, 0)
        inv_det = 1.0 / det
        return Mat22(inv_det * self.a22, -inv_det * self.a12,
                     -inv_det * self.a21, inv_det * self.a11)

    def mul_vec(self, v):
        return Vec2(self.a11 * v.x + self.a12 * v.y,
                    self.a21 * v.x + self.a22 * v.y)


# --------------------------------------------------------------------------
# Shapes
# --------------------------------------------------------------------------

class Circle:
    kind = "circle"

    def __init__(self, radius):
        if radius <= 0:
            raise ValueError("circle radius must be positive")
        self.radius = radius

    def mass_data(self, density):
        mass = density * math.pi * self.radius ** 2
        inertia = mass * self.radius ** 2 / 2.0
        return mass, inertia

    def aabb_radius(self):
        return self.radius


class Polygon:
    kind = "polygon"

    def __init__(self, vertices):
        """vertices: list of Vec2 in CCW order, positions relative to the
        body's local origin. The constructor re-centers them on the
        centroid so body.position always equals the true center of mass."""
        if len(vertices) < 3:
            raise ValueError("polygon needs at least 3 vertices")
        centroid = _polygon_centroid(vertices)
        self.vertices = [v - centroid for v in vertices]
        self.normals = self._compute_normals(self.vertices)

    @staticmethod
    def _compute_normals(verts):
        n = len(verts)
        normals = []
        for i in range(n):
            edge = verts[(i + 1) % n] - verts[i]
            # CCW winding -> outward normal is the clockwise perpendicular
            normals.append(Vec2(edge.y, -edge.x).normalized())
        return normals

    def mass_data(self, density):
        # Polygon mass/inertia via triangle decomposition about the origin
        # (vertices are already centroid-relative, so origin == centroid).
        area = 0.0
        inertia = 0.0
        origin = Vec2(0.0, 0.0)
        verts = self.vertices
        n = len(verts)
        k_inv3 = 1.0 / 3.0
        for i in range(n):
            p1 = verts[i]
            p2 = verts[(i + 1) % n]
            d = cross_vv(p1, p2)
            tri_area = 0.5 * d
            area += tri_area
            intx2 = p1.x * p1.x + p2.x * p1.x + p2.x * p2.x
            inty2 = p1.y * p1.y + p2.y * p1.y + p2.y * p2.y
            inertia += (0.25 * k_inv3 * d) * (intx2 + inty2)
        mass = density * area
        # inertia computed above is about the origin already (centroid)
        moment = density * inertia
        return mass, abs(moment)

    def aabb_radius(self):
        return max(v.length() for v in self.vertices)


def box_vertices(width, height):
    hw, hh = width / 2.0, height / 2.0
    return [Vec2(-hw, -hh), Vec2(hw, -hh), Vec2(hw, hh), Vec2(-hw, hh)]


def Box(width, height):
    return Polygon(box_vertices(width, height))


def _polygon_centroid(verts):
    n = len(verts)
    cx = cy = area = 0.0
    for i in range(n):
        p1 = verts[i]
        p2 = verts[(i + 1) % n]
        cr = cross_vv(p1, p2)
        area += cr
        cx += (p1.x + p2.x) * cr
        cy += (p1.y + p2.y) * cr
    area *= 0.5
    if abs(area) < 1e-9:
        # degenerate; fall back to vertex average
        return Vec2(sum(v.x for v in verts) / n, sum(v.y for v in verts) / n)
    cx /= (6.0 * area)
    cy /= (6.0 * area)
    return Vec2(cx, cy)


# --------------------------------------------------------------------------
# Body
# --------------------------------------------------------------------------

class Body:
    def __init__(self, shape, position, angle=0.0, density=1.0,
                 restitution=0.3, friction=0.3, static=False,
                 linear_damping=0.01, angular_damping=0.01, name=None):
        self.shape = shape
        self.position = Vec2(*position) if not isinstance(position, Vec2) else position
        self.angle = angle
        self.velocity = Vec2(0.0, 0.0)
        self.angular_velocity = 0.0
        self.restitution = max(0.0, min(1.0, restitution))
        self.friction = max(0.0, friction)
        self.static = static
        self.linear_damping = linear_damping
        self.angular_damping = angular_damping
        self.name = name
        self.force = Vec2(0.0, 0.0)
        self.torque = 0.0

        if static:
            self.mass = 0.0
            self.inv_mass = 0.0
            self.inertia = 0.0
            self.inv_inertia = 0.0
        else:
            mass, inertia = shape.mass_data(density)
            if mass <= 0:
                raise ValueError("body has non-positive mass")
            self.mass = mass
            self.inv_mass = 1.0 / mass
            self.inertia = inertia
            self.inv_inertia = 1.0 / inertia if inertia > 0 else 0.0

    def world_vertices(self):
        return [self.position + v.rotated(self.angle) for v in self.shape.vertices]

    def world_normals(self):
        return [n.rotated(self.angle) for n in self.shape.normals]

    def apply_impulse(self, impulse, contact_point):
        if self.static:
            return
        r = contact_point - self.position
        self.velocity = self.velocity + impulse * self.inv_mass
        self.angular_velocity += self.inv_inertia * cross_vv(r, impulse)

    def apply_force(self, f):
        self.force = self.force + f

    def aabb(self):
        r = self.shape.aabb_radius()
        return (self.position.x - r, self.position.y - r,
                self.position.x + r, self.position.y + r)

    def point_velocity(self, world_point):
        r = world_point - self.position
        return self.velocity + cross_sv(self.angular_velocity, r)

    def to_dict(self):
        d = {
            "name": self.name,
            "shape": self.shape.kind,
            "x": self.position.x, "y": self.position.y,
            "angle": self.angle,
            "static": self.static,
            "restitution": self.restitution,
            "friction": self.friction,
        }
        if self.shape.kind == "circle":
            d["radius"] = self.shape.radius
        else:
            d["vertices"] = [[v.x, v.y] for v in self.shape.vertices]
        return d


# --------------------------------------------------------------------------
# Narrow-phase collision detection
# --------------------------------------------------------------------------

class Manifold:
    __slots__ = ("body_a", "body_b", "normal", "points", "penetrations", "restitution", "friction")

    def __init__(self, body_a, body_b, normal, points, penetrations):
        self.body_a = body_a
        self.body_b = body_b
        self.normal = normal          # points from A to B
        self.points = points          # list of Vec2 world contact points
        self.penetrations = penetrations
        self.restitution = max(body_a.restitution, body_b.restitution)
        self.friction = math.sqrt(body_a.friction * body_b.friction)


def _clip_segment(v_in, n, offset):
    """Clip a 2-point segment to the half-plane dot(n, p) <= offset."""
    out = []
    d0 = n.dot(v_in[0]) - offset
    d1 = n.dot(v_in[1]) - offset
    if d0 <= 0:
        out.append(v_in[0])
    if d1 <= 0:
        out.append(v_in[1])
    if d0 * d1 < 0:
        t = d0 / (d0 - d1)
        out.append(v_in[0] + (v_in[1] - v_in[0]) * t)
    return out


def collide_circle_circle(a, b):
    normal = b.position - a.position
    dist = normal.length()
    radius_sum = a.shape.radius + b.shape.radius
    if dist >= radius_sum or dist < 1e-9:
        if dist < 1e-9 and radius_sum > 0:
            # exactly coincident centers: pick an arbitrary axis
            n = Vec2(1.0, 0.0)
            point = a.position
            return Manifold(a, b, n, [point], [radius_sum])
        return None
    n = normal * (1.0 / dist)
    penetration = radius_sum - dist
    point = a.position + n * a.shape.radius
    return Manifold(a, b, n, [point], [penetration])


def _polygon_support(verts, direction):
    best = verts[0]
    best_d = best.dot(direction)
    for v in verts[1:]:
        d = v.dot(direction)
        if d > best_d:
            best_d = d
            best = v
    return best


def collide_circle_polygon(circle_body, poly_body):
    """Returns a manifold with normal pointing from circle_body to poly_body,
    matching the (A=circle, B=polygon) convention used by the caller."""
    center_world = circle_body.position
    verts = poly_body.world_vertices()
    normals = poly_body.world_normals()
    n = len(verts)

    # find edge with max separation of the circle center
    max_sep = -math.inf
    face_index = 0
    for i in range(n):
        s = normals[i].dot(center_world - verts[i])
        if s > circle_body.shape.radius:
            return None  # definitely separated
        if s > max_sep:
            max_sep = s
            face_index = i

    v1 = verts[face_index]
    v2 = verts[(face_index + 1) % n]
    face_normal = normals[face_index]

    if max_sep < 1e-9:
        # center is inside the polygon
        normal = -face_normal
        penetration = circle_body.shape.radius - max_sep
        point = center_world + normal * circle_body.shape.radius
        return Manifold(circle_body, poly_body, normal, [point], [penetration])

    edge = v2 - v1
    u1 = (center_world - v1).dot(edge)
    u2 = (center_world - v2).dot(-edge)

    if u1 <= 0:
        # closest to v1
        d = (center_world - v1).length()
        if d > circle_body.shape.radius:
            return None
        normal = -(center_world - v1).normalized() if d > 1e-9 else -face_normal
        penetration = circle_body.shape.radius - d
        point = v1
        return Manifold(circle_body, poly_body, normal, [point], [penetration])
    elif u2 <= 0:
        d = (center_world - v2).length()
        if d > circle_body.shape.radius:
            return None
        normal = -(center_world - v2).normalized() if d > 1e-9 else -face_normal
        penetration = circle_body.shape.radius - d
        point = v2
        return Manifold(circle_body, poly_body, normal, [point], [penetration])
    else:
        # face region
        if max_sep > circle_body.shape.radius:
            return None
        normal = -face_normal
        penetration = circle_body.shape.radius - max_sep
        point = center_world + normal * circle_body.shape.radius
        return Manifold(circle_body, poly_body, normal, [point], [penetration])


def _find_axis_of_least_penetration(verts_a, normals_a, verts_b):
    best_dist = -math.inf
    best_index = 0
    for i, n in enumerate(normals_a):
        v = verts_a[i]
        support = _polygon_support(verts_b, -n)
        d = n.dot(support - v)
        if d > best_dist:
            best_dist = d
            best_index = i
    return best_index, best_dist


def collide_polygon_polygon(a, b):
    verts_a, normals_a = a.world_vertices(), a.world_normals()
    verts_b, normals_b = b.world_vertices(), b.world_normals()

    edge_a, sep_a = _find_axis_of_least_penetration(verts_a, normals_a, verts_b)
    if sep_a > 0:
        return None
    edge_b, sep_b = _find_axis_of_least_penetration(verts_b, normals_b, verts_a)
    if sep_b > 0:
        return None

    # reference = shallower penetration axis (SAT: true separating axis)
    if sep_b > sep_a + 1e-6:
        ref_body, inc_body = b, a
        ref_verts, ref_normals = verts_b, normals_b
        ref_edge = edge_b
        flip = True
    else:
        ref_body, inc_body = a, b
        ref_verts, ref_normals = verts_a, normals_a
        ref_edge = edge_a
        flip = False

    ref_normal = ref_normals[ref_edge]

    # incident edge on the other polygon: most anti-parallel normal
    inc_normals = normals_a if flip else normals_b
    inc_verts = verts_a if flip else verts_b
    best_dot = math.inf
    inc_index = 0
    for i, n in enumerate(inc_normals):
        d = ref_normal.dot(n)
        if d < best_dot:
            best_dot = d
            inc_index = i
    inc_edge = [inc_verts[inc_index], inc_verts[(inc_index + 1) % len(inc_verts)]]

    v1 = ref_verts[ref_edge]
    v2 = ref_verts[(ref_edge + 1) % len(ref_verts)]
    tangent = (v2 - v1).normalized()

    neg_side = -tangent.dot(v1)
    pos_side = tangent.dot(v2)

    clipped = _clip_segment(inc_edge, -tangent, neg_side)
    if len(clipped) < 2:
        return None
    clipped = _clip_segment(clipped, tangent, pos_side)
    if len(clipped) < 2:
        return None

    points = []
    penetrations = []
    for p in clipped:
        separation = ref_normal.dot(p - v1)
        if separation <= 0:
            points.append(p)
            penetrations.append(-separation)

    if not points:
        return None

    normal = ref_normal if not flip else -ref_normal
    # Manifold convention: normal points from body_a to body_b (a, b as passed in)
    if flip:
        return Manifold(a, b, -ref_normal, points, penetrations)
    else:
        return Manifold(a, b, ref_normal, points, penetrations)


def collide(body_a, body_b):
    ka, kb = body_a.shape.kind, body_b.shape.kind
    if ka == "circle" and kb == "circle":
        return collide_circle_circle(body_a, body_b)
    if ka == "circle" and kb == "polygon":
        return collide_circle_polygon(body_a, body_b)
    if ka == "polygon" and kb == "circle":
        m = collide_circle_polygon(body_b, body_a)
        if m is None:
            return None
        # swap to keep (a, b) = (body_a, body_b), flip normal direction
        return Manifold(body_a, body_b, -m.normal, m.points, m.penetrations)
    if ka == "polygon" and kb == "polygon":
        return collide_polygon_polygon(body_a, body_b)
    raise ValueError(f"unhandled shape pair {ka}, {kb}")


# --------------------------------------------------------------------------
# Broad phase: uniform spatial hash grid
# --------------------------------------------------------------------------

class SpatialHash:
    def __init__(self, cell_size=64.0):
        self.cell_size = cell_size

    def candidate_pairs(self, bodies):
        cells = {}
        for idx, body in enumerate(bodies):
            x0, y0, x1, y1 = body.aabb()
            cs = self.cell_size
            gx0, gy0 = int(math.floor(x0 / cs)), int(math.floor(y0 / cs))
            gx1, gy1 = int(math.floor(x1 / cs)), int(math.floor(y1 / cs))
            for gx in range(gx0, gx1 + 1):
                for gy in range(gy0, gy1 + 1):
                    cells.setdefault((gx, gy), []).append(idx)

        seen = set()
        pairs = []
        for bucket in cells.values():
            n = len(bucket)
            if n < 2:
                continue
            for i in range(n):
                for j in range(i + 1, n):
                    ia, ib = bucket[i], bucket[j]
                    key = (ia, ib) if ia < ib else (ib, ia)
                    if key in seen:
                        continue
                    seen.add(key)
                    pairs.append(key)
        return pairs


# --------------------------------------------------------------------------
# Joints
# --------------------------------------------------------------------------

class DistanceJoint:
    """Rigid rod holding two anchor points at a fixed distance apart.

    body_b may be None, in which case anchor_b is a fixed world-space point.
    """

    def __init__(self, body_a, anchor_a_local, body_b, anchor_b_local, length=None):
        self.body_a = body_a
        self.body_b = body_b
        self.anchor_a_local = Vec2(*anchor_a_local)
        self.anchor_b_local = Vec2(*anchor_b_local)
        if length is None:
            wa = body_a.position + self.anchor_a_local.rotated(body_a.angle)
            wb = (body_b.position + self.anchor_b_local.rotated(body_b.angle)
                  if body_b is not None else self.anchor_b_local)
            length = (wb - wa).length()
        self.length = length

    def _world_anchors(self):
        wa = self.body_a.position + self.anchor_a_local.rotated(self.body_a.angle)
        if self.body_b is not None:
            wb = self.body_b.position + self.anchor_b_local.rotated(self.body_b.angle)
        else:
            wb = self.anchor_b_local
        return wa, wb

    def solve(self, dt):
        a = self.body_a
        b = self.body_b
        wa, wb = self._world_anchors()
        d = wb - wa
        dist = d.length()
        if dist < 1e-9:
            return
        n = d * (1.0 / dist)

        ra = wa - a.position
        rb = (wb - b.position) if b is not None else Vec2(0.0, 0.0)

        inv_mass_sum = a.inv_mass + (b.inv_mass if b else 0.0)
        ra_cross_n = cross_vv(ra, n)
        rb_cross_n = cross_vv(rb, n) if b else 0.0
        k = (inv_mass_sum + a.inv_inertia * ra_cross_n ** 2 +
             (b.inv_inertia * rb_cross_n ** 2 if b else 0.0))
        if k < 1e-12:
            return

        va = a.velocity + cross_sv(a.angular_velocity, ra)
        vb = (b.velocity + cross_sv(b.angular_velocity, rb)) if b else Vec2(0.0, 0.0)
        rel_vel = (vb - va).dot(n)

        c = dist - self.length
        bias = (BAUMGARTE / dt) * c

        lam = -(rel_vel + bias) / k
        impulse = n * lam

        a.velocity = a.velocity - impulse * a.inv_mass
        a.angular_velocity -= a.inv_inertia * cross_vv(ra, impulse)
        if b is not None:
            b.velocity = b.velocity + impulse * b.inv_mass
            b.angular_velocity += b.inv_inertia * cross_vv(rb, impulse)


class SpringJoint:
    """Damped elastic connection between two anchor points. Applied as a
    force each step (not a hard velocity constraint), so it visibly
    stretches under load like a real spring."""

    def __init__(self, body_a, anchor_a_local, body_b, anchor_b_local,
                 rest_length=None, stiffness=40.0, damping=2.0):
        self.body_a = body_a
        self.body_b = body_b
        self.anchor_a_local = Vec2(*anchor_a_local)
        self.anchor_b_local = Vec2(*anchor_b_local)
        self.stiffness = stiffness
        self.damping = damping
        if rest_length is None:
            wa = body_a.position + self.anchor_a_local.rotated(body_a.angle)
            wb = (body_b.position + self.anchor_b_local.rotated(body_b.angle)
                  if body_b is not None else self.anchor_b_local)
            rest_length = (wb - wa).length()
        self.rest_length = rest_length

    def _world_anchors(self):
        a, b = self.body_a, self.body_b
        wa = a.position + self.anchor_a_local.rotated(a.angle)
        wb = (b.position + self.anchor_b_local.rotated(b.angle)
              if b is not None else self.anchor_b_local)
        return wa, wb

    def apply(self):
        wa, wb = self._world_anchors()
        a, b = self.body_a, self.body_b
        d = wb - wa
        dist = d.length()
        if dist < 1e-9:
            return
        n = d * (1.0 / dist)
        stretch = dist - self.rest_length

        va = a.point_velocity(wa)
        vb = b.point_velocity(wb) if b is not None else Vec2(0.0, 0.0)
        rel_vel = (vb - va).dot(n)

        force_mag = self.stiffness * stretch + self.damping * rel_vel
        force = n * force_mag

        if not a.static:
            a.force = a.force + force
            ra = wa - a.position
            a.torque += cross_vv(ra, force)
        if b is not None and not b.static:
            b.force = b.force - force
            rb = wb - b.position
            b.torque += cross_vv(rb, -force)


class PinJoint:
    """Point-to-point (revolute) constraint: pins a local anchor point on
    body_a to a fixed world point (body_b=None) or to an anchor point on
    body_b. Rotation is free — this is a hinge, not a weld."""

    def __init__(self, body_a, anchor_a_local, body_b=None, anchor_b_local=None):
        self.body_a = body_a
        self.body_b = body_b
        self.anchor_a_local = Vec2(*anchor_a_local)
        if body_b is not None:
            self.anchor_b_world_fixed = None
            self.anchor_b_local = Vec2(*(anchor_b_local or (0, 0)))
        else:
            wa = body_a.position + self.anchor_a_local.rotated(body_a.angle)
            self.anchor_b_world_fixed = Vec2(*anchor_b_local) if anchor_b_local else wa

    def _world_anchors(self):
        wa = self.body_a.position + self.anchor_a_local.rotated(self.body_a.angle)
        if self.body_b is not None:
            wb = self.body_b.position + self.anchor_b_local.rotated(self.body_b.angle)
        else:
            wb = self.anchor_b_world_fixed
        return wa, wb

    def solve(self, dt):
        a, b = self.body_a, self.body_b
        wa, wb = self._world_anchors()
        ra = wa - a.position
        rb = (wb - b.position) if b is not None else Vec2(0.0, 0.0)

        inv_mass_sum = a.inv_mass + (b.inv_mass if b else 0.0)
        k11 = inv_mass_sum + a.inv_inertia * ra.y * ra.y + (b.inv_inertia * rb.y * rb.y if b else 0.0)
        k12 = -a.inv_inertia * ra.x * ra.y - (b.inv_inertia * rb.x * rb.y if b else 0.0)
        k22 = inv_mass_sum + a.inv_inertia * ra.x * ra.x + (b.inv_inertia * rb.x * rb.x if b else 0.0)
        K = Mat22(k11, k12, k12, k22)
        K_inv = K.inverse()

        va = a.velocity + cross_sv(a.angular_velocity, ra)
        vb = (b.velocity + cross_sv(b.angular_velocity, rb)) if b else Vec2(0.0, 0.0)
        cdot = vb - va

        c = wb - wa
        bias = c * (BAUMGARTE / dt)

        impulse = K_inv.mul_vec(-(cdot) - bias)

        a.velocity = a.velocity - impulse * a.inv_mass
        a.angular_velocity -= a.inv_inertia * cross_vv(ra, impulse)
        if b is not None:
            b.velocity = b.velocity + impulse * b.inv_mass
            b.angular_velocity += b.inv_inertia * cross_vv(rb, impulse)


# --------------------------------------------------------------------------
# World
# --------------------------------------------------------------------------

class World:
    def __init__(self, gravity=GRAVITY, bounds=None):
        self.gravity = Vec2(*gravity)
        self.bodies = []
        self.joints = []
        self.broadphase = SpatialHash(cell_size=64.0)
        self.bounds = bounds  # optional (minx, miny, maxx, maxy) containing walls
        self.time = 0.0
        self.last_manifolds = []  # for debug rendering

    def add_body(self, body):
        self.bodies.append(body)
        return body

    def remove_body(self, body):
        if body in self.bodies:
            self.bodies.remove(body)
        self.joints = [j for j in self.joints
                        if getattr(j, "body_a", None) is not body
                        and getattr(j, "body_b", None) is not body]

    def add_joint(self, joint):
        self.joints.append(joint)
        return joint

    def clear(self):
        self.bodies = []
        self.joints = []
        self.time = 0.0

    def step(self, dt):
        if dt <= 0:
            return

        # 1. accumulate spring forces (uses velocities from the previous step)
        for joint in self.joints:
            if isinstance(joint, SpringJoint):
                joint.apply()

        # 2. integrate forces: gravity (as acceleration) + accumulated forces
        for body in self.bodies:
            if body.static:
                continue
            body.velocity = body.velocity + (self.gravity + body.force * body.inv_mass) * dt
            body.angular_velocity += body.torque * body.inv_inertia * dt
            body.velocity = body.velocity * (1.0 / (1.0 + dt * body.linear_damping))
            body.angular_velocity *= 1.0 / (1.0 + dt * body.angular_damping)
            body.force = Vec2(0.0, 0.0)
            body.torque = 0.0

        # 3. broad phase
        pairs = self.broadphase.candidate_pairs(self.bodies)

        # 4. narrow phase
        manifolds = []
        for ia, ib in pairs:
            a, b = self.bodies[ia], self.bodies[ib]
            if a.static and b.static:
                continue
            m = collide(a, b)
            if m is not None:
                manifolds.append(m)
        self.last_manifolds = manifolds

        # 5. velocity solve (joints + contacts), iterated
        for _ in range(VELOCITY_ITERATIONS):
            for joint in self.joints:
                if isinstance(joint, (DistanceJoint, PinJoint)):
                    joint.solve(dt)
            for m in manifolds:
                self._solve_contact(m, dt)

        # 6. integrate positions
        for body in self.bodies:
            if body.static:
                continue
            body.position = body.position + body.velocity * dt
            body.angle += body.angular_velocity * dt

        # 7. positional correction for contacts (prevents sinking)
        for m in manifolds:
            self._correct_positions(m)

        # 8. containing walls (optional simple boundary)
        if self.bounds is not None:
            self._enforce_bounds()

        self.time += dt

    def _solve_contact(self, m, dt):
        a, b = m.body_a, m.body_b
        for point, pen in zip(m.points, m.penetrations):
            ra = point - a.position
            rb = point - b.position

            va = a.velocity + cross_sv(a.angular_velocity, ra)
            vb = b.velocity + cross_sv(b.angular_velocity, rb)
            rel_vel = vb - va
            vel_along_normal = rel_vel.dot(m.normal)

            ra_cross_n = cross_vv(ra, m.normal)
            rb_cross_n = cross_vv(rb, m.normal)
            inv_mass_sum = (a.inv_mass + b.inv_mass +
                             a.inv_inertia * ra_cross_n ** 2 +
                             b.inv_inertia * rb_cross_n ** 2)
            if inv_mass_sum < 1e-12:
                continue

            bias = max(pen - SLOP, 0.0) * (BAUMGARTE / dt)
            j = -(1.0 + m.restitution) * vel_along_normal + bias
            j /= inv_mass_sum
            j = max(j, 0.0)

            impulse = m.normal * j
            a.velocity = a.velocity - impulse * a.inv_mass
            a.angular_velocity -= a.inv_inertia * cross_vv(ra, impulse)
            b.velocity = b.velocity + impulse * b.inv_mass
            b.angular_velocity += b.inv_inertia * cross_vv(rb, impulse)

            # friction (Coulomb, clamped by normal impulse)
            va = a.velocity + cross_sv(a.angular_velocity, ra)
            vb = b.velocity + cross_sv(b.angular_velocity, rb)
            rel_vel = vb - va
            tangent = rel_vel - m.normal * rel_vel.dot(m.normal)
            t_len = tangent.length()
            if t_len < 1e-9:
                continue
            tangent = tangent * (1.0 / t_len)

            ra_cross_t = cross_vv(ra, tangent)
            rb_cross_t = cross_vv(rb, tangent)
            t_mass_sum = (a.inv_mass + b.inv_mass +
                          a.inv_inertia * ra_cross_t ** 2 +
                          b.inv_inertia * rb_cross_t ** 2)
            if t_mass_sum < 1e-12:
                continue
            jt = -rel_vel.dot(tangent) / t_mass_sum
            max_friction = m.friction * j
            jt = max(-max_friction, min(jt, max_friction))

            friction_impulse = tangent * jt
            a.velocity = a.velocity - friction_impulse * a.inv_mass
            a.angular_velocity -= a.inv_inertia * cross_vv(ra, friction_impulse)
            b.velocity = b.velocity + friction_impulse * b.inv_mass
            b.angular_velocity += b.inv_inertia * cross_vv(rb, friction_impulse)

    def _correct_positions(self, m):
        a, b = m.body_a, m.body_b
        inv_mass_sum = a.inv_mass + b.inv_mass
        if inv_mass_sum < 1e-12:
            return
        for pen in m.penetrations:
            correction_mag = max(pen - SLOP, 0.0) / inv_mass_sum * BAUMGARTE
            correction_mag = min(correction_mag, MAX_LINEAR_CORRECTION)
            correction = m.normal * correction_mag
            if not a.static:
                a.position = a.position - correction * a.inv_mass
            if not b.static:
                b.position = b.position + correction * b.inv_mass

    def _enforce_bounds(self):
        minx, miny, maxx, maxy = self.bounds
        for body in self.bodies:
            if body.static:
                continue
            r = body.shape.aabb_radius()
            p = body.position
            v = body.velocity
            if p.x - r < minx:
                p.x = minx + r
                v.x = abs(v.x) * body.restitution
            elif p.x + r > maxx:
                p.x = maxx - r
                v.x = -abs(v.x) * body.restitution
            if p.y - r < miny:
                p.y = miny + r
                v.y = abs(v.y) * body.restitution
            elif p.y + r > maxy:
                p.y = maxy - r
                v.y = -abs(v.y) * body.restitution
            body.position = p
            body.velocity = v

    def _joint_dict(self, j):
        wa, wb = j._world_anchors()
        return {
            "type": type(j).__name__,
            "pa": [wa.x, wa.y],
            "pb": [wb.x, wb.y],
        }

    def to_dict(self):
        return {
            "time": self.time,
            "gravity": [self.gravity.x, self.gravity.y],
            "bodies": [b.to_dict() for b in self.bodies],
            "joints": [self._joint_dict(j) for j in self.joints],
            "contacts": [
                {"points": [[p.x, p.y] for p in m.points],
                 "normal": [m.normal.x, m.normal.y]}
                for m in self.last_manifolds
            ],
        }
