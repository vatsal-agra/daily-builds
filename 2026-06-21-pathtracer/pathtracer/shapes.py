"""Geometric primitives: Sphere, Box, Plane, Triangle, HittableList."""
import math

from .vec3 import Vec3
from .ray import Ray


class HitRecord:
    """Result of a ray-geometry intersection."""
    __slots__ = ('t', 'p', 'normal', 'front_face', 'u', 'v', 'material')

    def __init__(self, t, p, outward_normal, ray_dir, u, v, material):
        self.t = t
        self.p = p
        self.front_face = ray_dir.dot(outward_normal) < 0.0
        # Always store normal pointing against the incoming ray
        self.normal = outward_normal if self.front_face else -outward_normal
        self.u = u
        self.v = v
        self.material = material


# ---------- Sphere ----------

class Sphere:
    def __init__(self, center, radius, material):
        self.center = center
        self.radius = float(radius)
        self.material = material

    def hit(self, ray, t_min, t_max):
        oc = ray.origin - self.center
        a = ray.direction.length_sq()
        half_b = oc.dot(ray.direction)
        c = oc.length_sq() - self.radius * self.radius
        disc = half_b * half_b - a * c
        if disc < 0:
            return None
        sqrt_disc = math.sqrt(disc)
        # Try smaller root first
        root = (-half_b - sqrt_disc) / a
        if root < t_min or root > t_max:
            root = (-half_b + sqrt_disc) / a
            if root < t_min or root > t_max:
                return None
        t = root
        p = ray.at(t)
        outward_normal = (p - self.center) / self.radius
        u, v = _sphere_uv(outward_normal)
        return HitRecord(t, p, outward_normal, ray.direction, u, v, self.material)

    def bounding_box(self):
        r = abs(self.radius)
        rv = Vec3(r, r, r)
        return AABB(self.center - rv, self.center + rv)


def _sphere_uv(p):
    """UV coordinates from a unit-sphere surface point."""
    theta = math.acos(max(-1.0, min(1.0, -p.y)))
    phi = math.atan2(-p.z, p.x) + math.pi
    u = phi / (2.0 * math.pi)
    v = theta / math.pi
    return u, v


# ---------- Axis-Aligned Box ----------

class Box:
    """Axis-aligned box built from six quads (pair of triangles each)."""

    def __init__(self, p_min, p_max, material):
        self.p_min = p_min
        self.p_max = p_max
        self.material = material

    def hit(self, ray, t_min, t_max):
        # Slab intersection — track which face was hit for normals
        t_enter = t_min
        t_exit = t_max
        hit_axis = -1
        hit_sign = 0

        for axis in range(3):
            o = (ray.origin.x, ray.origin.y, ray.origin.z)[axis]
            d = (ray.direction.x, ray.direction.y, ray.direction.z)[axis]
            mn = (self.p_min.x, self.p_min.y, self.p_min.z)[axis]
            mx = (self.p_max.x, self.p_max.y, self.p_max.z)[axis]

            if abs(d) < 1e-10:
                if o < mn or o > mx:
                    return None
                continue

            inv_d = 1.0 / d
            t0 = (mn - o) * inv_d
            t1 = (mx - o) * inv_d
            if inv_d < 0:
                t0, t1 = t1, t0

            if t0 > t_enter:
                t_enter = t0
                hit_axis = axis
                hit_sign = -1 if d > 0 else 1

            t_exit = min(t_exit, t1)
            if t_exit <= t_enter:
                return None

        if t_enter < t_min or t_enter > t_max or hit_axis < 0:
            return None

        t = t_enter
        p = ray.at(t)

        normal_components = [0.0, 0.0, 0.0]
        normal_components[hit_axis] = float(hit_sign)
        outward_normal = Vec3(*normal_components)

        # UV: project onto dominant face
        u, v = _box_uv(p, outward_normal, self.p_min, self.p_max)
        return HitRecord(t, p, outward_normal, ray.direction, u, v, self.material)

    def bounding_box(self):
        return AABB(self.p_min, self.p_max)


def _box_uv(p, normal, p_min, p_max):
    ax = (abs(normal.x), abs(normal.y), abs(normal.z))
    if ax[0] > ax[1] and ax[0] > ax[2]:
        u = (p.y - p_min.y) / max(1e-10, p_max.y - p_min.y)
        v = (p.z - p_min.z) / max(1e-10, p_max.z - p_min.z)
    elif ax[1] > ax[2]:
        u = (p.x - p_min.x) / max(1e-10, p_max.x - p_min.x)
        v = (p.z - p_min.z) / max(1e-10, p_max.z - p_min.z)
    else:
        u = (p.x - p_min.x) / max(1e-10, p_max.x - p_min.x)
        v = (p.y - p_min.y) / max(1e-10, p_max.y - p_min.y)
    return max(0.0, min(1.0, u)), max(0.0, min(1.0, v))


# ---------- Infinite Plane ----------

class Plane:
    """Infinite plane defined by normal and distance from origin."""

    def __init__(self, normal, offset, material):
        """offset: plane satisfies p·normal = offset."""
        self.normal = normal.normalize()
        self.offset = float(offset)
        self.material = material

    def hit(self, ray, t_min, t_max):
        denom = ray.direction.dot(self.normal)
        if abs(denom) < 1e-10:
            return None
        t = (self.offset - ray.origin.dot(self.normal)) / denom
        if t < t_min or t > t_max:
            return None
        p = ray.at(t)
        # Arbitrary UV on infinite plane
        u, v = 0.5, 0.5
        return HitRecord(t, p, self.normal, ray.direction, u, v, self.material)

    def bounding_box(self):
        # Planes are infinite — return a huge AABB
        INF = 1e30
        return AABB(Vec3(-INF, -INF, -INF), Vec3(INF, INF, INF))


# ---------- Triangle ----------

class Triangle:
    """Single triangle with Möller-Trumbore intersection."""

    def __init__(self, v0, v1, v2, material):
        self.v0 = v0
        self.v1 = v1
        self.v2 = v2
        self.material = material
        e1 = v1 - v0
        e2 = v2 - v0
        self._outward_normal = e1.cross(e2).normalize()

    def hit(self, ray, t_min, t_max):
        e1 = self.v1 - self.v0
        e2 = self.v2 - self.v0
        h = ray.direction.cross(e2)
        a = e1.dot(h)
        if abs(a) < 1e-10:
            return None  # ray parallel to triangle
        f = 1.0 / a
        s = ray.origin - self.v0
        u = f * s.dot(h)
        if u < 0.0 or u > 1.0:
            return None
        q = s.cross(e1)
        v = f * ray.direction.dot(q)
        if v < 0.0 or u + v > 1.0:
            return None
        t = f * e2.dot(q)
        if t < t_min or t > t_max:
            return None
        p = ray.at(t)
        return HitRecord(t, p, self._outward_normal, ray.direction, u, v, self.material)

    def bounding_box(self):
        EPS = 0.0001
        mn = Vec3(
            min(self.v0.x, self.v1.x, self.v2.x) - EPS,
            min(self.v0.y, self.v1.y, self.v2.y) - EPS,
            min(self.v0.z, self.v1.z, self.v2.z) - EPS,
        )
        mx = Vec3(
            max(self.v0.x, self.v1.x, self.v2.x) + EPS,
            max(self.v0.y, self.v1.y, self.v2.y) + EPS,
            max(self.v0.z, self.v1.z, self.v2.z) + EPS,
        )
        return AABB(mn, mx)


# ---------- HittableList (brute-force) ----------

class HittableList:
    def __init__(self, objects=None):
        self.objects = list(objects) if objects else []

    def add(self, obj):
        self.objects.append(obj)

    def hit(self, ray, t_min, t_max):
        closest = None
        t_closest = t_max
        for obj in self.objects:
            rec = obj.hit(ray, t_min, t_closest)
            if rec is not None:
                t_closest = rec.t
                closest = rec
        return closest

    def bounding_box(self):
        if not self.objects:
            return AABB(Vec3(0, 0, 0), Vec3(0, 0, 0))
        box = self.objects[0].bounding_box()
        for obj in self.objects[1:]:
            box = AABB.surrounding(box, obj.bounding_box())
        return box


# ---------- AABB ----------

class AABB:
    __slots__ = ('mn', 'mx')

    def __init__(self, mn, mx):
        self.mn = mn
        self.mx = mx

    def hit(self, ray, t_min, t_max):
        for i, (o, d, lo, hi) in enumerate(zip(
            (ray.origin.x,    ray.origin.y,    ray.origin.z),
            (ray.direction.x, ray.direction.y, ray.direction.z),
            (self.mn.x,       self.mn.y,       self.mn.z),
            (self.mx.x,       self.mx.y,       self.mx.z),
        )):
            if abs(d) < 1e-10:
                if o < lo or o > hi:
                    return False
                continue
            inv_d = 1.0 / d
            t0 = (lo - o) * inv_d
            t1 = (hi - o) * inv_d
            if inv_d < 0:
                t0, t1 = t1, t0
            t_min = max(t_min, t0)
            t_max = min(t_max, t1)
            if t_max <= t_min:
                return False
        return True

    def surface_area(self):
        d = self.mx - self.mn
        dx, dy, dz = abs(d.x), abs(d.y), abs(d.z)
        return 2.0 * (dx * dy + dy * dz + dz * dx)

    def centroid(self):
        return (self.mn + self.mx) * 0.5

    @staticmethod
    def surrounding(a, b):
        mn = Vec3(min(a.mn.x, b.mn.x), min(a.mn.y, b.mn.y), min(a.mn.z, b.mn.z))
        mx = Vec3(max(a.mx.x, b.mx.x), max(a.mx.y, b.mx.y), max(a.mx.z, b.mx.z))
        return AABB(mn, mx)

    def __repr__(self):
        return f"AABB({self.mn!r}, {self.mx!r})"
