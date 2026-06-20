"""Whitted-style recursive ray tracer with Phong shading, reflections, refractions."""
from .vec3 import Vec3
from .ray import Ray
from .materials import HitRecord, Phong, Metal, Dielectric, Emissive
from .lights import AreaLight


_BLACK = Vec3(0, 0, 0)


def trace_whitted(ray, world, lights, sky_colour, depth=0, max_depth=8):
    """
    Recursive Whitted ray tracer.
    Returns a Vec3 colour for the ray.
    """
    if depth >= max_depth:
        return _BLACK

    rec = HitRecord()
    if not world.hit(ray, 0.001, 1e9, rec):
        # Sky / background
        return _sky(ray, sky_colour)

    mat = rec.material

    # Emissive surfaces glow
    emitted = mat.emitted(rec.u, rec.v, rec.p)

    # Phong materials: full Phong shading + recursive specular reflection
    if isinstance(mat, Phong):
        colour = mat.shade(ray, rec, lights, world)
        # Specular reflection component (treated as a chrome tint)
        refl_dir = ray.direction.unit().reflect(rec.normal)
        refl_ray = Ray(rec.p, refl_dir)
        reflect_col = trace_whitted(refl_ray, world, lights, sky_colour,
                                    depth + 1, max_depth)
        k = mat.shininess / (mat.shininess + 64.0)   # blend factor
        colour = colour * (1 - k * 0.3) + reflect_col * mat.specular * (k * 0.3)
        return colour + emitted

    # Metal — scatter, attenuate, recurse
    if isinstance(mat, Metal):
        result = mat.scatter(ray, rec)
        if result is None:
            return emitted
        bounced = trace_whitted(result.ray, world, lights, sky_colour,
                                depth + 1, max_depth)
        return result.attenuation * bounced + emitted

    # Dielectric — scatter (reflect or refract), recurse
    if isinstance(mat, Dielectric):
        result = mat.scatter(ray, rec)
        if result is None:
            return emitted
        bounced = trace_whitted(result.ray, world, lights, sky_colour,
                                depth + 1, max_depth)
        return result.attenuation * bounced + emitted

    # Emissive only (no scatter)
    if isinstance(mat, Emissive):
        return emitted

    # Lambertian / generic — simple diffuse with shadow rays to all lights
    colour = _lambertian_shade(rec, lights, world)
    return colour + emitted


def _lambertian_shade(rec, lights, world):
    """Simple direct-only Lambertian shading for non-Phong diffuse materials."""
    albedo = getattr(rec.material, 'albedo', Vec3(0.5, 0.5, 0.5))
    colour = albedo * 0.05   # ambient

    for light in lights:
        if isinstance(light, AreaLight):
            n = light.samples
            lit_frac = 0.0
            total_contrib = Vec3(0, 0, 0)
            for L, dist in light.sample_directions(rec.p):
                shadow_rec = HitRecord()
                shadowed = world.hit(Ray(rec.p, L), 0.001, dist - 0.001, shadow_rec)
                if not shadowed:
                    ndl = max(0.0, rec.normal.dot(L))
                    total_contrib += light.colour * (light.intensity * ndl)
                    lit_frac += 1.0
            count = n * n
            colour = colour + albedo * (total_contrib / count)
        else:
            L, dist = light.direction_and_distance(rec.p)
            shadow_rec = HitRecord()
            shadowed = world.hit(Ray(rec.p, L), 0.001, dist - 0.001, shadow_rec)
            if not shadowed:
                ndl = max(0.0, rec.normal.dot(L))
                colour = colour + albedo * light.colour * (light.intensity * ndl)

    return colour.clamp()


def _sky(ray, sky_colour):
    if sky_colour is None:
        t = 0.5 * (ray.direction.unit().y + 1.0)
        return Vec3(1, 1, 1) * (1 - t) + Vec3(0.5, 0.7, 1.0) * t
    return sky_colour
