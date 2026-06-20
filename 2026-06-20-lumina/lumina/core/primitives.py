"""Geometric primitives: Sphere, Plane, Triangle."""
import math
from .vec3 import Vec3
from .aabb import AABB
from .materials import HitRecord


class Sphere:
    def __init__(self, center, radius, material):
        self.center = center
        self.radius = radius
        self.material = material

    def hit(self, ray, t_min, t_max, rec):
        oc = ray.origin - self.center
        a = ray.direction.len_sq()
        half_b = oc.dot(ray.direction)
        c = oc.len_sq() - self.radius * self.radius
        disc = half_b * half_b - a * c
        if disc < 0:
            return False
        sqrtd = math.sqrt(disc)
        root = (-half_b - sqrtd) / a
        if root < t_min or root > t_max:
            root = (-half_b + sqrtd) / a
            if root < t_min or root > t_max:
                return False
        rec.t = root
        rec.p = ray.at(root)
        outward = (rec.p - self.center) / self.radius
        rec.set_face_normal(ray, outward)
        rec.material = self.material
        # UV coords
        theta = math.acos(-outward.y)
        phi = math.atan2(-outward.z, outward.x) + math.pi
        rec.u = phi / (2 * math.pi)
        rec.v = theta / math.pi
        return True

    def bounding_box(self):
        r = abs(self.radius)
        rv = Vec3(r, r, r)
        return AABB(self.center - rv, self.center + rv)


class Plane:
    """Infinite plane defined by point + normal. One-sided."""

    def __init__(self, point, normal, material):
        self.point = point
        self.normal = normal.unit()
        self.material = material

    def hit(self, ray, t_min, t_max, rec):
        denom = self.normal.dot(ray.direction)
        if abs(denom) < 1e-8:
            return False
        t = (self.point - ray.origin).dot(self.normal) / denom
        if t < t_min or t > t_max:
            return False
        rec.t = t
        rec.p = ray.at(t)
        rec.set_face_normal(ray, self.normal)
        rec.material = self.material
        rec.u = rec.p.x % 1.0
        rec.v = rec.p.z % 1.0
        return True

    def bounding_box(self):
        # Planes are infinite; give a large AABB
        BIG = 1e4
        n = self.normal
        # Create a huge slab around the plane's normal direction
        if abs(n.y) > 0.9:
            return AABB(Vec3(-BIG, self.point.y - 0.001, -BIG),
                        Vec3(BIG,  self.point.y + 0.001,  BIG))
        elif abs(n.x) > 0.9:
            return AABB(Vec3(self.point.x - 0.001, -BIG, -BIG),
                        Vec3(self.point.x + 0.001,  BIG,  BIG))
        else:
            return AABB(Vec3(-BIG, -BIG, self.point.z - 0.001),
                        Vec3( BIG,  BIG, self.point.z + 0.001))


class Triangle:
    """Möller–Trumbore intersection. Two-sided by default."""

    def __init__(self, v0, v1, v2, material, two_sided=True):
        self.v0 = v0
        self.v1 = v1
        self.v2 = v2
        self.material = material
        self.two_sided = two_sided
        # Pre-compute edges and normal
        e1 = v1 - v0
        e2 = v2 - v0
        self._e1 = e1
        self._e2 = e2
        n = e1.cross(e2)
        self._normal = n.unit() if n.len_sq() > 1e-12 else Vec3(0, 1, 0)

    def hit(self, ray, t_min, t_max, rec):
        e1, e2 = self._e1, self._e2
        h = ray.direction.cross(e2)
        a = e1.dot(h)
        if abs(a) < 1e-8:
            return False
        f = 1.0 / a
        s = ray.origin - self.v0
        u = f * s.dot(h)
        if u < 0.0 or u > 1.0:
            return False
        q = s.cross(e1)
        v = f * ray.direction.dot(q)
        if v < 0.0 or u + v > 1.0:
            return False
        t = f * e2.dot(q)
        if t < t_min or t > t_max:
            return False
        rec.t = t
        rec.p = ray.at(t)
        rec.set_face_normal(ray, self._normal)
        rec.material = self.material
        rec.u = u
        rec.v = v
        return True

    def bounding_box(self):
        return AABB.from_points([self.v0, self.v1, self.v2])


class Quad:
    """Axis-aligned quadrilateral (box face, floor, etc.)."""

    def __init__(self, corner, u_vec, v_vec, material):
        """corner + u_vec * s + v_vec * t, 0<=s,t<=1"""
        self.corner = corner
        self.u_vec = u_vec
        self.v_vec = v_vec
        self.material = material
        n = u_vec.cross(v_vec)
        self._normal = n.unit()
        self._d = self._normal.dot(corner)
        w = n / n.len_sq()
        self._w = w

    def hit(self, ray, t_min, t_max, rec):
        denom = self._normal.dot(ray.direction)
        if abs(denom) < 1e-8:
            return False
        t = (self._d - self._normal.dot(ray.origin)) / denom
        if t < t_min or t > t_max:
            return False
        p = ray.at(t)
        planar_hit = p - self.corner
        alpha = self._w.dot(planar_hit.cross(self.v_vec))
        beta  = self._w.dot(self.u_vec.cross(planar_hit))
        if alpha < 0 or alpha > 1 or beta < 0 or beta > 1:
            return False
        rec.t = t
        rec.p = p
        rec.set_face_normal(ray, self._normal)
        rec.material = self.material
        rec.u = alpha
        rec.v = beta
        return True

    def bounding_box(self):
        pts = [self.corner,
               self.corner + self.u_vec,
               self.corner + self.v_vec,
               self.corner + self.u_vec + self.v_vec]
        return AABB.from_points(pts)


class Box:
    """Axis-aligned box built from 6 Quads."""

    def __init__(self, a, b, material):
        dx = Vec3(b.x - a.x, 0, 0)
        dy = Vec3(0, b.y - a.y, 0)
        dz = Vec3(0, 0, b.z - a.z)
        self.faces = [
            Quad(a, dx, dy, material),                          # front  -z
            Quad(Vec3(b.x, a.y, a.z), -dx, dy, material),      # back   +z... wait
            Quad(a, dz, dy, material),                          # left
            Quad(Vec3(b.x, a.y, a.z), -dz, dy, material),      # right
            Quad(Vec3(a.x, b.y, a.z), dx, dz, material),       # top
            Quad(a, dx, dz, material),                          # bottom ... swap dz sign
        ]
        # Rebuild properly
        self.faces = []
        # front face (z=a.z), normal -z
        self.faces.append(Quad(a, dx, dy, material))
        # back face (z=b.z), normal +z
        self.faces.append(Quad(Vec3(b.x, a.y, b.z), -dx, dy, material))
        # left face (x=a.x), normal -x
        self.faces.append(Quad(a, dz, dy, material))
        # right face (x=b.x), normal +x
        self.faces.append(Quad(Vec3(b.x, a.y, a.z), -dz, dy, material))
        # bottom face (y=a.y), normal -y
        self.faces.append(Quad(a, dx, dz, material))
        # top face (y=b.y), normal +y
        self.faces.append(Quad(Vec3(a.x, b.y, b.z), dx, -dz, material))
        self._bbox = AABB(a, b)

    def hit(self, ray, t_min, t_max, rec):
        hit_any = False
        closest = t_max
        for face in self.faces:
            tmp = HitRecord()
            if face.hit(ray, t_min, closest, tmp):
                hit_any = True
                closest = tmp.t
                rec.t = tmp.t
                rec.p = tmp.p
                rec.normal = tmp.normal
                rec.front_face = tmp.front_face
                rec.material = tmp.material
                rec.u = tmp.u
                rec.v = tmp.v
        return hit_any

    def bounding_box(self):
        return self._bbox


class PrimitiveList:
    """Flat list of primitives — used as BVH leaf or fallback."""

    def __init__(self, objects=None):
        self.objects = objects or []

    def add(self, obj):
        self.objects.append(obj)

    def hit(self, ray, t_min, t_max, rec):
        hit_any = False
        closest = t_max
        for obj in self.objects:
            tmp = HitRecord()
            if obj.hit(ray, t_min, closest, tmp):
                hit_any = True
                closest = tmp.t
                rec.t = tmp.t
                rec.p = tmp.p
                rec.normal = tmp.normal
                rec.front_face = tmp.front_face
                rec.material = tmp.material
                rec.u = tmp.u
                rec.v = tmp.v
        return hit_any

    def bounding_box(self):
        if not self.objects:
            return AABB(Vec3(-1,-1,-1), Vec3(1,1,1))
        box = self.objects[0].bounding_box()
        for obj in self.objects[1:]:
            box = AABB.surrounding(box, obj.bounding_box())
        return box
