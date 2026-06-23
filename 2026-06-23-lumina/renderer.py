"""Monte Carlo path tracing integrator for Lumina.

Core algorithm:
  trace(ray, scene, depth) -> Vec3 radiance

Variants:
  trace_simple  — pure path tracing (always correct, higher variance)
  trace_nee     — path tracing + Next-Event Estimation with MIS balance heuristic
                  (dramatically lower variance for scenes with area lights)

NEE/MIS explanation:
  At each diffuse bounce we explicitly sample a random point on a light source
  and test visibility (shadow ray). We combine this with the BRDF sample using
  the balance heuristic:
    w_light = p_light / (p_light + p_brdf)
    w_brdf  = p_brdf  / (p_light + p_brdf)
  To avoid double counting, emitted light is only included when hitting a
  surface after a specular bounce (Metal/Dielectric) or on the first camera ray.
"""
import math
import random
from vec3 import Vec3, Ray, INF
from scene import Scene, Camera


# ── Simple path tracer ────────────────────────────────────────────────────────

def trace_simple(ray: Ray, scene: Scene, max_depth: int) -> Vec3:
    """Unbiased Monte Carlo path tracer (high variance on small lights)."""
    result = Vec3(0.0, 0.0, 0.0)
    throughput = Vec3(1.0, 1.0, 1.0)

    for depth in range(max_depth):
        hit = scene.hit(ray, 1e-4, INF)
        if hit is None:
            bg = scene.background(ray)
            result = Vec3(result.x + throughput.x * bg.x,
                          result.y + throughput.y * bg.y,
                          result.z + throughput.z * bg.z)
            break

        # Add emitted light (all bounces)
        emitted = hit.material.emitted(hit)
        result = Vec3(result.x + throughput.x * emitted.x,
                      result.y + throughput.y * emitted.y,
                      result.z + throughput.z * emitted.z)

        scatter = hit.material.scatter(ray, hit)
        if scatter is None:
            break  # Absorbed or pure light source

        attenuation, scattered, _pdf, is_specular = scatter

        # attenuation is the pre-computed Monte Carlo weight f_r*cos(θ)/pdf.
        # For Lambertian this equals albedo; for Metal/Dielectric it's the
        # reflectance. No further division by pdf needed here.
        throughput = Vec3(throughput.x * attenuation.x,
                          throughput.y * attenuation.y,
                          throughput.z * attenuation.z)

        # Russian Roulette after depth 3
        if depth >= 3:
            p = max(throughput.x, throughput.y, throughput.z)
            p = max(0.05, min(p, 0.95))
            if random.random() > p:
                break
            throughput = Vec3(throughput.x / p, throughput.y / p, throughput.z / p)

        ray = scattered

    return result


# ── NEE + MIS path tracer ─────────────────────────────────────────────────────

def trace_nee(ray: Ray, scene: Scene, max_depth: int) -> Vec3:
    """Path tracer with Next-Event Estimation and MIS balance heuristic.

    Dramatically reduces variance for scenes with area lights by explicitly
    sampling lights at every diffuse bounce instead of waiting for the BRDF
    sample to randomly hit them.
    """
    result = Vec3(0.0, 0.0, 0.0)
    throughput = Vec3(1.0, 1.0, 1.0)
    prev_specular = True  # Camera ray counts as specular for emitted term

    for depth in range(max_depth):
        hit = scene.hit(ray, 1e-4, INF)
        if hit is None:
            bg = scene.background(ray)
            result = Vec3(result.x + throughput.x * bg.x,
                          result.y + throughput.y * bg.y,
                          result.z + throughput.z * bg.z)
            break

        # Emitted: only include if previous bounce was specular (delta function)
        # or this is the very first hit from the camera.
        # For diffuse bounces, emitted is already counted via NEE.
        if prev_specular:
            emitted = hit.material.emitted(hit)
            result = Vec3(result.x + throughput.x * emitted.x,
                          result.y + throughput.y * emitted.y,
                          result.z + throughput.z * emitted.z)

        scatter = hit.material.scatter(ray, hit)
        if scatter is None:
            break

        attenuation, scattered, _pdf, is_specular = scatter

        # NEE: explicit direct light sampling (only for non-specular surfaces)
        if not is_specular and scene.emissives:
            direct = _direct_light(hit, scene)
            result = Vec3(result.x + throughput.x * direct.x,
                          result.y + throughput.y * direct.y,
                          result.z + throughput.z * direct.z)

        # Update throughput: attenuation is pre-computed weight (f_r*cos/pdf).
        throughput = Vec3(throughput.x * attenuation.x,
                          throughput.y * attenuation.y,
                          throughput.z * attenuation.z)

        # Russian Roulette after depth 3
        if depth >= 3:
            p = max(throughput.x, throughput.y, throughput.z)
            p = max(0.05, min(p, 0.95))
            if random.random() > p:
                break
            throughput = Vec3(throughput.x / p, throughput.y / p, throughput.z / p)

        prev_specular = is_specular
        ray = scattered

    return result


def _direct_light(hit, scene: Scene) -> Vec3:
    """Sample a light and return the MIS-weighted direct contribution."""
    sample = scene.sample_light(hit.point)
    if sample is None:
        return Vec3.zero()
    light_point, light_dir, light_dist, emission, light_pdf = sample
    if light_pdf < 1e-12:
        return Vec3.zero()

    # Shadow ray — test visibility to the light point
    shadow_origin = hit.point
    shadow_ray = Ray(shadow_origin, light_dir)
    # t_max slightly less than the light distance to avoid self-intersection
    shadow_hit = scene.hit(shadow_ray, 1e-4, light_dist - 1e-3)
    if shadow_hit is not None:
        return Vec3.zero()  # Occluded

    # BRDF value and PDF at this direction
    mat = hit.material
    brdf_val = mat.brdf(hit, -hit.normal, light_dir)  # f_r(ω_i, ω_o)
    mat_pdf = mat.pdf(hit, light_dir)

    cos_theta = max(0.0, light_dir.dot(hit.normal))
    if cos_theta < 1e-8:
        return Vec3.zero()

    # MIS balance heuristic weight for light sample
    w_light = light_pdf / (light_pdf + mat_pdf) if (light_pdf + mat_pdf) > 1e-12 else 1.0

    # Direct contribution: L_e * f_r * cos(θ) * w_mis / p_light
    factor = cos_theta * w_light / light_pdf
    return Vec3(emission.x * brdf_val.x * factor,
                emission.y * brdf_val.y * factor,
                emission.z * brdf_val.z * factor)


# ── Render function ───────────────────────────────────────────────────────────

def render(scene: Scene, camera: Camera,
           width: int, height: int,
           samples_per_pixel: int,
           max_depth: int = 8,
           use_nee: bool = True,
           progress_cb=None) -> list:
    """Render a scene and return a flat list of Vec3 pixel values (linear).

    Returns: list of Vec3, len = width * height, row-major top-to-bottom.
    """
    tracer = trace_nee if use_nee else trace_simple
    inv_spp = 1.0 / samples_per_pixel
    pixels = []

    for j in range(height - 1, -1, -1):
        if progress_cb:
            progress_cb(height - 1 - j, height)
        row = []
        for i in range(width):
            r_acc = g_acc = b_acc = 0.0
            for _ in range(samples_per_pixel):
                u = (i + random.random()) / (width - 1)
                v = (j + random.random()) / (height - 1)
                ray = camera.get_ray(u, v)
                c = tracer(ray, scene, max_depth)
                r_acc += c.x
                g_acc += c.y
                b_acc += c.z
            row.append(Vec3(r_acc * inv_spp, g_acc * inv_spp, b_acc * inv_spp))
        pixels.extend(row)

    return pixels
