"""Scene definition and JSON loader."""
import json
import math

from .vec3 import Vec3
from .ray import Ray
from .textures import SolidTexture, CheckerTexture, PerlinTexture
from .materials import Lambertian, Metal, Dielectric, DiffuseLight
from .shapes import Sphere, Box, Plane, Triangle, HittableList
from .bvh import build_bvh
from .camera import Camera


class Scene:
    """Holds world geometry + camera + background."""

    def __init__(self, world, camera, background, width, height, spp, max_depth):
        self.world = world
        self.camera = camera
        self.background = background   # callable(ray) -> Vec3
        self.width = width
        self.height = height
        self.spp = spp
        self.max_depth = max_depth


# ---- background helpers ----

def _gradient_bg(top_color, bottom_color):
    top = Vec3(*top_color)
    bot = Vec3(*bottom_color)

    def bg(ray):
        t = 0.5 * (ray.direction.normalize().y + 1.0)
        return bot * (1.0 - t) + top * t

    return bg


def _solid_bg(color):
    c = Vec3(*color)

    def bg(ray):
        return c

    return bg


def _black_bg():
    def bg(ray):
        return Vec3(0, 0, 0)
    return bg


# ---- JSON loader ----

def load_scene(path_or_dict):
    """Load a Scene from a JSON file path or a pre-parsed dict."""
    if isinstance(path_or_dict, str):
        with open(path_or_dict) as f:
            data = json.load(f)
    else:
        data = path_or_dict

    # Camera
    cam_data = data.get('camera', {})
    look_from = Vec3(*cam_data.get('look_from', [0, 0, 0]))
    look_at   = Vec3(*cam_data.get('look_at',   [0, 0, -1]))
    up        = Vec3(*cam_data.get('up',         [0, 1, 0]))
    vfov      = cam_data.get('vfov', 90.0)
    aperture  = cam_data.get('aperture', 0.0)
    focus_dist = cam_data.get('focus_dist', None)

    width  = max(1, int(data.get('width',  400)))
    height = max(1, int(data.get('height', 225)))
    spp    = max(1, int(data.get('spp',    64)))
    max_depth = max(1, int(data.get('max_depth', 10)))

    aspect = width / height
    camera = Camera(look_from, look_at, up, vfov, aspect, aperture, focus_dist)

    # Background
    bg_data = data.get('background', {'type': 'gradient',
                                       'top': [0.5, 0.7, 1.0],
                                       'bottom': [1.0, 1.0, 1.0]})
    bg_type = bg_data.get('type', 'gradient')
    if bg_type == 'gradient':
        background = _gradient_bg(bg_data.get('top', [0.5, 0.7, 1.0]),
                                   bg_data.get('bottom', [1.0, 1.0, 1.0]))
    elif bg_type == 'solid':
        background = _solid_bg(bg_data.get('color', [0, 0, 0]))
    else:
        background = _black_bg()

    # Objects
    objects = []
    for obj_data in data.get('objects', []):
        obj = _parse_object(obj_data)
        if obj is not None:
            objects.append(obj)

    use_bvh = data.get('bvh', True)
    world = build_bvh(objects) if use_bvh and objects else HittableList(objects)

    return Scene(world, camera, background, width, height, spp, max_depth)


def _parse_texture(t_data):
    if t_data is None:
        return SolidTexture(Vec3(0.8, 0.8, 0.8))
    if isinstance(t_data, (list, tuple)):
        return SolidTexture(Vec3(*t_data))
    kind = t_data.get('type', 'solid')
    if kind == 'solid':
        return SolidTexture(Vec3(*t_data.get('color', [0.8, 0.8, 0.8])))
    if kind == 'checker':
        even = _parse_texture(t_data.get('even', [1, 1, 1]))
        odd  = _parse_texture(t_data.get('odd',  [0, 0, 0]))
        scale = t_data.get('scale', 10.0)
        return CheckerTexture(even, odd, scale)
    if kind == 'perlin':
        c1 = Vec3(*t_data.get('color1', [1, 1, 1]))
        c2 = Vec3(*t_data.get('color2', [0, 0, 0]))
        scale = t_data.get('scale', 4.0)
        seed  = t_data.get('seed', 42)
        return PerlinTexture(c1, c2, scale, seed)
    return SolidTexture(Vec3(0.8, 0.8, 0.8))


def _parse_material(m_data):
    if m_data is None:
        return Lambertian(Vec3(0.8, 0.8, 0.8))
    kind = m_data.get('type', 'lambertian')
    if kind == 'lambertian':
        albedo = _parse_texture(m_data.get('albedo'))
        return Lambertian(albedo)
    if kind == 'metal':
        albedo = _parse_texture(m_data.get('albedo'))
        roughness = m_data.get('roughness', 0.0)
        return Metal(albedo, roughness)
    if kind == 'dielectric':
        ior = m_data.get('ior', 1.5)
        return Dielectric(ior)
    if kind == 'diffuse_light':
        color = m_data.get('color', [1, 1, 1])
        intensity = m_data.get('intensity', 1.0)
        return DiffuseLight(Vec3(*color), intensity)
    return Lambertian(Vec3(0.8, 0.8, 0.8))


def _parse_object(obj_data):
    kind = obj_data.get('type')
    mat = _parse_material(obj_data.get('material'))

    if kind == 'sphere':
        c = Vec3(*obj_data['center'])
        r = obj_data.get('radius', 1.0)
        return Sphere(c, r, mat)

    if kind == 'box':
        mn = Vec3(*obj_data['p_min'])
        mx = Vec3(*obj_data['p_max'])
        return Box(mn, mx, mat)

    if kind == 'plane':
        normal = Vec3(*obj_data.get('normal', [0, 1, 0]))
        offset = obj_data.get('offset', 0.0)
        return Plane(normal, offset, mat)

    if kind == 'triangle':
        v0 = Vec3(*obj_data['v0'])
        v1 = Vec3(*obj_data['v1'])
        v2 = Vec3(*obj_data['v2'])
        return Triangle(v0, v1, v2, mat)

    return None
