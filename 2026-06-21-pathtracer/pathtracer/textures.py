"""Procedural and solid textures."""
import math
import random as _rand

from .vec3 import Vec3


class SolidTexture:
    def __init__(self, color):
        self.color = color if isinstance(color, Vec3) else Vec3(*color)

    def value(self, u, v, p):
        return self.color


class CheckerTexture:
    """Alternates two sub-textures on world-space coordinates."""

    def __init__(self, even, odd, scale=10.0):
        self.even = _wrap(even)
        self.odd = _wrap(odd)
        self.scale = scale

    def value(self, u, v, p):
        sines = (math.sin(self.scale * p.x) *
                 math.sin(self.scale * p.y) *
                 math.sin(self.scale * p.z))
        return self.even.value(u, v, p) if sines >= 0 else self.odd.value(u, v, p)


class PerlinTexture:
    """Marble/wood pattern via gradient Perlin noise + turbulence + sine warp."""

    _N = 256

    def __init__(self, color1, color2, scale=4.0, seed=42):
        self.color1 = color1 if isinstance(color1, Vec3) else Vec3(*color1)
        self.color2 = color2 if isinstance(color2, Vec3) else Vec3(*color2)
        self.scale = scale
        rng = _rand.Random(seed)
        self._ranvec = [_random_unit_vec(rng) for _ in range(self._N)]
        self._perm_x = _generate_perm(rng, self._N)
        self._perm_y = _generate_perm(rng, self._N)
        self._perm_z = _generate_perm(rng, self._N)

    def noise(self, p):
        u = p.x - math.floor(p.x)
        v = p.y - math.floor(p.y)
        w = p.z - math.floor(p.z)
        i = int(math.floor(p.x)) & (self._N - 1)
        j = int(math.floor(p.y)) & (self._N - 1)
        k = int(math.floor(p.z)) & (self._N - 1)
        c = [[[None] * 2 for _ in range(2)] for _ in range(2)]
        for di in range(2):
            for dj in range(2):
                for dk in range(2):
                    idx = (self._perm_x[(i + di) & (self._N - 1)] ^
                           self._perm_y[(j + dj) & (self._N - 1)] ^
                           self._perm_z[(k + dk) & (self._N - 1)])
                    c[di][dj][dk] = self._ranvec[idx]
        return _trilinear_interp(c, u, v, w)

    def turbulence(self, p, depth=7):
        accum = 0.0
        weight = 1.0
        for _ in range(depth):
            accum += weight * self.noise(p)
            weight *= 0.5
            p = p * 2.0
        return abs(accum)

    def value(self, u, v, p):
        t = 0.5 * (1.0 + math.sin(self.scale * p.z + 10.0 * self.turbulence(p)))
        t = max(0.0, min(1.0, t))
        return self.color1 * (1.0 - t) + self.color2 * t


# ---- helpers ----

def _wrap(tex):
    """Accept a texture object or a colour tuple/list/Vec3."""
    if isinstance(tex, (SolidTexture, CheckerTexture, PerlinTexture)):
        return tex
    return SolidTexture(tex)


def _random_unit_vec(rng):
    theta = rng.uniform(0, 2 * math.pi)
    phi = math.acos(2 * rng.random() - 1)
    return Vec3(
        math.sin(phi) * math.cos(theta),
        math.sin(phi) * math.sin(theta),
        math.cos(phi),
    )


def _generate_perm(rng, n):
    p = list(range(n))
    rng.shuffle(p)
    return p


def _trilinear_interp(c, u, v, w):
    """Hermite-smoothed trilinear interpolation of gradient vectors."""
    uu = u * u * (3 - 2 * u)
    vv = v * v * (3 - 2 * v)
    ww = w * w * (3 - 2 * w)
    accum = 0.0
    for i in range(2):
        for j in range(2):
            for k in range(2):
                weight = Vec3(u - i, v - j, w - k)
                accum += ((i * uu + (1 - i) * (1 - uu)) *
                          (j * vv + (1 - j) * (1 - vv)) *
                          (k * ww + (1 - k) * (1 - ww)) *
                          c[i][j][k].dot(weight))
    return accum
