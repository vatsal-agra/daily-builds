"""Perspective camera with optional thin-lens depth-of-field."""
import math

from .vec3 import Vec3, random_in_unit_disk
from .ray import Ray


class Camera:
    def __init__(
        self,
        look_from,
        look_at,
        up,
        vfov_deg,
        aspect_ratio,
        aperture=0.0,
        focus_dist=None,
    ):
        """
        look_from / look_at / up: Vec3 positions
        vfov_deg: vertical field of view in degrees
        aperture:  lens diameter (0 = pinhole, no DOF)
        focus_dist: distance to the focal plane (defaults to dist(look_from, look_at))
        """
        self.look_from = look_from
        self.aperture = aperture

        if focus_dist is None:
            focus_dist = (look_at - look_from).length()
        self.focus_dist = focus_dist
        self.lens_radius = aperture / 2.0

        theta = math.radians(vfov_deg)
        h = math.tan(theta / 2.0)
        viewport_height = 2.0 * h
        viewport_width = aspect_ratio * viewport_height

        # Camera frame
        self.w = (look_from - look_at).normalize()  # points toward camera
        self.u = up.cross(self.w).normalize()        # camera right
        self.v = self.w.cross(self.u)                # camera up

        self.horizontal = focus_dist * viewport_width * self.u
        self.vertical = focus_dist * viewport_height * self.v
        self.lower_left = (look_from
                           - self.horizontal * 0.5
                           - self.vertical * 0.5
                           - focus_dist * self.w)

    def get_ray(self, s, t, rng):
        """Generate a ray through screen coordinates (s, t) ∈ [0, 1]².
        If aperture > 0, samples the lens for depth-of-field."""
        if self.lens_radius > 0.0:
            rd = random_in_unit_disk(rng) * self.lens_radius
            offset = self.u * rd.x + self.v * rd.y
        else:
            offset = Vec3(0, 0, 0)

        target = self.lower_left + s * self.horizontal + t * self.vertical
        origin = self.look_from + offset
        direction = target - origin
        return Ray(origin, direction)
