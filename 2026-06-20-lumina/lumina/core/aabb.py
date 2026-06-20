"""Axis-Aligned Bounding Box with slab-method ray intersection."""
from .vec3 import Vec3


class AABB:
    __slots__ = ('minimum', 'maximum')

    def __init__(self, minimum: Vec3, maximum: Vec3):
        self.minimum = minimum
        self.maximum = maximum

    def hit(self, ray, t_min: float, t_max: float) -> bool:
        """Slab-method intersection; returns True if ray hits box in [t_min, t_max]."""
        ox, oy, oz = ray.origin.x, ray.origin.y, ray.origin.z
        dx, dy, dz = ray.direction.x, ray.direction.y, ray.direction.z
        mnx, mny, mnz = self.minimum.x, self.minimum.y, self.minimum.z
        mxx, mxy, mxz = self.maximum.x, self.maximum.y, self.maximum.z

        # X slab
        if dx != 0.0:
            inv = 1.0 / dx
            t0 = (mnx - ox) * inv
            t1 = (mxx - ox) * inv
            if inv < 0: t0, t1 = t1, t0
        else:
            if ox < mnx or ox > mxx:
                return False
            t0, t1 = t_min, t_max
        t_min = max(t_min, t0)
        t_max = min(t_max, t1)
        if t_max <= t_min:
            return False

        # Y slab
        if dy != 0.0:
            inv = 1.0 / dy
            t0 = (mny - oy) * inv
            t1 = (mxy - oy) * inv
            if inv < 0: t0, t1 = t1, t0
        else:
            if oy < mny or oy > mxy:
                return False
            t0, t1 = t_min, t_max
        t_min = max(t_min, t0)
        t_max = min(t_max, t1)
        if t_max <= t_min:
            return False

        # Z slab
        if dz != 0.0:
            inv = 1.0 / dz
            t0 = (mnz - oz) * inv
            t1 = (mxz - oz) * inv
            if inv < 0: t0, t1 = t1, t0
        else:
            if oz < mnz or oz > mxz:
                return False
            t0, t1 = t_min, t_max
        t_min = max(t_min, t0)
        t_max = min(t_max, t1)
        return t_max > t_min

    def surface_area(self) -> float:
        d = self.maximum - self.minimum
        return 2.0 * (d.x * d.y + d.y * d.z + d.z * d.x)

    @staticmethod
    def surrounding(a: 'AABB', b: 'AABB') -> 'AABB':
        small = Vec3(min(a.minimum.x, b.minimum.x),
                     min(a.minimum.y, b.minimum.y),
                     min(a.minimum.z, b.minimum.z))
        big   = Vec3(max(a.maximum.x, b.maximum.x),
                     max(a.maximum.y, b.maximum.y),
                     max(a.maximum.z, b.maximum.z))
        return AABB(small, big)

    @staticmethod
    def from_points(pts):
        mn = Vec3(min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts))
        mx = Vec3(max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts))
        # pad degenerate flat boxes slightly
        eps = 1e-4
        if mn.x == mx.x: mn.x -= eps; mx.x += eps
        if mn.y == mx.y: mn.y -= eps; mx.y += eps
        if mn.z == mx.z: mn.z -= eps; mx.z += eps
        return AABB(mn, mx)
