"""Camera: view + projection matrices, viewport transform."""
import math
from .math3d import Vec3, Vec4, Mat4


class Camera:
    def __init__(self, eye=None, center=None, up=None,
                 fov_y=60.0, aspect=1.0, near=0.1, far=100.0,
                 width=512, height=512):
        self.eye    = eye    or Vec3(0, 2, 5)
        self.center = center or Vec3(0, 0, 0)
        self.up     = up     or Vec3(0, 1, 0)
        self.fov_y  = fov_y
        self.aspect = aspect
        self.near   = near
        self.far    = far
        self.width  = width
        self.height = height

    @property
    def view_matrix(self):
        return Mat4.look_at(self.eye, self.center, self.up)

    @property
    def proj_matrix(self):
        return Mat4.perspective(
            math.radians(self.fov_y), self.aspect, self.near, self.far)

    @property
    def vp_matrix(self):
        """View × Projection (clip space from world space)."""
        return self.proj_matrix * self.view_matrix

    def world_to_clip(self, pos_world):
        """Transform world-space Vec3 to clip-space Vec4."""
        return self.vp_matrix * Vec4.from_vec3(pos_world)

    def clip_to_ndc(self, clip):
        """Perspective divide Vec4 → NDC Vec3 (x,y ∈ [-1,1], z ∈ [-1,1])."""
        return clip.to_vec3_div()

    def ndc_to_screen(self, ndc):
        """NDC → pixel coords (x,y integers, z kept for depth)."""
        sx = (ndc.x * 0.5 + 0.5) * self.width
        sy = (1.0 - (ndc.y * 0.5 + 0.5)) * self.height  # flip Y
        return sx, sy, ndc.z


class LightCamera(Camera):
    """Orthographic or perspective camera used to render a shadow map."""
    def __init__(self, eye, center, up=None,
                 ortho=True, ortho_size=6.0,
                 fov_y=60.0, near=0.1, far=50.0,
                 width=512, height=512):
        super().__init__(eye=eye, center=center, up=up or Vec3(0,1,0),
                         fov_y=fov_y, aspect=1.0, near=near, far=far,
                         width=width, height=height)
        self.ortho = ortho
        self.ortho_size = ortho_size

    @property
    def proj_matrix(self):
        if self.ortho:
            s = self.ortho_size
            return Mat4.orthographic(-s, s, -s, s, self.near, self.far)
        return super().proj_matrix
