"""Monte Carlo path tracing integrator for Lumina.

Core algorithm:
  trace(ray, scene, depth) -> Vec3 radiance

Variants:
  trace_simple  — pure path tracing (unbiased, higher variance on small lights)
  trace_nee     — path tracing + Next-Event Estimation with full MIS balance heuristic

NEE/MIS explanation:
  At each diffuse bounce we:
    1. Explicitly sample a light source (NEE) and test visibility, weight by w_light
    2. Also track whether the BRDF-sampled ray subsequently hits a light, weight by w_brdf
  MIS balance heuristic:
    w_light = p_light / (p_light + p_brdf)
    w_brdf  = p_brdf  / (p_brdf  + p_light)
  This is UNBIASED and handles blocked shadow rays correctly — the BRDF sample
  captures the contribution when NEE is blocked by geometry.

  Emitted light is included via MIS at every bounce; for specular bounces (delta
  BSDF), the full emitted is included since no NEE is possible.
"""
import math
import random
from vec3 import Vec3, Ray, INF
from scene import Scene, Camera


# ── Simple path tracer ────────────────────────────────────────────────────────

def trace_simple(ray: Ray, scene: Scene, max_depth: int) -> Vec3:
    """Unbiased Monte Carlo path tracer. Higher variance on small/bright lights."""
    result_r = result_g = result_b = 0.0
    tp_r = tp_g = tp_b = 1.0

    for depth in range(max_depth):
        hit = scene.hit(ray, 1e-4, INF)
        if hit is None:
            bg = scene.background(ray)
            result_r += tp_r * bg.x
            result_g += tp_g * bg.y
            result_b += tp_b * bg.z
            break

        em = hit.material.emitted(hit)
        result_r += tp_r * em.x
        result_g += tp_g * em.y
        result_b += tp_b * em.z

        scatter = hit.material.scatter(ray, hit)
        if scatter is None:
            break

        atten, scattered, _pdf, _spec = scatter
        tp_r *= atten.x
        tp_g *= atten.y
        tp_b *= atten.z

        # Russian Roulette after depth 3
        if depth >= 3:
            p = max(0.05, min(0.95, max(tp_r, tp_g, tp_b)))
            if random.random() > p:
                break
            inv_p = 1.0 / p
            tp_r *= inv_p; tp_g *= inv_p; tp_b *= inv_p

        ray = scattered

    return Vec3(result_r, result_g, result_b)


# ── NEE + full MIS path tracer ────────────────────────────────────────────────

def trace_nee(ray: Ray, scene: Scene, max_depth: int) -> Vec3:
    """Path tracer with NEE and full MIS balance heuristic (unbiased).

    Tracks the BRDF PDF of each scattered direction so that when the BRDF ray
    subsequently hits an emissive, the MIS weight w_brdf = p_brdf/(p_brdf+p_light)
    is computed correctly. This ensures correctness even when NEE shadow rays are
    blocked by geometry.
    """
    result_r = result_g = result_b = 0.0
    tp_r = tp_g = tp_b = 1.0
    # PDF used to generate the current ray (-1 = camera/specular, i.e. delta BSDF)
    prev_pdf = -1.0

    for depth in range(max_depth):
        hit = scene.hit(ray, 1e-4, INF)
        if hit is None:
            bg = scene.background(ray)
            result_r += tp_r * bg.x
            result_g += tp_g * bg.y
            result_b += tp_b * bg.z
            break

        em = hit.material.emitted(hit)
        if em.x > 0 or em.y > 0 or em.z > 0:
            # Compute MIS weight for the BRDF sample (or 1.0 for specular/camera)
            if prev_pdf < 0:
                w = 1.0  # Camera ray or after specular bounce: full weight
            else:
                # MIS: w_brdf = p_brdf / (p_brdf + p_light)
                lp = _light_pdf_at_hit(hit, ray, scene)
                w = prev_pdf / (prev_pdf + lp) if (prev_pdf + lp) > 1e-12 else 1.0
            result_r += tp_r * em.x * w
            result_g += tp_g * em.y * w
            result_b += tp_b * em.z * w

        scatter = hit.material.scatter(ray, hit)
        if scatter is None:
            break

        atten, scattered, _pdf, is_specular = scatter

        # NEE: explicit direct light sampling for non-specular surfaces
        if not is_specular and scene.emissives:
            dr, dg, db = _direct_light_rgb(hit, scene)
            result_r += tp_r * dr
            result_g += tp_g * dg
            result_b += tp_b * db

        tp_r *= atten.x
        tp_g *= atten.y
        tp_b *= atten.z

        # Russian Roulette after depth 3
        if depth >= 3:
            p = max(0.05, min(0.95, max(tp_r, tp_g, tp_b)))
            if random.random() > p:
                break
            inv_p = 1.0 / p
            tp_r *= inv_p; tp_g *= inv_p; tp_b *= inv_p

        # Track BRDF PDF for MIS at the next emissive hit
        if is_specular:
            prev_pdf = -1.0  # Delta BSDF → use full weight for any emissive hit
        else:
            prev_pdf = hit.material.pdf(hit, scattered.direction)

        ray = scattered

    return Vec3(result_r, result_g, result_b)


def _light_pdf_at_hit(hit, incoming_ray: Ray, scene: Scene) -> float:
    """Estimate the NEE PDF for having sampled the current hit direction from the
    previous surface. Used for MIS weighting of BRDF-sampled rays hitting lights.

    PDF_solid_angle = dist² / (cos_light × area × n_lights)
    """
    mat = hit.material
    area = getattr(mat, '_sample_area', 0.0)
    if area <= 0:
        return 0.0  # Light not in the NEE pool
    n_lights = getattr(mat, '_n_lights', 1)
    d = incoming_ray.direction.normalize()
    cos_light = abs((-d).dot(hit.normal))
    if cos_light < 1e-8:
        return 0.0
    # Distance from ray origin to hit point
    dist_sq = (hit.point - incoming_ray.origin).length_sq()
    return dist_sq / (cos_light * area * n_lights)


def _direct_light_rgb(hit, scene: Scene):
    """NEE with MIS. Returns (r, g, b) direct light contribution."""
    sample = scene.sample_light(hit.point)
    if sample is None:
        return 0.0, 0.0, 0.0
    light_point, light_dir, light_dist, emission, light_pdf = sample
    if light_pdf < 1e-12:
        return 0.0, 0.0, 0.0

    # Shadow ray
    shadow_hit = scene.hit(Ray(hit.point, light_dir), 1e-4, light_dist - 1e-3)
    if shadow_hit is not None:
        return 0.0, 0.0, 0.0

    mat = hit.material
    brdf_x, brdf_y, brdf_z = _brdf_rgb(mat, hit, light_dir)
    mat_pdf = mat.pdf(hit, light_dir)

    cos_theta = light_dir.dot(hit.normal)
    if cos_theta < 1e-8:
        return 0.0, 0.0, 0.0

    # MIS balance weight for light sample
    denom = light_pdf + mat_pdf
    w_light = light_pdf / denom if denom > 1e-12 else 1.0

    factor = cos_theta * w_light / light_pdf
    return (emission.x * brdf_x * factor,
            emission.y * brdf_y * factor,
            emission.z * brdf_z * factor)


def _brdf_rgb(mat, hit, direction):
    """Evaluate material BRDF at direction. Returns (r, g, b)."""
    b = mat.brdf(hit, -hit.normal, direction)
    return b.x, b.y, b.z


# ── Render function ───────────────────────────────────────────────────────────

def render(scene: Scene, camera: Camera,
           width: int, height: int,
           samples_per_pixel: int,
           max_depth: int = 8,
           use_nee: bool = True,
           progress_cb=None) -> list:
    """Render a scene. Returns flat list of Vec3 pixels (linear), top-to-bottom."""
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
                u = (i + random.random()) / max(width - 1, 1)
                v = (j + random.random()) / max(height - 1, 1)
                ray = camera.get_ray(u, v)
                c = tracer(ray, scene, max_depth)
                r_acc += c.x
                g_acc += c.y
                b_acc += c.z
            row.append(Vec3(r_acc * inv_spp, g_acc * inv_spp, b_acc * inv_spp))
        pixels.extend(row)

    return pixels
