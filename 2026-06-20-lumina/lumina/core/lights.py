"""Light types for the Whitted tracer."""
import math
import random
from .vec3 import Vec3


class PointLight:
    def __init__(self, position, colour=None, intensity=1.0):
        self.position = position
        self.colour = colour or Vec3(1, 1, 1)
        self.intensity = intensity

    def direction_and_distance(self, point):
        vec = self.position - point
        dist = vec.length()
        return vec.unit(), dist


class DirectionalLight:
    def __init__(self, direction, colour=None, intensity=1.0):
        self.direction = (-direction).unit()   # point toward source
        self.colour = colour or Vec3(1, 1, 1)
        self.intensity = intensity

    def direction_and_distance(self, point):
        return self.direction, 1e9


class AreaLight:
    """Rectangular area light for soft shadows (Whitted mode, stratified sampling)."""

    def __init__(self, corner, u_vec, v_vec, colour=None, intensity=1.0, samples=4):
        self.corner = corner
        self.u_vec = u_vec
        self.v_vec = v_vec
        self.colour = colour or Vec3(1, 1, 1)
        self.intensity = intensity
        self.samples = samples   # samples × samples stratified grid

    def direction_and_distance(self, point):
        # Single random sample — averaged at call site
        s = random.random()
        t = random.random()
        pos = self.corner + self.u_vec * s + self.v_vec * t
        vec = pos - point
        dist = vec.length()
        return vec.unit(), dist

    def sample_directions(self, point, n=None):
        """Yield (L_dir, dist) pairs for stratified n×n samples."""
        if n is None:
            n = self.samples
        for i in range(n):
            for j in range(n):
                s = (i + random.random()) / n
                t = (j + random.random()) / n
                pos = self.corner + self.u_vec * s + self.v_vec * t
                vec = pos - point
                dist = vec.length()
                yield vec.unit(), dist
