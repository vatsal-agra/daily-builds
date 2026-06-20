"""JSON scene format → Scene (camera, world BVH, lights, render settings)."""
import json
import os
from .vec3 import Vec3
from .ray import Ray
from .camera import Camera
from .materials import Lambertian, Metal, Dielectric, Phong, Emissive
from .lights import PointLight, DirectionalLight, AreaLight
from .primitives import Sphere, Plane, Triangle, Quad, Box, PrimitiveList
from .bvh import build_bvh


def _v(lst):
    return Vec3(lst[0], lst[1], lst[2])


def _load_material(d):
    t = d.get('type', 'lambertian')
    if t == 'lambertian':
        return Lambertian(_v(d['albedo']))
    if t == 'metal':
        return Metal(_v(d['albedo']), d.get('fuzz', 0.0))
    if t == 'dielectric':
        return Dielectric(d.get('ior', 1.5))
    if t == 'phong':
        return Phong(
            diffuse   = _v(d['diffuse']),
            specular  = _v(d['specular']) if 'specular' in d else None,
            shininess = d.get('shininess', 32.0),
            ambient   = _v(d['ambient']) if 'ambient' in d else None,
        )
    if t == 'emissive':
        return Emissive(_v(d['colour']), d.get('strength', 1.0))
    raise ValueError(f"Unknown material type: {t!r}")


def _load_light(d):
    t = d.get('type', 'point')
    colour = _v(d['colour']) if 'colour' in d else Vec3(1, 1, 1)
    intensity = d.get('intensity', 1.0)
    if t == 'point':
        return PointLight(_v(d['position']), colour, intensity)
    if t == 'directional':
        return DirectionalLight(_v(d['direction']), colour, intensity)
    if t == 'area':
        return AreaLight(
            corner    = _v(d['corner']),
            u_vec     = _v(d['u']),
            v_vec     = _v(d['v']),
            colour    = colour,
            intensity = intensity,
            samples   = d.get('samples', 4),
        )
    raise ValueError(f"Unknown light type: {t!r}")


def _load_primitive(d, mats):
    mat = _load_material(d['material'])
    t = d['type']
    if t == 'sphere':
        return Sphere(_v(d['center']), d['radius'], mat)
    if t == 'plane':
        return Plane(_v(d['point']), _v(d['normal']), mat)
    if t == 'triangle':
        return Triangle(_v(d['v0']), _v(d['v1']), _v(d['v2']), mat)
    if t == 'quad':
        return Quad(_v(d['corner']), _v(d['u']), _v(d['v']), mat)
    if t == 'box':
        return Box(_v(d['a']), _v(d['b']), mat)
    if t == 'obj':
        from .obj_loader import load_obj
        path = d['path']
        triangles = load_obj(path, mat,
                             scale=d.get('scale', 1.0),
                             offset=_v(d['offset']) if 'offset' in d else None)
        if not triangles:
            raise ValueError(f"No triangles loaded from {path!r}")
        return build_bvh(triangles)
    raise ValueError(f"Unknown primitive type: {t!r}")


def load_scene(path_or_dict):
    """Load a scene from a JSON file path or a pre-parsed dict."""
    if isinstance(path_or_dict, str):
        with open(path_or_dict) as f:
            d = json.load(f)
    else:
        d = path_or_dict

    # Camera
    cam_d = d['camera']
    camera = Camera(
        look_from  = _v(cam_d['look_from']),
        look_at    = _v(cam_d['look_at']),
        vup        = _v(cam_d.get('vup', [0, 1, 0])),
        vfov       = cam_d.get('vfov', 40.0),
        aspect     = cam_d.get('aspect', 16.0 / 9.0),
        aperture   = cam_d.get('aperture', 0.0),
        focus_dist = cam_d.get('focus_dist', 1.0),
    )

    # Primitives → BVH
    prims = [_load_primitive(p, {}) for p in d.get('objects', [])]
    if len(prims) == 0:
        world = PrimitiveList()
    elif len(prims) == 1:
        world = PrimitiveList(prims)
    else:
        try:
            world = build_bvh(prims)
        except Exception:
            world = PrimitiveList(prims)

    # Lights (optional — path tracer uses emissive surfaces)
    lights = [_load_light(l) for l in d.get('lights', [])]

    # Render settings
    rs = d.get('render', {})
    settings = {
        'width':   rs.get('width',   400),
        'height':  rs.get('height',  225),
        'samples': rs.get('samples', 16),
        'mode':    rs.get('mode',    'path'),      # 'path' or 'whitted'
        'max_depth': rs.get('max_depth', 12),
        'tonemap': rs.get('tonemap', 'aces'),
        'sky': _v(rs['sky']) if 'sky' in rs else None,
    }
    return camera, world, lights, settings
