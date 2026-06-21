"""Physically-based materials: Lambertian, Metal, Dielectric, DiffuseLight."""
import math

from .vec3 import (Vec3, reflect, refract, schlick,
                   random_unit_vector, sample_cosine_hemisphere)
from .textures import SolidTexture, _wrap


class Lambertian:
    """Perfectly diffuse surface — cosine-weighted hemisphere scattering."""

    def __init__(self, albedo):
        self.albedo = _wrap(albedo)

    def scatter(self, ray_in, hit, rng):
        scattered_dir = sample_cosine_hemisphere(rng, hit.normal)
        if scattered_dir.near_zero():
            scattered_dir = hit.normal
        from .ray import Ray
        scattered = Ray(hit.p, scattered_dir)
        attenuation = self.albedo.value(hit.u, hit.v, hit.p)
        return scattered, attenuation

    def emitted(self, u, v, p):
        return Vec3(0, 0, 0)


class Metal:
    """Mirror-like reflection with optional roughness (0 = perfect mirror)."""

    def __init__(self, albedo, roughness=0.0):
        self.albedo = _wrap(albedo)
        self.roughness = max(0.0, min(1.0, roughness))

    def scatter(self, ray_in, hit, rng):
        reflected = reflect(ray_in.direction.normalize(), hit.normal)
        fuzz = self.roughness * random_unit_vector(rng) if self.roughness > 0 else Vec3(0, 0, 0)
        scattered_dir = (reflected + fuzz).normalize()
        if scattered_dir.dot(hit.normal) <= 0:
            return None  # absorbed below surface
        from .ray import Ray
        scattered = Ray(hit.p, scattered_dir)
        attenuation = self.albedo.value(hit.u, hit.v, hit.p)
        return scattered, attenuation

    def emitted(self, u, v, p):
        return Vec3(0, 0, 0)


class Dielectric:
    """Glass / water — refraction + Fresnel reflection via Schlick approximation."""

    def __init__(self, ior=1.5):
        self.ior = ior  # index of refraction

    def scatter(self, ray_in, hit, rng):
        attenuation = Vec3(1.0, 1.0, 1.0)
        eta_ratio = (1.0 / self.ior) if hit.front_face else self.ior

        unit_dir = ray_in.direction.normalize()
        cos_theta = min((-unit_dir).dot(hit.normal), 1.0)
        sin_theta = math.sqrt(max(0.0, 1.0 - cos_theta * cos_theta))

        # Total internal reflection OR probabilistic Fresnel reflection
        cannot_refract = eta_ratio * sin_theta > 1.0
        if cannot_refract or schlick(cos_theta, eta_ratio) > rng.random():
            direction = reflect(unit_dir, hit.normal)
        else:
            direction = refract(unit_dir, hit.normal, eta_ratio)
            if direction is None:
                direction = reflect(unit_dir, hit.normal)

        from .ray import Ray
        return Ray(hit.p, direction), attenuation

    def emitted(self, u, v, p):
        return Vec3(0, 0, 0)


class DiffuseLight:
    """Area light — emits colour, does not scatter."""

    def __init__(self, color, intensity=1.0):
        if isinstance(color, Vec3):
            self.emit_tex = SolidTexture(color * intensity)
        else:
            self.emit_tex = SolidTexture(Vec3(*color) * intensity)

    def scatter(self, ray_in, hit, rng):
        return None  # no scattering

    def emitted(self, u, v, p):
        return self.emit_tex.value(u, v, p)
