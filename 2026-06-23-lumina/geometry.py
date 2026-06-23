"""Geometric primitives and SAH-BVH acceleration structure for Lumina.

Primitives:
  Sphere    - analytic quadratic intersection
  Triangle  - Möller-Trumbore algorithm
  Plane     - infinite half-plane (one-sided)
  QuadLight - axis-aligned emissive rectangle (for Cornell box lights)
  BVHNode   - recursive SAH-split BVH over any list of hittables

All primitives expose:
  hit(ray, t_min, t_max) -> HitRecord or None
  bounding_box()         -> AABB
  (optional) sample_point() -> (point, normal, area)  for light sampling
"""
import math
import random
from vec3 import Vec3, Ray, AABB, INF
from materials import HitRecord


class Sphere:
    def __init__(self, center: Vec3, radius: float, material):
        self.center = center
        self.radius = radius
        self.material = material
        self._area = 4.0 * math.pi * radius * radius

    def hit(self, ray: Ray, t_min: float, t_max: float):
        oc = Vec3(ray.origin.x - self.center.x,
                  ray.origin.y - self.center.y,
                  ray.origin.z - self.center.z)
        a = ray.direction.length_sq()
        half_b = oc.dot(ray.direction)
        c = oc.length_sq() - self.radius * self.radius
        discriminant = half_b * half_b - a * c
        if discriminant < 0.0:
            return None
        sqrtd = math.sqrt(discriminant)
        inv_a = 1.0 / a

        root = (-half_b - sqrtd) * inv_a
        if root <= t_min or root >= t_max:
            root = (-half_b + sqrtd) * inv_a
            if root <= t_min or root >= t_max:
                return None

        t = root
        p = ray.at(t)
        outward_normal = Vec3(
            (p.x - self.center.x) / self.radius,
            (p.y - self.center.y) / self.radius,
            (p.z - self.center.z) / self.radius,
        )
        rec = HitRecord(t, p, outward_normal, self.material, True)
        rec.set_face_normal(ray, outward_normal)
        return rec

    def bounding_box(self) -> AABB:
        r = self.radius
        c = self.center
        return AABB(Vec3(c.x - r, c.y - r, c.z - r),
                    Vec3(c.x + r, c.y + r, c.z + r))

    def sample_point(self):
        """Uniform random point on sphere surface. Returns (point, normal, area)."""
        d = Vec3.random_unit()
        p = Vec3(self.center.x + d.x * self.radius,
                 self.center.y + d.y * self.radius,
                 self.center.z + d.z * self.radius)
        return p, d, self._area


class Triangle:
    """Möller-Trumbore triangle intersection."""

    def __init__(self, v0: Vec3, v1: Vec3, v2: Vec3, material,
                 n0=None, n1=None, n2=None):
        self.v0 = v0
        self.v1 = v1
        self.v2 = v2
        self.material = material
        # Precompute edges and geometric normal
        self.e1 = v1 - v0
        self.e2 = v2 - v0
        geom_n = self.e1.cross(self.e2)
        area_x2 = geom_n.length()
        if area_x2 < 1e-20:
            self._degenerate = True
            self._normal = Vec3(0.0, 1.0, 0.0)
            self._area = 0.0
        else:
            self._degenerate = False
            self._normal = geom_n / area_x2  # normalized
            self._area = area_x2 * 0.5
        # Smooth shading normals (per-vertex); if None, use flat shading
        self.n0 = n0 or self._normal
        self.n1 = n1 or self._normal
        self.n2 = n2 or self._normal

    def hit(self, ray: Ray, t_min: float, t_max: float):
        if self._degenerate:
            return None
        h = ray.direction.cross(self.e2)
        a = self.e1.dot(h)
        if abs(a) < 1e-12:
            return None
        inv_a = 1.0 / a
        s = ray.origin - self.v0
        u = s.dot(h) * inv_a
        if u < 0.0 or u > 1.0:
            return None
        q = s.cross(self.e1)
        v = ray.direction.dot(q) * inv_a
        if v < 0.0 or u + v > 1.0:
            return None
        t = self.e2.dot(q) * inv_a
        if t <= t_min or t >= t_max:
            return None
        w = 1.0 - u - v
        # Interpolated normal
        sn = Vec3(
            w * self.n0.x + u * self.n1.x + v * self.n2.x,
            w * self.n0.y + u * self.n1.y + v * self.n2.y,
            w * self.n0.z + u * self.n1.z + v * self.n2.z,
        ).normalize()
        p = ray.at(t)
        rec = HitRecord(t, p, sn, self.material, True, u, v)
        rec.set_face_normal(ray, sn)
        return rec

    def bounding_box(self) -> AABB:
        return AABB(
            Vec3(min(self.v0.x, self.v1.x, self.v2.x),
                 min(self.v0.y, self.v1.y, self.v2.y),
                 min(self.v0.z, self.v1.z, self.v2.z)),
            Vec3(max(self.v0.x, self.v1.x, self.v2.x),
                 max(self.v0.y, self.v1.y, self.v2.y),
                 max(self.v0.z, self.v1.z, self.v2.z)),
        )

    def sample_point(self):
        """Uniform random point on triangle surface."""
        r1 = math.sqrt(random.random())
        r2 = random.random()
        u = 1.0 - r1
        v = r1 * (1.0 - r2)
        w = r1 * r2
        p = Vec3(
            u * self.v0.x + v * self.v1.x + w * self.v2.x,
            u * self.v0.y + v * self.v1.y + w * self.v2.y,
            u * self.v0.z + v * self.v1.z + w * self.v2.z,
        )
        return p, self._normal, self._area


class Plane:
    """Infinite one-sided plane (only intersects from positive-normal side)."""

    def __init__(self, point: Vec3, normal: Vec3, material):
        self.point = point
        self.normal = normal.normalize()
        self.material = material

    def hit(self, ray: Ray, t_min: float, t_max: float):
        denom = self.normal.dot(ray.direction)
        if abs(denom) < 1e-10:
            return None  # Parallel
        t = self.normal.dot(self.point - ray.origin) / denom
        if t <= t_min or t >= t_max:
            return None
        p = ray.at(t)
        rec = HitRecord(t, p, self.normal, self.material, True)
        rec.set_face_normal(ray, self.normal)
        return rec

    def bounding_box(self) -> AABB:
        # Infinite plane needs a large box
        BIG = 1e4
        n = self.normal
        # Dominant axis is the normal; clip on the other two
        eps = 0.01
        if abs(n.y) > 0.9:
            return AABB(Vec3(-BIG, self.point.y - eps, -BIG),
                        Vec3(BIG, self.point.y + eps, BIG))
        if abs(n.x) > 0.9:
            return AABB(Vec3(self.point.x - eps, -BIG, -BIG),
                        Vec3(self.point.x + eps, BIG, BIG))
        return AABB(Vec3(-BIG, -BIG, self.point.z - eps),
                    Vec3(BIG, BIG, self.point.z + eps))


class QuadLight:
    """Axis-aligned rectangular emissive area light.

    The quad lies in one of three axis-aligned planes (XY, XZ, or YZ).
    Supports direct light sampling (sample_point).
    """

    def __init__(self, corner: Vec3, u: Vec3, v: Vec3, material):
        """
        corner: one corner of the quad
        u, v:   edge vectors along two axes (orthogonal)
        material: should be an Emissive material
        """
        self.corner = corner
        self.u = u
        self.v = v
        self.material = material
        normal_raw = u.cross(v)
        area_x2 = normal_raw.length()
        self._normal = normal_raw / area_x2 if area_x2 > 1e-20 else Vec3(0, 1, 0)
        self._area = area_x2  # Parallelogram area = |u × v|
        self._d = self._normal.dot(corner)  # Plane equation constant

    def hit(self, ray: Ray, t_min: float, t_max: float):
        denom = self._normal.dot(ray.direction)
        if abs(denom) < 1e-10:
            return None
        t = (self._d - self._normal.dot(ray.origin)) / denom
        if t <= t_min or t >= t_max:
            return None
        p = ray.at(t)
        # Check if p is inside the parallelogram
        p_local = p - self.corner
        alpha = p_local.dot(self.u) / self.u.length_sq()
        beta = p_local.dot(self.v) / self.v.length_sq()
        if not (0.0 <= alpha <= 1.0 and 0.0 <= beta <= 1.0):
            return None
        rec = HitRecord(t, p, self._normal, self.material, True, alpha, beta)
        rec.set_face_normal(ray, self._normal)
        return rec

    def bounding_box(self) -> AABB:
        p0 = self.corner
        p1 = self.corner + self.u
        p2 = self.corner + self.v
        p3 = self.corner + self.u + self.v
        return AABB(
            Vec3(min(p0.x, p1.x, p2.x, p3.x),
                 min(p0.y, p1.y, p2.y, p3.y),
                 min(p0.z, p1.z, p2.z, p3.z)),
            Vec3(max(p0.x, p1.x, p2.x, p3.x),
                 max(p0.y, p1.y, p2.y, p3.y),
                 max(p0.z, p1.z, p2.z, p3.z)),
        )

    def sample_point(self):
        """Uniform random point on quad surface."""
        r1 = random.random()
        r2 = random.random()
        p = self.corner + r1 * self.u + r2 * self.v
        return p, self._normal, self._area


class BVHNode:
    """SAH-partitioned Bounding Volume Hierarchy node.

    Construction: sort objects by their centroid on the best split axis,
    try all N-1 split positions and pick the one that minimizes
    (SA_left × n_left + SA_right × n_right) / SA_parent.
    """

    def __init__(self, objects: list, t0: float = 0.0, t1: float = 0.0):
        if not objects:
            raise ValueError("BVH: empty object list")

        # Compute bounding boxes once
        boxes = [obj.bounding_box() for obj in objects]
        n = len(objects)

        if n == 1:
            self.left = objects[0]
            self.right = None
            self.box = boxes[0]
            return
        if n == 2:
            self.left = objects[0]
            self.right = objects[1]
            self.box = AABB.surrounding(boxes[0], boxes[1])
            return

        # Overall bounding box of all centroids (for choosing split axis)
        centroids = [b.centroid() for b in boxes]
        cx = [c.x for c in centroids]
        cy = [c.y for c in centroids]
        cz = [c.z for c in centroids]
        extent_x = max(cx) - min(cx)
        extent_y = max(cy) - min(cy)
        extent_z = max(cz) - min(cz)

        # Choose the axis with the greatest centroid spread
        if extent_x >= extent_y and extent_x >= extent_z:
            axis = 0
        elif extent_y >= extent_z:
            axis = 1
        else:
            axis = 2

        # Compute total bounding box surface area for SAH normalization
        total_box = boxes[0]
        for b in boxes[1:]:
            total_box = AABB.surrounding(total_box, b)

        # Sort by centroid on chosen axis
        key = lambda i: (centroids[i].x, centroids[i].y, centroids[i].z)[axis]
        order = sorted(range(n), key=key)
        sorted_objs = [objects[i] for i in order]
        sorted_boxes = [boxes[i] for i in order]

        # SAH: try all n-1 split positions
        # Left prefix boxes
        left_boxes = [None] * n
        left_boxes[0] = sorted_boxes[0]
        for i in range(1, n):
            left_boxes[i] = AABB.surrounding(left_boxes[i - 1], sorted_boxes[i])

        # Right suffix boxes
        right_boxes = [None] * n
        right_boxes[n - 1] = sorted_boxes[n - 1]
        for i in range(n - 2, -1, -1):
            right_boxes[i] = AABB.surrounding(right_boxes[i + 1], sorted_boxes[i])

        best_cost = INF
        best_split = n // 2  # fallback to midpoint
        for i in range(1, n):
            cost = (left_boxes[i - 1].surface_area() * i +
                    right_boxes[i].surface_area() * (n - i))
            if cost < best_cost:
                best_cost = cost
                best_split = i

        left_objs = sorted_objs[:best_split]
        right_objs = sorted_objs[best_split:]

        self.left = BVHNode(left_objs) if len(left_objs) > 1 else left_objs[0]
        self.right = BVHNode(right_objs) if len(right_objs) > 1 else right_objs[0]
        lb = self.left.bounding_box()
        rb = self.right.bounding_box()
        self.box = AABB.surrounding(lb, rb)

    def hit(self, ray: Ray, t_min: float, t_max: float):
        if not self.box.hit(ray, t_min, t_max):
            return None
        # Hit left, then try to improve t_max with right
        hit_left = self.left.hit(ray, t_min, t_max)
        t_upper = hit_left.t if hit_left else t_max
        hit_right = self.right.hit(ray, t_min, t_upper) if self.right else None
        return hit_right if hit_right else hit_left

    def bounding_box(self) -> AABB:
        return self.box


class HittableList:
    """Unaccelerated list of hittables (used for small scenes / testing)."""

    def __init__(self, objects: list = None):
        self.objects = objects or []

    def add(self, obj):
        self.objects.append(obj)

    def hit(self, ray: Ray, t_min: float, t_max: float):
        closest = None
        t_closest = t_max
        for obj in self.objects:
            rec = obj.hit(ray, t_min, t_closest)
            if rec:
                closest = rec
                t_closest = rec.t
        return closest

    def bounding_box(self) -> AABB:
        if not self.objects:
            return AABB(Vec3.zero(), Vec3.zero())
        box = self.objects[0].bounding_box()
        for obj in self.objects[1:]:
            box = AABB.surrounding(box, obj.bounding_box())
        return box


def make_box(p_min: Vec3, p_max: Vec3, material) -> list:
    """Return 12 triangles forming an axis-aligned box."""
    x0, y0, z0 = p_min.x, p_min.y, p_min.z
    x1, y1, z1 = p_max.x, p_max.y, p_max.z
    tris = []
    # Bottom (y = y0, normal -Y)
    tris += [Triangle(Vec3(x0,y0,z0), Vec3(x1,y0,z0), Vec3(x1,y0,z1), material),
             Triangle(Vec3(x0,y0,z0), Vec3(x1,y0,z1), Vec3(x0,y0,z1), material)]
    # Top (y = y1, normal +Y)
    tris += [Triangle(Vec3(x0,y1,z0), Vec3(x1,y1,z1), Vec3(x1,y1,z0), material),
             Triangle(Vec3(x0,y1,z0), Vec3(x0,y1,z1), Vec3(x1,y1,z1), material)]
    # Front (z = z1, normal +Z)
    tris += [Triangle(Vec3(x0,y0,z1), Vec3(x1,y0,z1), Vec3(x1,y1,z1), material),
             Triangle(Vec3(x0,y0,z1), Vec3(x1,y1,z1), Vec3(x0,y1,z1), material)]
    # Back (z = z0, normal -Z)
    tris += [Triangle(Vec3(x0,y0,z0), Vec3(x1,y1,z0), Vec3(x1,y0,z0), material),
             Triangle(Vec3(x0,y0,z0), Vec3(x0,y1,z0), Vec3(x1,y1,z0), material)]
    # Left (x = x0, normal -X)
    tris += [Triangle(Vec3(x0,y0,z0), Vec3(x0,y0,z1), Vec3(x0,y1,z1), material),
             Triangle(Vec3(x0,y0,z0), Vec3(x0,y1,z1), Vec3(x0,y1,z0), material)]
    # Right (x = x1, normal +X)
    tris += [Triangle(Vec3(x1,y0,z0), Vec3(x1,y1,z1), Vec3(x1,y0,z1), material),
             Triangle(Vec3(x1,y0,z0), Vec3(x1,y1,z0), Vec3(x1,y1,z1), material)]
    return tris


def rotate_y(obj_list: list, angle_deg: float, pivot: Vec3) -> list:
    """Rotate a list of Triangle primitives around Y axis by angle_deg degrees."""
    theta = math.radians(angle_deg)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)

    def rot(p: Vec3) -> Vec3:
        dx = p.x - pivot.x
        dz = p.z - pivot.z
        return Vec3(cos_t * dx + sin_t * dz + pivot.x,
                    p.y,
                    -sin_t * dx + cos_t * dz + pivot.z)

    result = []
    for obj in obj_list:
        if isinstance(obj, Triangle):
            v0r, v1r, v2r = rot(obj.v0), rot(obj.v1), rot(obj.v2)
            result.append(Triangle(v0r, v1r, v2r, obj.material))
        else:
            result.append(obj)
    return result
