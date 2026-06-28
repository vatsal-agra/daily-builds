"""Blinn-Phong fragment shader + shadow map sampler."""
import math
from .math3d import Vec3


class Light:
    def __init__(self, pos_or_dir, color=None, intensity=1.0,
                 kind='point', attenuation=(1.0, 0.1, 0.01)):
        # kind: 'point', 'directional', 'spot'
        self.kind        = kind
        self.pos_or_dir  = pos_or_dir   # world space
        self.color       = color or Vec3(1.0, 1.0, 1.0)
        self.intensity   = intensity
        self.attenuation = attenuation  # (c, l, q)

    @staticmethod
    def point(pos, color=None, intensity=1.0):
        return Light(pos, color, intensity, 'point', (1.0, 0.05, 0.01))

    @staticmethod
    def directional(direction, color=None, intensity=1.0):
        return Light(direction.normalize(), color, intensity, 'directional', (1,0,0))

    @staticmethod
    def ambient(color=None, intensity=0.15):
        return Light(Vec3(0,1,0), color or Vec3(1,1,1), intensity, 'ambient', (1,0,0))


def blinn_phong(pos_view, normal_view, uv, material,
                lights_view, shadow_factor=1.0):
    """
    Compute Blinn-Phong radiance at a fragment.
    All positions/directions in view (camera) space.
    Returns Vec3 RGB color (linear, not gamma-corrected).
    """
    N = normal_view.normalize()
    # Direction to camera in view space is just (0,0,0) - pos_view → -pos_view
    V = (-pos_view).normalize()

    # Sample texture if present
    tex_color = Vec3(1.0, 1.0, 1.0)
    if material.texture is not None:
        tr, tg, tb = material.texture.sample(uv[0], uv[1])
        tex_color = Vec3(tr, tg, tb)

    diff_color = material.diffuse * tex_color
    spec_color = material.specular

    result = Vec3.zero()

    for light in lights_view:
        lc = light.color * light.intensity
        if light.kind == 'ambient':
            result = result + material.ambient * tex_color * lc
            continue

        if light.kind == 'directional':
            L = (-light.pos_or_dir).normalize()
            atten = 1.0
        else:  # point
            to_light = light.pos_or_dir - pos_view
            dist = to_light.length()
            L = to_light / (dist + 1e-9)
            c, l, q = light.attenuation
            atten = 1.0 / (c + l*dist + q*dist*dist)
            atten = min(atten, 10.0)

        NdotL = max(0.0, N.dot(L))
        H = (L + V).normalize()
        NdotH = max(0.0, N.dot(H))

        diffuse  = diff_color * (NdotL * atten)
        specular = spec_color * (pow(NdotH, material.shininess) * atten * NdotL)

        result = result + (diffuse + specular) * lc

    result = result * shadow_factor
    return result


def sample_shadow_pcf(shadow_map, light_proj_pos, bias=0.002, kernel=3):
    """
    PCF shadow sampling. light_proj_pos is NDC coords from light camera.
    Returns shadow_factor ∈ [0,1] (0=full shadow, 1=fully lit).
    """
    if shadow_map is None:
        return 1.0

    # NDC → shadow map UV
    su = light_proj_pos.x * 0.5 + 0.5
    sv = light_proj_pos.y * 0.5 + 0.5
    sz = light_proj_pos.z

    # Check if outside shadow map frustum
    if su < 0 or su > 1 or sv < 0 or sv > 1:
        return 1.0

    sx = su * shadow_map.width
    sy = (1.0-sv) * shadow_map.height

    half = kernel // 2
    lit = 0; total = 0
    for dy in range(-half, half+1):
        for dx in range(-half, half+1):
            px = int(sx + dx)
            py = int(sy + dy)
            if 0 <= px < shadow_map.width and 0 <= py < shadow_map.height:
                stored_depth = shadow_map.get(px, py)
                if stored_depth == float('inf'):
                    lit += 1
                elif sz - bias <= stored_depth:
                    lit += 1
                total += 1
    return lit / total if total > 0 else 1.0
