"""Pinhole camera with optional thin-lens depth-of-field."""
import math
import random
from .vec3 import Vec3
from .ray import Ray


class Camera:
    def __init__(self, look_from, look_at, vup,
                 vfov=40.0, aspect=16/9,
                 aperture=0.0, focus_dist=1.0):
        theta = math.radians(vfov)
        h = math.tan(theta / 2)
        viewport_height = 2.0 * h
        viewport_width  = aspect * viewport_height

        self.w = (look_from - look_at).unit()
        self.u = vup.cross(self.w).unit()
        self.v = self.w.cross(self.u)

        self.origin = look_from
        self.horizontal = self.u * (viewport_width  * focus_dist)
        self.vertical   = self.v * (viewport_height * focus_dist)
        self.lower_left = (self.origin
                           - self.horizontal * 0.5
                           - self.vertical   * 0.5
                           - self.w * focus_dist)
        self.lens_radius = aperture / 2.0

    def get_ray(self, s, t):
        if self.lens_radius > 0:
            rd = Vec3.random_in_unit_disc() * self.lens_radius
            offset = self.u * rd.x + self.v * rd.y
        else:
            offset = Vec3(0, 0, 0)
        origin = self.origin + offset
        direction = (self.lower_left
                     + self.horizontal * s
                     + self.vertical   * t
                     - origin)
        return Ray(origin, direction.unit())
