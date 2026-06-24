"""3-component vector with all math inlined for speed."""
import math
import random


class Vec3:
    __slots__ = ('x', 'y', 'z')

    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)

    # ── arithmetic ───────────────────────────────────────────────────────────

    def __add__(self, o):  return Vec3(self.x + o.x, self.y + o.y, self.z + o.z)
    def __sub__(self, o):  return Vec3(self.x - o.x, self.y - o.y, self.z - o.z)
    def __neg__(self):     return Vec3(-self.x, -self.y, -self.z)
    def __mul__(self, t):
        if isinstance(t, Vec3):
            return Vec3(self.x * t.x, self.y * t.y, self.z * t.z)
        return Vec3(self.x * t, self.y * t, self.z * t)
    def __rmul__(self, t): return self.__mul__(t)
    def __truediv__(self, t): return Vec3(self.x / t, self.y / t, self.z / t)
    def __iadd__(self, o): self.x += o.x; self.y += o.y; self.z += o.z; return self
    def __imul__(self, t):
        if isinstance(t, Vec3):
            self.x *= t.x; self.y *= t.y; self.z *= t.z
        else:
            self.x *= t; self.y *= t; self.z *= t
        return self

    # ── geometry ─────────────────────────────────────────────────────────────

    def dot(self, o):   return self.x*o.x + self.y*o.y + self.z*o.z
    def len_sq(self):   return self.x*self.x + self.y*self.y + self.z*self.z
    def length(self):   return math.sqrt(self.len_sq())
    def unit(self):     return self / self.length()

    def cross(self, o):
        return Vec3(self.y*o.z - self.z*o.y,
                    self.z*o.x - self.x*o.z,
                    self.x*o.y - self.y*o.x)

    def reflect(self, n):
        return self - n * (2.0 * self.dot(n))

    def refract(self, n, eta_ratio):
        cos_theta = min(-self.dot(n), 1.0)
        r_out_perp = (self + n * cos_theta) * eta_ratio
        r_out_para = n * (-math.sqrt(abs(1.0 - r_out_perp.len_sq())))
        return r_out_perp + r_out_para

    def near_zero(self):
        return abs(self.x) < 1e-8 and abs(self.y) < 1e-8 and abs(self.z) < 1e-8

    def clamp(self, lo=0.0, hi=1.0):
        return Vec3(max(lo, min(hi, self.x)),
                    max(lo, min(hi, self.y)),
                    max(lo, min(hi, self.z)))

    # ── constructors ─────────────────────────────────────────────────────────

    @staticmethod
    def random():
        return Vec3(random.random(), random.random(), random.random())

    @staticmethod
    def random_in_unit_sphere():
        while True:
            p = Vec3(random.uniform(-1, 1), random.uniform(-1, 1), random.uniform(-1, 1))
            if p.len_sq() < 1.0:
                return p

    @staticmethod
    def random_unit():
        return Vec3.random_in_unit_sphere().unit()

    @staticmethod
    def random_in_hemisphere(normal):
        u = Vec3.random_unit()
        return u if u.dot(normal) > 0 else -u

    @staticmethod
    def random_in_unit_disc():
        while True:
            p = Vec3(random.uniform(-1, 1), random.uniform(-1, 1), 0)
            if p.len_sq() < 1.0:
                return p

    @staticmethod
    def random_cosine_direction():
        r1 = random.random()
        r2 = random.random()
        z = math.sqrt(1.0 - r2)
        phi = 2.0 * math.pi * r1
        x = math.cos(phi) * math.sqrt(r2)
        y = math.sin(phi) * math.sqrt(r2)
        return Vec3(x, y, z)

    def __repr__(self):
        return f"Vec3({self.x:.4f}, {self.y:.4f}, {self.z:.4f})"

    def to_tuple(self):
        return (self.x, self.y, self.z)


def schlick(cosine, ref_idx):
    """Schlick approximation for Fresnel reflectance."""
    r0 = ((1 - ref_idx) / (1 + ref_idx)) ** 2
    return r0 + (1 - r0) * (1 - cosine) ** 5


def build_onb(normal):
    """Build orthonormal basis from a surface normal.
    Returns (u, v, w) where w = normal."""
    w = normal.unit()
    a = Vec3(1, 0, 0) if abs(w.x) < 0.9 else Vec3(0, 1, 0)
    v = w.cross(a).unit()
    u = w.cross(v)
    return u, v, w
