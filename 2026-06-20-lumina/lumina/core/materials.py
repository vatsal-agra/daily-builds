"""Materials: Lambertian, Metal, Dielectric, Phong, Emissive."""
import math
import random
from .vec3 import Vec3, schlick, build_onb


class HitRecord:
    __slots__ = ('t', 'p', 'normal', 'front_face', 'material', 'u', 'v')

    def __init__(self):
        self.t = 0.0
        self.p = Vec3()
        self.normal = Vec3()
        self.front_face = True
        self.material = None
        self.u = 0.0
        self.v = 0.0

    def set_face_normal(self, ray, outward_normal):
        self.front_face = ray.direction.dot(outward_normal) < 0
        self.normal = outward_normal if self.front_face else -outward_normal


class ScatterRecord:
    """Returned by material.scatter(); holds reflected/refracted ray + attenuation."""
    __slots__ = ('ray', 'attenuation', 'is_specular')

    def __init__(self, ray, attenuation, is_specular=False):
        self.ray = ray
        self.attenuation = attenuation
        self.is_specular = is_specular


class Lambertian:
    """Perfectly diffuse / matte surface."""

    def __init__(self, albedo):
        self.albedo = albedo   # Vec3 colour

    def scatter(self, ray_in, rec):
        from .ray import Ray
        u, v, w = build_onb(rec.normal)
        # cosine-weighted hemisphere sample in local ONB
        cd = Vec3.random_cosine_direction()
        scatter_dir = u * cd.x + v * cd.y + w * cd.z
        if scatter_dir.near_zero():
            scatter_dir = rec.normal
        return ScatterRecord(Ray(rec.p, scatter_dir.unit()), self.albedo)

    def emitted(self, u, v, p):
        return Vec3(0, 0, 0)

    def phong_shade(self, ray_in, rec, lights):
        return Vec3(0, 0, 0)  # handled by path tracer / Whitted separately


class Metal:
    """Specular mirror (fuzz=0) or brushed metal (fuzz>0)."""

    def __init__(self, albedo, fuzz=0.0):
        self.albedo = albedo
        self.fuzz = min(fuzz, 1.0)

    def scatter(self, ray_in, rec):
        from .ray import Ray
        reflected = ray_in.direction.unit().reflect(rec.normal)
        scattered = reflected + Vec3.random_in_unit_sphere() * self.fuzz
        if scattered.dot(rec.normal) > 0:
            return ScatterRecord(Ray(rec.p, scattered), self.albedo, is_specular=True)
        return None

    def emitted(self, u, v, p):
        return Vec3(0, 0, 0)


class Dielectric:
    """Glass-like material with Snell's law refraction + Schlick Fresnel."""

    def __init__(self, ior=1.5):
        self.ior = ior   # index of refraction

    def scatter(self, ray_in, rec):
        from .ray import Ray
        attenuation = Vec3(1, 1, 1)
        eta_ratio = (1.0 / self.ior) if rec.front_face else self.ior

        unit_dir = ray_in.direction.unit()
        cos_theta = min(-unit_dir.dot(rec.normal), 1.0)
        sin_theta = math.sqrt(1.0 - cos_theta * cos_theta)

        cannot_refract = eta_ratio * sin_theta > 1.0
        if cannot_refract or schlick(cos_theta, eta_ratio) > random.random():
            direction = unit_dir.reflect(rec.normal)
        else:
            direction = unit_dir.refract(rec.normal, eta_ratio)

        return ScatterRecord(Ray(rec.p, direction), attenuation, is_specular=True)

    def emitted(self, u, v, p):
        return Vec3(0, 0, 0)


class Phong:
    """Classic Phong BRDF — ambient + diffuse + specular + shininess.
    Used by the Whitted tracer for deterministic rendering."""

    def __init__(self, diffuse, specular=None, shininess=32.0, ambient=None):
        self.diffuse = diffuse               # Vec3 base colour
        self.specular = specular or Vec3(0.8, 0.8, 0.8)
        self.shininess = shininess
        self.ambient = ambient or diffuse * 0.1

    def scatter(self, ray_in, rec):
        # Phong scatters diffusely for path tracer compatibility
        from .ray import Ray
        u, v, w = build_onb(rec.normal)
        cd = Vec3.random_cosine_direction()
        scatter_dir = (u * cd.x + v * cd.y + w * cd.z).unit()
        return ScatterRecord(Ray(rec.p, scatter_dir), self.diffuse)

    def shade(self, ray_in, rec, lights, world, t_min=0.001, t_max=1e9):
        """Whitted shading: iterate lights, cast shadow rays."""
        from .ray import Ray
        colour = self.ambient.clamp()
        view_dir = (-ray_in.direction).unit()

        for light in lights:
            L, dist = light.direction_and_distance(rec.p)
            # shadow ray
            shadow = Ray(rec.p, L)
            shadow_rec = HitRecord()
            in_shadow = world.hit(shadow, 0.001, dist - 0.001, shadow_rec)
            if in_shadow:
                continue

            # diffuse
            ndl = max(0.0, rec.normal.dot(L))
            diffuse_contrib = self.diffuse * (light.intensity * ndl)

            # specular (Blinn-Phong half-vector)
            h = (L + view_dir).unit()
            ndh = max(0.0, rec.normal.dot(h))
            spec_contrib = self.specular * (light.intensity * ndh ** self.shininess)

            colour = colour + diffuse_contrib * light.colour + spec_contrib * light.colour

        return colour.clamp()

    def emitted(self, u, v, p):
        return Vec3(0, 0, 0)


class Emissive:
    """Glowing surface — acts as an area light for the path tracer."""

    def __init__(self, colour, strength=1.0):
        self.colour = colour
        self.strength = strength

    def scatter(self, ray_in, rec):
        return None  # emissive surfaces absorb incoming rays

    def emitted(self, u, v, p):
        return self.colour * self.strength
