"""Physically-based material types for Lumina path tracer.

Each material implements:
  scatter(ray_in, hit) -> (attenuation, scattered_ray, pdf, is_specular) or None
  emitted(hit) -> Vec3  (black for non-emissive materials)
  pdf(hit, direction) -> float  (BRDF PDF for direct light sampling)
  brdf(hit, wo, wi) -> Vec3     (BRDF value for direct light sampling)
"""
import math
import random
from vec3 import Vec3, Ray, reflect, refract, schlick


class HitRecord:
    """Result of a ray-primitive intersection."""
    __slots__ = ('t', 'point', 'normal', 'material', 'front_face', 'u', 'v')

    def __init__(self, t, point, normal, material, front_face, u=0.0, v=0.0):
        self.t = t
        self.point = point
        self.normal = normal      # Always points outward from the surface
        self.material = material
        self.front_face = front_face  # True if ray hit the front face
        self.u = u
        self.v = v

    def set_face_normal(self, ray, outward_normal):
        self.front_face = ray.direction.dot(outward_normal) < 0.0
        self.normal = outward_normal if self.front_face else -outward_normal


class Lambertian:
    """Perfectly diffuse material using cosine-weighted hemisphere sampling.

    BRDF = albedo / π
    PDF  = cos(θ) / π  (cosine-weighted hemisphere)
    BRDF * cos(θ) / PDF = albedo  (the π cancels)
    """

    def __init__(self, albedo: Vec3):
        self.albedo = albedo
        self.is_specular = False

    def scatter(self, ray_in: Ray, hit: HitRecord):
        direction = Vec3.random_cosine_hemisphere(hit.normal)
        # Degenerate scatter direction
        if direction.near_zero():
            direction = hit.normal
        cos_theta = max(0.0, direction.dot(hit.normal))
        pdf = cos_theta / math.pi
        if pdf < 1e-10:
            return None
        scattered = Ray(hit.point, direction)
        attenuation = self.albedo
        return attenuation, scattered, pdf, False

    def pdf(self, hit: HitRecord, direction: Vec3) -> float:
        cos_theta = direction.normalize().dot(hit.normal)
        return max(0.0, cos_theta / math.pi)

    def brdf(self, hit: HitRecord, wo: Vec3, wi: Vec3) -> Vec3:
        return self.albedo / math.pi

    def emitted(self, hit: HitRecord) -> Vec3:
        return Vec3.zero()


class Metal:
    """Mirror-like metal with optional fuzz (micro-roughness)."""

    def __init__(self, albedo: Vec3, fuzz: float = 0.0):
        self.albedo = albedo
        self.fuzz = min(fuzz, 1.0)
        self.is_specular = True

    def scatter(self, ray_in: Ray, hit: HitRecord):
        reflected = reflect(ray_in.direction.normalize(), hit.normal)
        if self.fuzz > 0.0:
            reflected = (reflected + self.fuzz * Vec3.random_in_unit_sphere()).normalize()
        if reflected.dot(hit.normal) <= 0.0:
            return None  # Fuzz sent ray below surface
        scattered = Ray(hit.point, reflected)
        return self.albedo, scattered, 1.0, True

    def pdf(self, hit: HitRecord, direction: Vec3) -> float:
        return 0.0  # Delta distribution, not sampled directly

    def brdf(self, hit: HitRecord, wo: Vec3, wi: Vec3) -> Vec3:
        return Vec3.zero()  # Delta BRDF, handled in scatter

    def emitted(self, hit: HitRecord) -> Vec3:
        return Vec3.zero()


class Dielectric:
    """Glass/water material: refraction + Fresnel reflection (Schlick).

    Uses Snell's law: n1 sin θ1 = n2 sin θ2
    At each bounce either reflects or refracts based on Fresnel coefficient.
    """

    def __init__(self, ior: float = 1.5):
        self.ior = ior
        self.is_specular = True

    def scatter(self, ray_in: Ray, hit: HitRecord):
        attenuation = Vec3(1.0, 1.0, 1.0)
        ni_over_nt = (1.0 / self.ior) if hit.front_face else self.ior

        unit_dir = ray_in.direction.normalize()
        cos_theta = min(-unit_dir.dot(hit.normal), 1.0)
        sin_theta = math.sqrt(max(0.0, 1.0 - cos_theta * cos_theta))

        # Total internal reflection check
        must_reflect = ni_over_nt * sin_theta > 1.0
        fresnel = schlick(cos_theta, ni_over_nt)

        if must_reflect or random.random() < fresnel:
            direction = reflect(unit_dir, hit.normal)
        else:
            direction = refract(unit_dir, hit.normal, ni_over_nt)
            if direction is None:
                direction = reflect(unit_dir, hit.normal)

        scattered = Ray(hit.point, direction)
        return attenuation, scattered, 1.0, True

    def pdf(self, hit: HitRecord, direction: Vec3) -> float:
        return 0.0

    def brdf(self, hit: HitRecord, wo: Vec3, wi: Vec3) -> Vec3:
        return Vec3.zero()

    def emitted(self, hit: HitRecord) -> Vec3:
        return Vec3.zero()


class Emissive:
    """Uniformly emitting area-light material."""

    def __init__(self, color: Vec3, strength: float = 1.0):
        self.color = color
        self.strength = strength
        self.emission = Vec3(color.x * strength, color.y * strength, color.z * strength)
        self.is_specular = False

    def scatter(self, ray_in: Ray, hit: HitRecord):
        return None  # Lights don't scatter

    def pdf(self, hit: HitRecord, direction: Vec3) -> float:
        return 0.0

    def brdf(self, hit: HitRecord, wo: Vec3, wi: Vec3) -> Vec3:
        return Vec3.zero()

    def emitted(self, hit: HitRecord) -> Vec3:
        if hit.front_face:
            return self.emission
        return Vec3.zero()


class Checkerboard:
    """Procedural checkerboard diffuse material."""

    def __init__(self, color_a: Vec3, color_b: Vec3, scale: float = 1.0):
        self.color_a = color_a
        self.color_b = color_b
        self.scale = scale
        self.is_specular = False

    def _albedo(self, hit: HitRecord) -> Vec3:
        x = int(math.floor(hit.point.x * self.scale))
        y = int(math.floor(hit.point.y * self.scale))
        z = int(math.floor(hit.point.z * self.scale))
        return self.color_a if (x + y + z) % 2 == 0 else self.color_b

    def scatter(self, ray_in: Ray, hit: HitRecord):
        direction = Vec3.random_cosine_hemisphere(hit.normal)
        if direction.near_zero():
            direction = hit.normal
        cos_theta = max(0.0, direction.dot(hit.normal))
        pdf = cos_theta / math.pi
        if pdf < 1e-10:
            return None
        scattered = Ray(hit.point, direction)
        albedo = self._albedo(hit)
        return albedo, scattered, pdf, False

    def pdf(self, hit: HitRecord, direction: Vec3) -> float:
        cos_theta = direction.normalize().dot(hit.normal)
        return max(0.0, cos_theta / math.pi)

    def brdf(self, hit: HitRecord, wo: Vec3, wi: Vec3) -> Vec3:
        return self._albedo(hit) / math.pi

    def emitted(self, hit: HitRecord) -> Vec3:
        return Vec3.zero()


# ── Factory ────────────────────────────────────────────────────────────────────

def make_material(spec: dict):
    """Create a material from a JSON-like dict."""
    t = spec.get('type', 'lambertian')

    def rgb(key, default=(1, 1, 1)):
        v = spec.get(key, default)
        return Vec3(v[0], v[1], v[2])

    if t == 'lambertian':
        return Lambertian(rgb('albedo', (0.7, 0.7, 0.7)))
    if t == 'metal':
        return Metal(rgb('albedo', (0.8, 0.8, 0.8)), spec.get('fuzz', 0.0))
    if t == 'dielectric':
        return Dielectric(spec.get('ior', 1.5))
    if t == 'emissive':
        return Emissive(rgb('color', (1, 1, 1)), spec.get('strength', 1.0))
    if t == 'checkerboard':
        return Checkerboard(rgb('color_a', (0.9, 0.9, 0.9)),
                            rgb('color_b', (0.1, 0.1, 0.1)),
                            spec.get('scale', 1.0))
    raise ValueError(f"Unknown material type: {t!r}")
