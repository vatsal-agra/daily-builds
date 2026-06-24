"""Ray: origin + direction."""
from .vec3 import Vec3


class Ray:
    __slots__ = ('origin', 'direction')

    def __init__(self, origin: Vec3, direction: Vec3):
        self.origin = origin
        self.direction = direction

    def at(self, t: float) -> Vec3:
        return self.origin + self.direction * t

    def __repr__(self):
        return f"Ray({self.origin} -> {self.direction})"
