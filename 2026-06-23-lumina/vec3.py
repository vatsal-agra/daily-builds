"""Vector math, rays, and axis-aligned bounding boxes for Lumina path tracer."""
import math
import random as _rng

INF = float('inf')


class Vec3:
    __slots__ = ('x', 'y', 'z')

    def __init__(self, x: float, y: float, z: float):
        self.x = x; self.y = y; self.z = z

    def __add__(self, o: 'Vec3') -> 'Vec3':
        return Vec3(self.x + o.x, self.y + o.y, self.z + o.z)

    def __sub__(self, o: 'Vec3') -> 'Vec3':
        return Vec3(self.x - o.x, self.y - o.y, self.z - o.z)

    def __mul__(self, o) -> 'Vec3':
        if isinstance(o, Vec3):
            return Vec3(self.x * o.x, self.y * o.y, self.z * o.z)
        return Vec3(self.x * o, self.y * o, self.z * o)

    def __rmul__(self, o) -> 'Vec3':
        return self.__mul__(o)

    def __truediv__(self, s: float) -> 'Vec3':
        inv = 1.0 / s
        return Vec3(self.x * inv, self.y * inv, self.z * inv)

    def __neg__(self) -> 'Vec3':
        return Vec3(-self.x, -self.y, -self.z)

    def __repr__(self) -> str:
        return f"Vec3({self.x:.4f},{self.y:.4f},{self.z:.4f})"

    def __iter__(self):
        return iter((self.x, self.y, self.z))

    def dot(self, o: 'Vec3') -> float:
        return self.x * o.x + self.y * o.y + self.z * o.z

    def cross(self, o: 'Vec3') -> 'Vec3':
        return Vec3(
            self.y * o.z - self.z * o.y,
            self.z * o.x - self.x * o.z,
            self.x * o.y - self.y * o.x,
        )

    def length_sq(self) -> float:
        return self.x * self.x + self.y * self.y + self.z * self.z

    def length(self) -> float:
        return math.sqrt(self.length_sq())

    def normalize(self) -> 'Vec3':
        l = self.length()
        if l < 1e-30:
            return Vec3(0.0, 1.0, 0.0)
        inv = 1.0 / l
        return Vec3(self.x * inv, self.y * inv, self.z * inv)

    def max_component(self) -> float:
        return max(self.x, self.y, self.z)

    def near_zero(self) -> bool:
        return abs(self.x) < 1e-8 and abs(self.y) < 1e-8 and abs(self.z) < 1e-8

    def clamp(self, lo: float, hi: float) -> 'Vec3':
        return Vec3(max(lo, min(hi, self.x)),
                    max(lo, min(hi, self.y)),
                    max(lo, min(hi, self.z)))

    def gamma(self, g: float = 2.2) -> 'Vec3':
        e = 1.0 / g
        return Vec3(self.x ** e, self.y ** e, self.z ** e)

    @staticmethod
    def zero() -> 'Vec3':
        return Vec3(0.0, 0.0, 0.0)

    @staticmethod
    def one() -> 'Vec3':
        return Vec3(1.0, 1.0, 1.0)

    @staticmethod
    def random_in_unit_sphere() -> 'Vec3':
        while True:
            x = _rng.uniform(-1.0, 1.0)
            y = _rng.uniform(-1.0, 1.0)
            z = _rng.uniform(-1.0, 1.0)
            if x * x + y * y + z * z < 1.0:
                return Vec3(x, y, z)

    @staticmethod
    def random_unit() -> 'Vec3':
        while True:
            x = _rng.uniform(-1.0, 1.0)
            y = _rng.uniform(-1.0, 1.0)
            z = _rng.uniform(-1.0, 1.0)
            sq = x * x + y * y + z * z
            if 1e-30 < sq <= 1.0:
                inv = 1.0 / math.sqrt(sq)
                return Vec3(x * inv, y * inv, z * inv)

    @staticmethod
    def random_in_unit_disk() -> 'Vec3':
        while True:
            x = _rng.uniform(-1.0, 1.0)
            y = _rng.uniform(-1.0, 1.0)
            if x * x + y * y < 1.0:
                return Vec3(x, y, 0.0)

    @staticmethod
    def random_cosine_hemisphere(normal: 'Vec3') -> 'Vec3':
        """Cosine-weighted hemisphere sample via Malley's method."""
        r1 = _rng.random()
        r2 = _rng.random()
        phi = 2.0 * math.pi * r1
        sin_phi = math.sin(phi)
        cos_phi = math.cos(phi)
        sr2 = math.sqrt(r2)
        x = cos_phi * sr2
        y = sin_phi * sr2
        z = math.sqrt(max(0.0, 1.0 - r2))
        # Build orthonormal basis around normal
        if abs(normal.x) > 0.9:
            up = Vec3(0.0, 1.0, 0.0)
        else:
            up = Vec3(1.0, 0.0, 0.0)
        tangent = up.cross(normal).normalize()
        bitangent = normal.cross(tangent)
        return Vec3(
            x * tangent.x + y * bitangent.x + z * normal.x,
            x * tangent.y + y * bitangent.y + z * normal.y,
            x * tangent.z + y * bitangent.z + z * normal.z,
        )


def reflect(v: Vec3, n: Vec3) -> Vec3:
    return v - n * (2.0 * v.dot(n))


def refract(v: Vec3, n: Vec3, ni_over_nt: float):
    """Snell's law refraction. Returns refracted Vec3 or None on TIR."""
    uv = v.normalize()
    dt = uv.dot(n)
    discriminant = 1.0 - ni_over_nt * ni_over_nt * (1.0 - dt * dt)
    if discriminant < 0.0:
        return None
    return ni_over_nt * (uv - n * dt) - n * math.sqrt(discriminant)


def schlick(cosine: float, ref_idx: float) -> float:
    """Schlick Fresnel approximation."""
    r0 = ((1.0 - ref_idx) / (1.0 + ref_idx)) ** 2
    return r0 + (1.0 - r0) * (1.0 - cosine) ** 5


class Ray:
    __slots__ = ('origin', 'direction')

    def __init__(self, origin: Vec3, direction: Vec3):
        self.origin = origin
        self.direction = direction

    def at(self, t: float) -> Vec3:
        return Vec3(
            self.origin.x + t * self.direction.x,
            self.origin.y + t * self.direction.y,
            self.origin.z + t * self.direction.z,
        )


class AABB:
    """Axis-aligned bounding box."""
    __slots__ = ('min_p', 'max_p')

    def __init__(self, min_p: Vec3, max_p: Vec3):
        # Pad degenerate boxes to avoid zero-thickness slabs
        eps = 1e-4
        self.min_p = Vec3(
            min_p.x if max_p.x - min_p.x > eps else min_p.x - eps,
            min_p.y if max_p.y - min_p.y > eps else min_p.y - eps,
            min_p.z if max_p.z - min_p.z > eps else min_p.z - eps,
        )
        self.max_p = Vec3(
            max_p.x if max_p.x - min_p.x > eps else max_p.x + eps,
            max_p.y if max_p.y - min_p.y > eps else max_p.y + eps,
            max_p.z if max_p.z - min_p.z > eps else max_p.z + eps,
        )

    def hit(self, ray: Ray, t_min: float, t_max: float) -> bool:
        # X slab
        d = ray.direction.x
        if abs(d) < 1e-12:
            if ray.origin.x < self.min_p.x or ray.origin.x > self.max_p.x:
                return False
        else:
            inv = 1.0 / d
            t0 = (self.min_p.x - ray.origin.x) * inv
            t1 = (self.max_p.x - ray.origin.x) * inv
            if inv < 0.0: t0, t1 = t1, t0
            t_min = max(t_min, t0)
            t_max = min(t_max, t1)
            if t_max <= t_min: return False
        # Y slab
        d = ray.direction.y
        if abs(d) < 1e-12:
            if ray.origin.y < self.min_p.y or ray.origin.y > self.max_p.y:
                return False
        else:
            inv = 1.0 / d
            t0 = (self.min_p.y - ray.origin.y) * inv
            t1 = (self.max_p.y - ray.origin.y) * inv
            if inv < 0.0: t0, t1 = t1, t0
            t_min = max(t_min, t0)
            t_max = min(t_max, t1)
            if t_max <= t_min: return False
        # Z slab
        d = ray.direction.z
        if abs(d) < 1e-12:
            if ray.origin.z < self.min_p.z or ray.origin.z > self.max_p.z:
                return False
        else:
            inv = 1.0 / d
            t0 = (self.min_p.z - ray.origin.z) * inv
            t1 = (self.max_p.z - ray.origin.z) * inv
            if inv < 0.0: t0, t1 = t1, t0
            t_min = max(t_min, t0)
            t_max = min(t_max, t1)
            if t_max <= t_min: return False
        return True

    def surface_area(self) -> float:
        d = self.max_p - self.min_p
        return 2.0 * (d.x * d.y + d.y * d.z + d.z * d.x)

    def centroid(self) -> Vec3:
        return Vec3(
            (self.min_p.x + self.max_p.x) * 0.5,
            (self.min_p.y + self.max_p.y) * 0.5,
            (self.min_p.z + self.max_p.z) * 0.5,
        )

    @staticmethod
    def surrounding(a: 'AABB', b: 'AABB') -> 'AABB':
        return AABB(
            Vec3(min(a.min_p.x, b.min_p.x),
                 min(a.min_p.y, b.min_p.y),
                 min(a.min_p.z, b.min_p.z)),
            Vec3(max(a.max_p.x, b.max_p.x),
                 max(a.max_p.y, b.max_p.y),
                 max(a.max_p.z, b.max_p.z)),
        )
