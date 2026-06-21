"""3-D vector math — no external deps."""
import math


class Vec3:
    __slots__ = ('x', 'y', 'z')

    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)

    # ---- arithmetic ----
    def __add__(self, o):
        return Vec3(self.x + o.x, self.y + o.y, self.z + o.z)

    def __radd__(self, o):
        return self.__add__(o) if isinstance(o, Vec3) else self

    def __sub__(self, o):
        return Vec3(self.x - o.x, self.y - o.y, self.z - o.z)

    def __mul__(self, o):
        if isinstance(o, Vec3):
            return Vec3(self.x * o.x, self.y * o.y, self.z * o.z)
        return Vec3(self.x * o, self.y * o, self.z * o)

    def __rmul__(self, o):
        return self.__mul__(o)

    def __truediv__(self, t):
        return Vec3(self.x / t, self.y / t, self.z / t)

    def __neg__(self):
        return Vec3(-self.x, -self.y, -self.z)

    def __iter__(self):
        return iter((self.x, self.y, self.z))

    def __repr__(self):
        return f"Vec3({self.x:.5f}, {self.y:.5f}, {self.z:.5f})"

    def __eq__(self, o):
        return (isinstance(o, Vec3) and
                abs(self.x - o.x) < 1e-9 and
                abs(self.y - o.y) < 1e-9 and
                abs(self.z - o.z) < 1e-9)

    def __hash__(self):
        return hash((round(self.x, 9), round(self.y, 9), round(self.z, 9)))

    # ---- pickle support for multiprocessing ----
    def __getstate__(self):
        return (self.x, self.y, self.z)

    def __setstate__(self, state):
        self.x, self.y, self.z = state

    # ---- geometry ----
    def length_sq(self):
        return self.x * self.x + self.y * self.y + self.z * self.z

    def length(self):
        return math.sqrt(self.length_sq())

    def normalize(self):
        l = self.length()
        if l < 1e-12:
            return Vec3(0.0, 0.0, 1.0)
        return Vec3(self.x / l, self.y / l, self.z / l)

    def dot(self, o):
        return self.x * o.x + self.y * o.y + self.z * o.z

    def cross(self, o):
        return Vec3(
            self.y * o.z - self.z * o.y,
            self.z * o.x - self.x * o.z,
            self.x * o.y - self.y * o.x,
        )

    def near_zero(self, eps=1e-8):
        return abs(self.x) < eps and abs(self.y) < eps and abs(self.z) < eps

    def clamp(self, lo=0.0, hi=1.0):
        return Vec3(
            max(lo, min(hi, self.x)),
            max(lo, min(hi, self.y)),
            max(lo, min(hi, self.z)),
        )

    def luminance(self):
        return 0.2126 * self.x + 0.7152 * self.y + 0.0722 * self.z

    def to_rgb8(self):
        c = self.clamp()
        return (int(c.x * 255.999), int(c.y * 255.999), int(c.z * 255.999))


# ---- free functions ----

def reflect(v, n):
    """Reflect v about normal n (both vectors, n normalised)."""
    return v - 2.0 * v.dot(n) * n


def refract(v, n, eta_ratio):
    """Snell's law refraction. v normalised, n normalised pointing against v.
    Returns refracted direction or None on total internal reflection."""
    cos_theta = min((-v).dot(n), 1.0)
    r_perp = eta_ratio * (v + cos_theta * n)
    disc = 1.0 - r_perp.length_sq()
    if disc < 0.0:
        return None
    r_parallel = -math.sqrt(disc) * n
    return r_perp + r_parallel


def schlick(cosine, ref_idx):
    """Fresnel-Schlick approximation for reflectance."""
    cosine = max(0.0, min(1.0, cosine))  # clamp; fp error can push outside [0,1]
    r0 = ((1.0 - ref_idx) / (1.0 + ref_idx)) ** 2
    return r0 + (1.0 - r0) * (1.0 - cosine) ** 5


def random_in_unit_sphere(rng):
    while True:
        p = Vec3(rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))
        if p.length_sq() < 1.0:
            return p


def random_unit_vector(rng):
    return random_in_unit_sphere(rng).normalize()


def random_in_unit_disk(rng):
    while True:
        p = Vec3(rng.uniform(-1, 1), rng.uniform(-1, 1), 0.0)
        if p.length_sq() < 1.0:
            return p


def random_cosine_direction(rng):
    """Cosine-weighted hemisphere sample in local z-up frame."""
    r1 = rng.random()
    r2 = rng.random()
    phi = 2.0 * math.pi * r1
    sqrt_r2 = math.sqrt(r2)
    return Vec3(
        math.cos(phi) * sqrt_r2,
        math.sin(phi) * sqrt_r2,
        math.sqrt(max(0.0, 1.0 - r2)),
    )


def build_onb(n):
    """Orthonormal basis (u, v, w) with w aligned to n."""
    n = n.normalize()
    a = Vec3(1, 0, 0) if abs(n.x) < 0.9 else Vec3(0, 1, 0)
    v = n.cross(a).normalize()
    u = n.cross(v)
    return u, v, n


def sample_cosine_hemisphere(rng, normal):
    """Cosine-weighted direction in world space around `normal`."""
    u, v, w = build_onb(normal)
    d = random_cosine_direction(rng)
    return (u * d.x + v * d.y + w * d.z).normalize()
