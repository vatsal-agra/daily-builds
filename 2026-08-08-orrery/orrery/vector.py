"""A minimal 3D vector class. No NumPy — this repo builds from scratch."""

import math


class Vec3:
    __slots__ = ("x", "y", "z")

    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)

    def __add__(self, other):
        return Vec3(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other):
        return Vec3(self.x - other.x, self.y - other.y, self.z - other.z)

    def __neg__(self):
        return Vec3(-self.x, -self.y, -self.z)

    def __mul__(self, scalar):
        return Vec3(self.x * scalar, self.y * scalar, self.z * scalar)

    __rmul__ = __mul__

    def __truediv__(self, scalar):
        return Vec3(self.x / scalar, self.y / scalar, self.z / scalar)

    def __iadd__(self, other):
        self.x += other.x
        self.y += other.y
        self.z += other.z
        return self

    def __eq__(self, other):
        if not isinstance(other, Vec3):
            return NotImplemented
        return self.x == other.x and self.y == other.y and self.z == other.z

    def __repr__(self):
        return f"Vec3({self.x!r}, {self.y!r}, {self.z!r})"

    def dot(self, other):
        return self.x * other.x + self.y * other.y + self.z * other.z

    def cross(self, other):
        return Vec3(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x,
        )

    def norm(self):
        return math.sqrt(self.dot(self))

    def norm_sq(self):
        return self.dot(self)

    def normalized(self):
        n = self.norm()
        if n == 0.0:
            return Vec3(0.0, 0.0, 0.0)
        return self / n

    def is_finite(self):
        return all(math.isfinite(v) for v in (self.x, self.y, self.z))

    def to_tuple(self):
        return (self.x, self.y, self.z)

    @staticmethod
    def from_tuple(t):
        return Vec3(t[0], t[1], t[2])

    def copy(self):
        return Vec3(self.x, self.y, self.z)
