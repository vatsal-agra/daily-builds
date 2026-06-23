"""Scene description, camera model, and preset scenes for Lumina.

Camera:
  Perspective pinhole with optional thin-lens depth of field.
  Generates primary rays given (pixel_x, pixel_y) with anti-aliasing jitter.

Scene:
  Holds a BVH over all primitives plus a list of emissive objects for NEE.
  Supports JSON loading and Python dict presets.
"""
import math
import random
import json
from vec3 import Vec3, Ray, AABB
from materials import (Lambertian, Metal, Dielectric, Emissive,
                       Checkerboard, make_material)
from geometry import (Sphere, Triangle, Plane, QuadLight,
                      BVHNode, HittableList, make_box, rotate_y)


# ── Camera ────────────────────────────────────────────────────────────────────

class Camera:
    """Perspective camera with thin-lens depth of field."""

    def __init__(self, lookfrom: Vec3, lookat: Vec3, vup: Vec3,
                 vfov_deg: float, aspect: float,
                 aperture: float = 0.0, focus_dist: float = None):
        theta = math.radians(vfov_deg)
        h = math.tan(theta / 2.0)
        viewport_h = 2.0 * h
        viewport_w = aspect * viewport_h

        self.w = (lookfrom - lookat).normalize()       # -Z direction
        self.u = vup.cross(self.w).normalize()          # +X
        self.v = self.w.cross(self.u)                   # +Y

        if focus_dist is None:
            focus_dist = (lookfrom - lookat).length()

        self.origin = lookfrom
        self.horizontal = focus_dist * viewport_w * self.u
        self.vertical = focus_dist * viewport_h * self.v
        self.lower_left = (lookfrom
                           - self.horizontal / 2.0
                           - self.vertical / 2.0
                           - focus_dist * self.w)
        self.lens_radius = aperture / 2.0

    def get_ray(self, s: float, t: float) -> Ray:
        """Generate a ray for fractional pixel position (s, t) in [0,1]²."""
        if self.lens_radius > 0.0:
            rd = self.lens_radius * Vec3.random_in_unit_disk()
            offset = self.u * rd.x + self.v * rd.y
        else:
            offset = Vec3.zero()
        origin = self.origin + offset
        direction = (self.lower_left
                     + s * self.horizontal
                     + t * self.vertical
                     - origin)
        return Ray(origin, direction)


# ── Scene ─────────────────────────────────────────────────────────────────────

class Scene:
    """Holds all geometry, the BVH, emissive objects, and background."""

    def __init__(self, objects: list, emissives: list,
                 background_top: Vec3 = None, background_bot: Vec3 = None):
        self.emissives = emissives
        self.background_top = background_top or Vec3(0.5, 0.7, 1.0)
        self.background_bot = background_bot or Vec3(1.0, 1.0, 1.0)

        if not objects:
            self._root = HittableList()
        elif len(objects) == 1:
            self._root = objects[0]
        else:
            self._root = BVHNode(objects)

    def hit(self, ray: Ray, t_min: float = 1e-4, t_max: float = 1e30):
        return self._root.hit(ray, t_min, t_max)

    def background(self, ray: Ray) -> Vec3:
        """Gradient sky background."""
        t = 0.5 * (ray.direction.normalize().y + 1.0)
        b = self.background_bot
        top = self.background_top
        return Vec3(b.x + t * (top.x - b.x),
                    b.y + t * (top.y - b.y),
                    b.z + t * (top.z - b.z))

    def sample_light(self, surface_point: Vec3):
        """Pick a random emissive primitive, sample a point on it.

        Returns (light_point, light_normal, emission, solid_angle_pdf)
        or None if no lights.
        """
        if not self.emissives:
            return None
        light = random.choice(self.emissives)
        lp, ln, area = light.sample_point()
        to_light = lp - surface_point
        dist_sq = to_light.length_sq()
        if dist_sq < 1e-20:
            return None
        dist = math.sqrt(dist_sq)
        direction = Vec3(to_light.x / dist, to_light.y / dist, to_light.z / dist)
        cos_light = abs(ln.dot(-direction))
        if cos_light < 1e-8:
            return None
        # Solid-angle PDF = (dist² / (cos_light * area)) * (1/n_lights)
        pdf = dist_sq / (cos_light * area * len(self.emissives))
        emission = light.material.emission if hasattr(light.material, 'emission') else Vec3.zero()
        return lp, direction, dist, emission, pdf


# ── Preset scene builders ─────────────────────────────────────────────────────

def scene_spheres():
    """Classic random sphere field with glass, metal, and diffuse balls."""
    objects = []
    emissives = []

    # Ground
    ground = Lambertian(Vec3(0.5, 0.5, 0.5))
    objects.append(Sphere(Vec3(0, -1000, 0), 1000, ground))

    # Random small spheres
    rng = random.Random(42)
    for a in range(-11, 11):
        for b in range(-11, 11):
            choose = rng.random()
            cx = a + 0.9 * rng.random()
            cy = 0.2
            cz = b + 0.9 * rng.random()
            center = Vec3(cx, cy, cz)
            if (center - Vec3(4, 0.2, 0)).length() < 0.9:
                continue
            if choose < 0.8:
                albedo = Vec3(rng.random() ** 2, rng.random() ** 2, rng.random() ** 2)
                mat = Lambertian(albedo)
            elif choose < 0.95:
                albedo = Vec3(0.5 + 0.5 * rng.random(),
                              0.5 + 0.5 * rng.random(),
                              0.5 + 0.5 * rng.random())
                mat = Metal(albedo, 0.5 * rng.random())
            else:
                mat = Dielectric(1.5)
            objects.append(Sphere(center, 0.2, mat))

    # Three large hero spheres
    objects.append(Sphere(Vec3(0, 1, 0), 1.0, Dielectric(1.5)))
    objects.append(Sphere(Vec3(-4, 1, 0), 1.0,
                          Lambertian(Vec3(0.4, 0.2, 0.1))))
    objects.append(Sphere(Vec3(4, 1, 0), 1.0,
                          Metal(Vec3(0.7, 0.6, 0.5), 0.0)))

    camera = Camera(
        lookfrom=Vec3(13, 2, 3),
        lookat=Vec3(0, 0, 0),
        vup=Vec3(0, 1, 0),
        vfov_deg=20,
        aspect=16.0 / 9.0,
        aperture=0.1,
        focus_dist=10.0,
    )
    return Scene(objects, emissives), camera


def scene_cornell():
    """Classic Cornell box: two diffuse boxes under an area light."""
    objects = []
    emissives = []

    red   = Lambertian(Vec3(0.65, 0.05, 0.05))
    white = Lambertian(Vec3(0.73, 0.73, 0.73))
    green = Lambertian(Vec3(0.12, 0.45, 0.15))
    light_mat = Emissive(Vec3(1.0, 1.0, 1.0), strength=15.0)

    # Box walls (each as 2 triangles)
    W = 555  # box size

    # Floor
    objects += make_box(Vec3(0, 0, 0), Vec3(W, 1, W), white)
    # Ceiling
    objects += make_box(Vec3(0, W - 1, 0), Vec3(W, W, W), white)
    # Back wall
    objects += make_box(Vec3(0, 0, W - 1), Vec3(W, W, W), white)
    # Left wall (red)
    objects += make_box(Vec3(0, 0, 0), Vec3(1, W, W), red)
    # Right wall (green)
    objects += make_box(Vec3(W - 1, 0, 0), Vec3(W, W, W), green)

    # Area light on ceiling
    light_quad = QuadLight(
        corner=Vec3(213, W - 1, 227),
        u=Vec3(130, 0, 0),
        v=Vec3(0, 0, 105),
        material=light_mat,
    )
    objects.append(light_quad)
    emissives.append(light_quad)

    # Tall box (rotated 15° CCW when viewed from above)
    tall = make_box(Vec3(0, 0, 0), Vec3(165, 330, 165), white)
    tall = rotate_y(tall, -15.0, Vec3(0, 0, 0))
    tall = [Triangle(t.v0 + Vec3(265, 0, 295),
                     t.v1 + Vec3(265, 0, 295),
                     t.v2 + Vec3(265, 0, 295), t.material)
            for t in tall]
    objects.extend(tall)

    # Short box (rotated 18° CW)
    short = make_box(Vec3(0, 0, 0), Vec3(165, 165, 165), white)
    short = rotate_y(short, 18.0, Vec3(0, 0, 0))
    short = [Triangle(t.v0 + Vec3(130, 0, 65),
                      t.v1 + Vec3(130, 0, 65),
                      t.v2 + Vec3(130, 0, 65), t.material)
             for t in short]
    objects.extend(short)

    camera = Camera(
        lookfrom=Vec3(W / 2, W / 2, -800),
        lookat=Vec3(W / 2, W / 2, 0),
        vup=Vec3(0, 1, 0),
        vfov_deg=40,
        aspect=1.0,
    )
    bg = Vec3(0.0, 0.0, 0.0)
    return Scene(objects, emissives, background_top=bg, background_bot=bg), camera


def scene_glass():
    """Glass and metal spheres on a checkered floor, soft area light above."""
    objects = []
    emissives = []

    floor_mat = Checkerboard(Vec3(0.9, 0.9, 0.9), Vec3(0.1, 0.1, 0.1), scale=0.5)
    objects.append(Sphere(Vec3(0, -1000, 0), 1000, floor_mat))

    # Glass sphere
    objects.append(Sphere(Vec3(-1.5, 1, 0), 1.0, Dielectric(1.5)))
    # Air bubble inside glass
    objects.append(Sphere(Vec3(-1.5, 1, 0), -0.85, Dielectric(1.5)))

    # Mirror metal sphere
    objects.append(Sphere(Vec3(1.5, 1, 0), 1.0, Metal(Vec3(0.8, 0.7, 0.5), 0.0)))

    # Diffuse sphere
    objects.append(Sphere(Vec3(0, 0.5, 2.5), 0.5,
                          Lambertian(Vec3(0.9, 0.3, 0.2))))

    # Fuzzy metal
    objects.append(Sphere(Vec3(0, 0.4, -2.5), 0.4,
                          Metal(Vec3(0.5, 0.5, 0.9), 0.3)))

    # Overhead area light (wide, soft)
    light_mat = Emissive(Vec3(1.0, 0.97, 0.9), strength=6.0)
    light_quad = QuadLight(
        corner=Vec3(-3, 6, -3),
        u=Vec3(6, 0, 0),
        v=Vec3(0, 0, 6),
        material=light_mat,
    )
    objects.append(light_quad)
    emissives.append(light_quad)

    camera = Camera(
        lookfrom=Vec3(0, 3, 8),
        lookat=Vec3(0, 1, 0),
        vup=Vec3(0, 1, 0),
        vfov_deg=30,
        aspect=16.0 / 9.0,
        aperture=0.05,
        focus_dist=8.5,
    )
    bg_top = Vec3(0.1, 0.12, 0.2)
    bg_bot = Vec3(0.3, 0.3, 0.35)
    return Scene(objects, emissives, background_top=bg_top, background_bot=bg_bot), camera


def scene_showcase():
    """One of each material type on a stage, demonstrating PBR features."""
    objects = []
    emissives = []

    # Ground plane (checkerboard)
    floor_mat = Checkerboard(Vec3(0.8, 0.8, 0.8), Vec3(0.2, 0.2, 0.2), scale=0.25)
    objects.append(Sphere(Vec3(0, -1000, 0), 1000, floor_mat))

    # Back wall
    wall_mat = Lambertian(Vec3(0.2, 0.2, 0.3))
    objects.append(Sphere(Vec3(0, 0, -1010), 1000, wall_mat))

    # Lambertian diffuse — warm orange
    objects.append(Sphere(Vec3(-4, 1, 0), 1.0,
                          Lambertian(Vec3(0.9, 0.5, 0.1))))
    # Lambertian diffuse — cool blue
    objects.append(Sphere(Vec3(-2, 1, 0), 1.0,
                          Lambertian(Vec3(0.2, 0.4, 0.9))))
    # Fuzzy metal — bronze
    objects.append(Sphere(Vec3(0, 1, 0), 1.0,
                          Metal(Vec3(0.8, 0.6, 0.2), 0.15)))
    # Perfect mirror
    objects.append(Sphere(Vec3(2, 1, 0), 1.0,
                          Metal(Vec3(0.95, 0.95, 0.95), 0.0)))
    # Dielectric glass
    objects.append(Sphere(Vec3(4, 1, 0), 1.0,
                          Dielectric(1.5)))

    # Small emissive sphere (point-ish light)
    light_sphere = Sphere(Vec3(0, 5, -2), 1.0,
                          Emissive(Vec3(1.0, 0.9, 0.7), strength=8.0))
    objects.append(light_sphere)
    emissives.append(light_sphere)

    # Wide overhead quad light
    light_mat = Emissive(Vec3(1.0, 1.0, 1.0), strength=3.0)
    light_quad = QuadLight(
        corner=Vec3(-6, 8, -5),
        u=Vec3(12, 0, 0),
        v=Vec3(0, 0, 6),
        material=light_mat,
    )
    objects.append(light_quad)
    emissives.append(light_quad)

    camera = Camera(
        lookfrom=Vec3(0, 3, 12),
        lookat=Vec3(0, 1, 0),
        vup=Vec3(0, 1, 0),
        vfov_deg=35,
        aspect=16.0 / 9.0,
        aperture=0.0,
        focus_dist=12.0,
    )
    bg_top = Vec3(0.05, 0.07, 0.12)
    bg_bot = Vec3(0.15, 0.15, 0.2)
    return Scene(objects, emissives, background_top=bg_top, background_bot=bg_bot), camera


PRESETS = {
    'spheres':   scene_spheres,
    'cornell':   scene_cornell,
    'glass':     scene_glass,
    'showcase':  scene_showcase,
}


def load_scene(path: str):
    """Load a scene from a JSON file.

    JSON format:
    {
      "background_top": [r, g, b],
      "background_bot": [r, g, b],
      "camera": {
        "lookfrom": [x, y, z], "lookat": [x, y, z], "vup": [x, y, z],
        "vfov": degrees, "aspect": float, "aperture": float, "focus_dist": float
      },
      "materials": {"name": {material spec}, ...},
      "objects": [
        {"type": "sphere", "center": [x,y,z], "radius": r, "material": "name"},
        {"type": "triangle", "v0":[x,y,z], "v1":[x,y,z], "v2":[x,y,z],
         "material": "name"},
        {"type": "quad_light", "corner":[x,y,z], "u":[x,y,z], "v":[x,y,z],
         "material": "name"},
        ...
      ]
    }
    """
    with open(path) as f:
        data = json.load(f)

    def v3(lst): return Vec3(lst[0], lst[1], lst[2])

    mats = {}
    for name, spec in data.get('materials', {}).items():
        mats[name] = make_material(spec)

    objects = []
    emissives = []
    for spec in data.get('objects', []):
        mat = mats[spec['material']]
        t = spec['type']
        if t == 'sphere':
            obj = Sphere(v3(spec['center']), spec['radius'], mat)
        elif t == 'triangle':
            obj = Triangle(v3(spec['v0']), v3(spec['v1']), v3(spec['v2']), mat)
        elif t == 'quad_light':
            obj = QuadLight(v3(spec['corner']), v3(spec['u']), v3(spec['v']), mat)
        else:
            raise ValueError(f"Unknown object type: {t!r}")
        objects.append(obj)
        if isinstance(mat, Emissive):
            emissives.append(obj)

    bg_top = v3(data.get('background_top', [0.5, 0.7, 1.0]))
    bg_bot = v3(data.get('background_bot', [1.0, 1.0, 1.0]))
    scene = Scene(objects, emissives, bg_top, bg_bot)

    cam_d = data['camera']
    camera = Camera(
        lookfrom=v3(cam_d['lookfrom']),
        lookat=v3(cam_d['lookat']),
        vup=v3(cam_d.get('vup', [0, 1, 0])),
        vfov_deg=cam_d.get('vfov', 60),
        aspect=cam_d.get('aspect', 16 / 9),
        aperture=cam_d.get('aperture', 0.0),
        focus_dist=cam_d.get('focus_dist', None),
    )
    return scene, camera
