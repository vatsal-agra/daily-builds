"""
Prism test suite — 45 tests covering math, rasterization, shading, textures,
pipeline, OBJ loading, shadows, PNG encoding, and full renders.
"""
import sys, os, math, unittest, tempfile, struct, zlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.math3d import Vec3, Vec4, Mat4
from src.framebuffer import Framebuffer, DepthBuffer
from src.geometry import (Material, Vertex, Triangle, Mesh,
                           _make_sphere, _make_torus, _make_cube,
                           _make_plane, _make_cylinder, load_obj)
from src.camera import Camera, LightCamera
from src.rasterizer import RenderContext, render_mesh, render_depth, _edge
from src.shader import Light, blinn_phong, sample_shadow_pcf
from src.texture import checkerboard, marble, uv_grid, earth_like, Texture
from src.png_encoder import encode_png, save_png


# ── Helper ──

def _count_lit(fb, threshold=0.05):
    """Count pixels that are brighter than the background."""
    n = fb.rw * fb.rh
    return sum(1 for i in range(n) if fb.r[i] > threshold or fb.g[i] > threshold or fb.b[i] > threshold)


def _decode_png(data):
    """Minimal PNG decode: returns (width, height, list-of-rgb-bytes)."""
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    pos = 8
    width = height = None
    idat = b''
    while pos < len(data):
        length = struct.unpack('>I', data[pos:pos+4])[0]
        tag = data[pos+4:pos+8]
        chunk = data[pos+8:pos+8+length]
        if tag == b'IHDR':
            width, height = struct.unpack('>II', chunk[:8])
        elif tag == b'IDAT':
            idat += chunk
        pos += 4 + 4 + length + 4
    raw = zlib.decompress(idat)
    # Reconstruct RGB pixels (undo Sub filter row by row)
    row_bytes = width * 3
    rgb = []
    for y in range(height):
        ftype = raw[y*(row_bytes+1)]
        row = raw[y*(row_bytes+1)+1 : y*(row_bytes+1)+1+row_bytes]
        prev = [0]*row_bytes
        out = []
        for x in range(row_bytes):
            p = row[x]
            if ftype == 1:  # Sub
                a = out[x-3] if x >= 3 else 0
                p = (p + a) & 0xFF
            out.append(p)
        rgb.extend(out)
    return width, height, rgb


# ══════════════════════════════════════════════════════════════
# 1. Math3D Tests
# ══════════════════════════════════════════════════════════════

class TestVec3(unittest.TestCase):
    def test_add(self):
        a = Vec3(1,2,3); b = Vec3(4,5,6)
        r = a+b
        self.assertAlmostEqual(r.x, 5); self.assertAlmostEqual(r.y, 7); self.assertAlmostEqual(r.z, 9)

    def test_dot(self):
        a = Vec3(1,0,0); b = Vec3(0,1,0)
        self.assertAlmostEqual(a.dot(b), 0.0)
        self.assertAlmostEqual(a.dot(a), 1.0)

    def test_cross(self):
        x = Vec3(1,0,0); y = Vec3(0,1,0)
        z = x.cross(y)
        self.assertAlmostEqual(z.x, 0); self.assertAlmostEqual(z.y, 0); self.assertAlmostEqual(z.z, 1)

    def test_normalize(self):
        v = Vec3(3,4,0)
        n = v.normalize()
        self.assertAlmostEqual(n.length(), 1.0, places=6)
        self.assertAlmostEqual(n.x, 0.6, places=6)

    def test_normalize_zero(self):
        """Zero vector doesn't crash — returns fallback."""
        n = Vec3(0,0,0).normalize()
        self.assertAlmostEqual(n.length(), 1.0, places=6)

    def test_lerp(self):
        a = Vec3(0,0,0); b = Vec3(10,10,10)
        m = a.lerp(b, 0.5)
        self.assertAlmostEqual(m.x, 5.0)

    def test_reflect(self):
        v = Vec3(1,-1,0).normalize()
        n = Vec3(0,1,0)
        r = v.reflect(n)
        self.assertAlmostEqual(r.x, v.x, places=5)
        self.assertAlmostEqual(r.y, -v.y, places=5)

    def test_clamp(self):
        v = Vec3(2, -1, 0.5)
        c = v.clamp(0, 1)
        self.assertEqual(c.x, 1.0); self.assertEqual(c.y, 0.0); self.assertAlmostEqual(c.z, 0.5)


class TestMat4(unittest.TestCase):
    def test_identity_mul_vec(self):
        I = Mat4.identity()
        v = Vec4(1,2,3,1)
        r = I * v
        self.assertAlmostEqual(r.x, 1); self.assertAlmostEqual(r.y, 2)
        self.assertAlmostEqual(r.z, 3); self.assertAlmostEqual(r.w, 1)

    def test_translation(self):
        T = Mat4.translation(1,2,3)
        v = Vec4(0,0,0,1)
        r = T * v
        self.assertAlmostEqual(r.x, 1); self.assertAlmostEqual(r.y, 2); self.assertAlmostEqual(r.z, 3)

    def test_rotation_y_90(self):
        R = Mat4.rotation_y(math.pi/2)
        v = Vec4(1,0,0,0)
        r = R * v
        self.assertAlmostEqual(r.x, 0, places=5)
        self.assertAlmostEqual(r.z, -1, places=5)

    def test_scale(self):
        S = Mat4.scale(2,3,4)
        v = Vec4(1,1,1,1)
        r = S * v
        self.assertAlmostEqual(r.x, 2); self.assertAlmostEqual(r.y, 3); self.assertAlmostEqual(r.z, 4)

    def test_mat_mul_identity(self):
        A = Mat4.rotation_y(0.7) * Mat4.translation(1,2,3)
        I = Mat4.identity()
        B = A * I
        for i in range(16):
            self.assertAlmostEqual(A.m[i], B.m[i], places=10)

    def test_inverse(self):
        T = Mat4.translation(1,2,3)
        Ti = T.inverse()
        I = T * Ti
        for r in range(4):
            for c in range(4):
                expected = 1.0 if r==c else 0.0
                self.assertAlmostEqual(I.get(r,c), expected, places=8)

    def test_perspective_project(self):
        P = Mat4.perspective(math.radians(90), 1.0, 0.1, 100)
        # Point at (0,0,-1) should be in front (w > 0 for the projection)
        v = P * Vec4(0,0,-1,1)
        self.assertGreater(v.w, 0)

    def test_look_at_forward(self):
        V = Mat4.look_at(Vec3(0,0,5), Vec3(0,0,0), Vec3(0,1,0))
        # The origin transformed by look_at should be at (0,0,-5) in view space
        r = V * Vec4(0,0,0,1)
        self.assertAlmostEqual(r.z, -5, places=4)

    def test_normal_matrix_preserves_perpendicularity(self):
        """After transforming by normal_matrix, a normal stays perpendicular to the surface."""
        M = Mat4.rotation_y(math.pi/4) * Mat4.scale(1,2,1)
        NM = M.normal_matrix()
        # Surface tangent in object space: (1,0,0)
        # Surface normal in object space: (0,1,0)
        tangent_world = M.transform_direction(Vec3(1,0,0))
        normal_world = NM.transform_direction(Vec3(0,1,0)).normalize()
        dot = tangent_world.dot(normal_world)
        self.assertAlmostEqual(dot, 0.0, places=5)


# ══════════════════════════════════════════════════════════════
# 2. Framebuffer Tests
# ══════════════════════════════════════════════════════════════

class TestFramebuffer(unittest.TestCase):
    def test_clear_and_read(self):
        fb = Framebuffer(4, 4)
        fb.clear((0.1, 0.2, 0.3))
        r, g, b = fb.get_pixel(0, 0)
        self.assertAlmostEqual(r, 0.1, places=5)
        self.assertAlmostEqual(g, 0.2, places=5)

    def test_set_and_get(self):
        fb = Framebuffer(4, 4)
        fb.set_pixel(2, 3, 0.9, 0.5, 0.1)
        r, g, b = fb.get_pixel(2, 3)
        self.assertAlmostEqual(r, 0.9, places=5)

    def test_depth_buffer(self):
        fb = Framebuffer(4, 4)
        self.assertTrue(fb.depth_test_and_set(0, 0, 0.5))
        self.assertFalse(fb.depth_test_and_set(0, 0, 0.6))  # farther → rejected
        self.assertTrue(fb.depth_test_and_set(0, 0, 0.4))   # closer → accepted

    def test_resolve_to_bytes_shape(self):
        fb = Framebuffer(8, 8)
        fb.clear((0.5, 0.0, 0.0))
        rgb = fb.resolve_to_rgb_bytes()
        self.assertEqual(len(rgb), 8*8*3)

    def test_msaa_resolve(self):
        fb = Framebuffer(4, 4, msaa=2)
        # Fill all super-samples with bright red
        for i in range(fb.rw * fb.rh):
            fb.r[i] = 10.0; fb.g[i] = 0.0; fb.b[i] = 0.0
        rgb = fb.resolve_to_rgb_bytes()
        # After Reinhard (10/11) ≈ 0.909 then gamma → ~0.951 * 255 ≈ 242
        self.assertGreater(rgb[0], 200)
        self.assertLess(rgb[1], 10)

    def test_depth_buffer_standalone(self):
        db = DepthBuffer(4, 4)
        db.clear()
        self.assertEqual(db.get(0,0), float('inf'))
        db.depth_test_and_set(1, 1, 0.3)
        self.assertAlmostEqual(db.get(1,1), 0.3)
        # OOB clamped
        self.assertAlmostEqual(db.get(-1, -1), db.get(0,0))


# ══════════════════════════════════════════════════════════════
# 3. Texture Tests
# ══════════════════════════════════════════════════════════════

class TestTexture(unittest.TestCase):
    def test_checkerboard_colors(self):
        tex = checkerboard(64, 64, (1,0,0), (0,0,1), tiles=4)
        # (0,0) UV corner → tile 0,0 = color_a (red)
        r, g, b = tex.sample(0.01, 0.01)
        self.assertGreater(r, 0.5)
        self.assertLess(b, 0.5)

    def test_bilinear_continuous(self):
        """Bilinear sampling should be continuous — nearby points within same tile are similar."""
        # Use tiles=2 so tile boundaries are at UV=0.5; samples at 0.1 and 0.2 are in same tile.
        tex = checkerboard(64, 64, tiles=2)
        c1 = tex.sample(0.1, 0.1)
        c2 = tex.sample(0.2, 0.2)
        diff = abs(c1[0]-c2[0]) + abs(c1[1]-c2[1]) + abs(c1[2]-c2[2])
        self.assertLess(diff, 0.5)

    def test_uv_wrapping(self):
        """UV outside [0,1] should wrap."""
        tex = checkerboard(64, 64, (1,0,0), (0,0,1), tiles=2)
        c_base = tex.sample(0.1, 0.1)
        c_wrap = tex.sample(1.1, 1.1)
        for i in range(3):
            self.assertAlmostEqual(c_base[i], c_wrap[i], places=3)

    def test_marble_range(self):
        tex = marble(32, 32)
        for y in range(32):
            for x in range(32):
                r, g, b = tex.get_pixel_raw(x, y)
                self.assertGreaterEqual(r, 0); self.assertLessEqual(r, 1)

    def test_earth_has_blue_and_green(self):
        tex = earth_like(64, 64)
        has_blue = any(tex.get_pixel_raw(x,y)[2] > 0.3 for y in range(64) for x in range(64))
        has_green = any(tex.get_pixel_raw(x,y)[1] > 0.3 for y in range(64) for x in range(64))
        self.assertTrue(has_blue)
        self.assertTrue(has_green)


# ══════════════════════════════════════════════════════════════
# 4. Geometry Tests
# ══════════════════════════════════════════════════════════════

class TestGeometry(unittest.TestCase):
    def test_sphere_triangle_count(self):
        s = _make_sphere(rings=8, sectors=8)
        # rings×sectors×2 - adjustments at poles ≈ ~112
        self.assertGreater(len(s.triangles), 50)

    def test_sphere_normals_unit(self):
        s = _make_sphere(rings=8, sectors=8)
        for tri in s.triangles:
            for v in tri.v:
                self.assertAlmostEqual(v.normal.length(), 1.0, places=4)

    def test_torus_triangle_count(self):
        t = _make_torus(rings=10, sectors=8)
        self.assertEqual(len(t.triangles), 10*8*2)

    def test_cube_triangle_count(self):
        c = _make_cube()
        self.assertEqual(len(c.triangles), 12)  # 6 faces × 2

    def test_plane_subdivisions(self):
        p = _make_plane(size=2.0, subdivisions=3)
        self.assertEqual(len(p.triangles), 3*3*2)

    def test_obj_load_simple(self):
        """Write a minimal OBJ and load it."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.obj',
                                         delete=False) as f:
            f.write("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
            path = f.name
        try:
            mesh = load_obj(path)
            self.assertEqual(len(mesh.triangles), 1)
            tri = mesh.triangles[0]
            self.assertAlmostEqual(tri.v[0].pos.x, 0)
            self.assertAlmostEqual(tri.v[1].pos.x, 1)
        finally:
            os.unlink(path)

    def test_obj_face_normal_computed(self):
        """OBJ without vn should get face normals computed."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.obj', delete=False) as f:
            f.write("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
            path = f.name
        try:
            mesh = load_obj(path)
            n = mesh.triangles[0].v[0].normal
            self.assertAlmostEqual(n.length(), 1.0, places=4)
        finally:
            os.unlink(path)

    def test_obj_quad_fan_triangulation(self):
        """Quad face → 2 triangles."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.obj', delete=False) as f:
            f.write("v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nf 1 2 3 4\n")
            path = f.name
        try:
            mesh = load_obj(path)
            self.assertEqual(len(mesh.triangles), 2)
        finally:
            os.unlink(path)

    def test_obj_nonexistent_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_obj("/tmp/does_not_exist_xyz.obj")


# ══════════════════════════════════════════════════════════════
# 5. Camera Tests
# ══════════════════════════════════════════════════════════════

class TestCamera(unittest.TestCase):
    def test_project_origin_in_center(self):
        cam = Camera(eye=Vec3(0,0,5), center=Vec3(0,0,0), fov_y=90,
                     aspect=1.0, near=0.1, far=100, width=200, height=200)
        clip = cam.world_to_clip(Vec3(0,0,0))
        ndc = cam.clip_to_ndc(clip)
        sx, sy, _ = cam.ndc_to_screen(ndc)
        self.assertAlmostEqual(sx, 100, delta=2)
        self.assertAlmostEqual(sy, 100, delta=2)

    def test_point_behind_camera_clipped(self):
        """A point behind the camera should have w < 0 in clip space."""
        cam = Camera(eye=Vec3(0,0,5), center=Vec3(0,0,0), fov_y=90,
                     aspect=1.0, near=0.1, far=100, width=200, height=200)
        from src.math3d import Vec4
        clip = cam.world_to_clip(Vec3(0,0,10))  # behind camera (at z=10 > eye z=5)
        # The clip w should be negative (behind near plane)
        # Actually for standard perspective, point behind eye has negative w
        self.assertLess(clip.w, 0)

    def test_vp_matrix_dimensions(self):
        cam = Camera()
        vp = cam.vp_matrix
        self.assertEqual(len(vp.m), 16)

    def test_light_camera_ortho(self):
        lcam = LightCamera(eye=Vec3(0,5,0), center=Vec3(0,0,0),
                           ortho=True, ortho_size=4.0, near=0.1, far=20)
        P = lcam.proj_matrix
        # Orthographic: (0,0,?) → x=0, y=0
        v = P * Vec4(0,0,-5,1)
        self.assertAlmostEqual(v.x, 0.0, places=5)
        self.assertAlmostEqual(v.y, 0.0, places=5)


# ══════════════════════════════════════════════════════════════
# 6. Shader / Lighting Tests
# ══════════════════════════════════════════════════════════════

class TestShader(unittest.TestCase):
    def test_ambient_only(self):
        mat = Material.default()
        mat.ambient = Vec3(0.5, 0.3, 0.2)
        lights = [Light.ambient(Vec3(1,1,1), intensity=1.0)]
        pos = Vec3(0,0,-1); norm = Vec3(0,0,1)
        c = blinn_phong(pos, norm, (0,0), mat, lights)
        self.assertAlmostEqual(c.x, 0.5, places=4)

    def test_diffuse_front(self):
        mat = Material.default()
        mat.diffuse = Vec3(1,0,0); mat.specular = Vec3(0,0,0)
        mat.ambient = Vec3(0,0,0)
        # Directional light: pos_or_dir is the direction the ray TRAVELS.
        # Light rays traveling in -Z → light comes from +Z side → illuminates +Z normals.
        lights = [Light(Vec3(0,0,-1), Vec3(1,1,1), 1.0, 'directional', (1,0,0))]
        pos = Vec3(0,0,-1); norm = Vec3(0,0,1)
        c = blinn_phong(pos, norm, (0,0), mat, lights)
        self.assertGreater(c.x, 0.5)  # red light hits red surface → bright

    def test_diffuse_back_is_zero(self):
        """Light from behind surface → NdotL=0 → no diffuse contribution."""
        mat = Material.default()
        mat.diffuse = Vec3(1,0,0); mat.specular = Vec3(0,0,0); mat.ambient = Vec3(0,0,0)
        # Rays traveling in +Z → light comes from -Z side → back-faces +Z normal
        lights = [Light(Vec3(0,0,1), Vec3(1,1,1), 1.0, 'directional', (1,0,0))]
        pos = Vec3(0,0,-1); norm = Vec3(0,0,1)
        c = blinn_phong(pos, norm, (0,0), mat, lights)
        self.assertAlmostEqual(c.x, 0.0, places=4)

    def test_shadow_factor_zero(self):
        """shadow_factor=0 → result ≈ 0 (only ambient survives)."""
        mat = Material.default()
        mat.ambient = Vec3(0,0,0)
        lights = [Light.point(Vec3(0,2,0), Vec3(1,1,1), 1.0)]
        pos = Vec3(0,0,0); norm = Vec3(0,1,0)
        c = blinn_phong(pos, norm, (0,0), mat, lights, shadow_factor=0.0)
        self.assertAlmostEqual(c.x + c.y + c.z, 0.0, places=4)

    def test_pcf_shadow_no_map(self):
        """No shadow map → always lit."""
        from src.math3d import Vec3
        self.assertEqual(sample_shadow_pcf(None, Vec3(0,0,0)), 1.0)

    def test_pcf_shadow_lit(self):
        """Fragment closer than stored depth → lit."""
        db = DepthBuffer(4, 4)
        db.clear()
        db.depth[0*4+0] = 0.9  # stored depth at (0,0)
        from src.math3d import Vec3
        # Fragment at NDC (0,0) with depth 0.5 (closer than 0.9)
        result = sample_shadow_pcf(db, Vec3(0,0,0.5))
        self.assertGreater(result, 0.0)

    def test_pcf_shadow_occluded(self):
        """Fragment farther than stored depth → shadow."""
        db = DepthBuffer(64, 64)
        # Fill all pixels with shallow depth
        for i in range(64*64):
            db.depth[i] = 0.2
        from src.math3d import Vec3
        # Fragment at center with depth 0.9 (farther than 0.2) → shadowed
        result = sample_shadow_pcf(db, Vec3(0,0,0.9))
        self.assertLess(result, 0.5)


# ══════════════════════════════════════════════════════════════
# 7. Rasterizer Tests
# ══════════════════════════════════════════════════════════════

class TestRasterizer(unittest.TestCase):
    def _simple_ctx(self, size=64):
        fb = Framebuffer(size, size)
        fb.clear((0,0,0))
        cam = Camera(eye=Vec3(0,0,3), center=Vec3(0,0,0), fov_y=60,
                     aspect=1.0, near=0.1, far=20, width=size, height=size)
        lights = [Light.ambient(Vec3(1,1,1), intensity=1.0),
                  Light.point(Vec3(0,5,5), Vec3(1,1,1), 5.0)]
        from src.math3d import Mat4
        # Transform lights to view space
        vm = cam.view_matrix
        view_lights = []
        for lt in lights:
            if lt.kind == 'ambient':
                view_lights.append(lt)
            else:
                vp = vm.transform_point(lt.pos_or_dir)
                view_lights.append(Light(vp, lt.color, lt.intensity, lt.kind, lt.attenuation))
        return fb, cam, view_lights

    def test_edge_function(self):
        # CCW triangle: (0,0)→(1,0)→(0,1)
        # Interior point (0.1,0.1) should pass all three edges
        e0 = _edge(0,0, 1,0, 0.1,0.1)  # edge (0,0)→(1,0), interior below → positive
        e1 = _edge(1,0, 0,1, 0.1,0.1)
        e2 = _edge(0,1, 0,0, 0.1,0.1)
        # All must agree in sign for an interior point
        self.assertEqual(e0 > 0, e1 > 0)
        self.assertEqual(e1 > 0, e2 > 0)

    def test_render_produces_lit_pixels(self):
        """Rendering a cube in front of camera produces non-black pixels."""
        fb, cam, lights = self._simple_ctx(64)
        mesh = _make_cube(size=1.0, material=Material.colored(0.8,0.2,0.2))
        from src.math3d import Mat4
        ctx = RenderContext(fb, cam, lights)
        render_mesh(ctx, mesh, Mat4.identity())
        bright = _count_lit(fb)
        self.assertGreater(bright, 100)

    def test_render_sphere_lit(self):
        fb, cam, lights = self._simple_ctx(64)
        mesh = _make_sphere(rings=8, sectors=8)
        from src.math3d import Mat4
        ctx = RenderContext(fb, cam, lights)
        render_mesh(ctx, mesh, Mat4.identity())
        self.assertGreater(_count_lit(fb), 200)

    def test_z_buffer_occlusion(self):
        """Object further from camera should be occluded by closer one."""
        fb, cam, lights = self._simple_ctx(64)
        from src.math3d import Mat4
        # Front box (red)
        front = _make_cube(1.0, Material.colored(1,0,0))
        # Back box (green) — further from camera
        back  = _make_cube(1.0, Material.colored(0,1,0))
        ctx = RenderContext(fb, cam, lights)
        render_mesh(ctx, front, Mat4.translation(0,0,0))
        render_mesh(ctx, back,  Mat4.translation(0,0,-2))
        # Check pixel at center — should be red (front), not green
        r, g, b = fb.get_pixel(32, 32)
        self.assertGreater(r, g)  # red > green at center

    def test_backface_culling(self):
        """Back-facing triangle (culled convention) → zero pixels drawn."""
        from src.math3d import Mat4
        fb = Framebuffer(32, 32)
        fb.clear((0, 0, 0))
        cam = Camera(eye=Vec3(0,0,3), center=Vec3(0,0,0), fov_y=60,
                     aspect=1.0, near=0.1, far=20, width=32, height=32)
        mat = Material.colored(1,1,1)
        mat.ambient = Vec3(1,1,1)
        lights = [Light.ambient(Vec3(1,1,1), 1.0)]
        # Triangle winding that gives area < 0 in screen space = culled by rasterizer.
        # Camera at (0,0,3), looking at origin. CCW from +Z perspective gives area < 0.
        v0 = Vertex(Vec3(-1,-1,0), Vec3(0,0,1), (0,0))
        v1 = Vertex(Vec3( 1,-1,0), Vec3(0,0,1), (1,0))
        v2 = Vertex(Vec3( 0, 1,0), Vec3(0,0,1), (0.5,1))
        mesh = Mesh("test")
        mesh.triangles = [Triangle(v0, v1, v2, mat)]
        ctx = RenderContext(fb, cam, lights)
        render_mesh(ctx, mesh, Mat4.identity())
        lit = _count_lit(fb)
        self.assertEqual(lit, 0, f"Expected 0 lit pixels (culled winding), got {lit}")

    def test_frontface_rendered(self):
        """Front-facing triangle (kept convention) → pixels drawn."""
        from src.math3d import Mat4
        fb = Framebuffer(32, 32)
        fb.clear((0, 0, 0))
        cam = Camera(eye=Vec3(0,0,3), center=Vec3(0,0,0), fov_y=60,
                     aspect=1.0, near=0.1, far=20, width=32, height=32)
        mat = Material.colored(1,1,1)
        mat.ambient = Vec3(1,1,1)
        lights = [Light.ambient(Vec3(1,1,1), 1.0)]
        # Reversed winding (CW from +Z) → area > 0 → rendered.
        v0 = Vertex(Vec3(-1,-1,0), Vec3(0,0,-1), (0,0))
        v1 = Vertex(Vec3( 0, 1,0), Vec3(0,0,-1), (0.5,1))
        v2 = Vertex(Vec3( 1,-1,0), Vec3(0,0,-1), (1,0))
        mesh = Mesh("test")
        mesh.triangles = [Triangle(v0, v1, v2, mat)]
        ctx = RenderContext(fb, cam, lights)
        render_mesh(ctx, mesh, Mat4.identity())
        lit = _count_lit(fb)
        self.assertGreater(lit, 50, f"Expected lit pixels for front face, got {lit}")

    def test_wireframe_no_fill(self):
        """Wireframe mode produces lines but sparse interior."""
        fb, cam, lights = self._simple_ctx(64)
        from src.math3d import Mat4
        mesh = _make_cube(1.0)
        ctx = RenderContext(fb, cam, lights, wireframe=True)
        render_mesh(ctx, mesh, Mat4.identity())
        lit = _count_lit(fb)
        # Some pixels should be lit (wire edges) but fewer than filled
        self.assertGreater(lit, 0)
        self.assertLess(lit, 64*64 // 4)

    def test_depth_render_pass(self):
        """render_depth fills depth buffer with valid finite values."""
        db = DepthBuffer(32, 32)
        db.clear()
        cam = LightCamera(eye=Vec3(0,5,0), center=Vec3(0,0,0),
                          ortho=True, ortho_size=3.0, near=0.1, far=20)
        from src.math3d import Mat4
        mesh = _make_cube(1.0)
        render_depth(db, mesh, Mat4.identity(), cam)
        # Some pixels should have finite depths
        finite = sum(1 for v in db.depth if v != float('inf'))
        self.assertGreater(finite, 0)


# ══════════════════════════════════════════════════════════════
# 8. PNG Encoder Tests
# ══════════════════════════════════════════════════════════════

class TestPngEncoder(unittest.TestCase):
    def test_encode_decode_roundtrip(self):
        """Encode then decode a small solid-color image → same pixels."""
        w, h = 8, 8
        rgb = bytes([200, 100, 50] * (w*h))
        data = encode_png(w, h, rgb)
        dw, dh, dpix = _decode_png(data)
        self.assertEqual(dw, w); self.assertEqual(dh, h)
        self.assertEqual(len(dpix), w*h*3)
        self.assertEqual(dpix[0], 200)
        self.assertEqual(dpix[1], 100)
        self.assertEqual(dpix[2], 50)

    def test_png_signature(self):
        data = encode_png(2, 2, bytes([0]*12))
        self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')

    def test_png_save_load(self):
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            path = f.name
        try:
            save_png(path, 4, 4, bytes([128]*48))
            with open(path, 'rb') as ff:
                data = ff.read()
            self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
        finally:
            os.unlink(path)

    def test_framebuffer_to_png_valid(self):
        """Rendering to fb → PNG → valid PNG bytes."""
        fb = Framebuffer(16, 16)
        fb.clear((0.5, 0.3, 0.1))
        # Render a cube
        mesh = _make_cube(1.0, Material.colored(0.8, 0.2, 0.2))
        cam = Camera(eye=Vec3(0,0,3), center=Vec3(0,0,0), fov_y=60,
                     aspect=1.0, near=0.1, far=20, width=16, height=16)
        lights = [Light.ambient(Vec3(1,1,1), 1.0)]
        from src.math3d import Mat4
        ctx = RenderContext(fb, cam, lights)
        render_mesh(ctx, mesh, Mat4.identity())
        rgb = fb.resolve_to_rgb_bytes()
        data = encode_png(16, 16, rgb)
        self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
        self.assertGreater(len(data), 50)  # even a tiny compressed PNG needs header + IDAT


# ══════════════════════════════════════════════════════════════
# 9. Full-Pipeline Smoke Tests
# ══════════════════════════════════════════════════════════════

class TestFullPipeline(unittest.TestCase):
    """Each scene renders without error and produces non-trivial output."""

    def _render(self, scene, size=64):
        """Run render_scene through the full stack."""
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        import importlib.util, types
        # Import prism module functions directly
        spec = importlib.util.spec_from_file_location(
            "prism", os.path.join(os.path.dirname(__file__), '..', 'prism.py'))
        prism = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(prism)
        textures = prism._build_textures()
        fb, elapsed = prism._render_scene(scene, size, size, msaa=1,
                                          shadow=False, textures=textures)
        return fb, elapsed

    def test_render_torus(self):
        fb, el = self._render("torus")
        self.assertGreater(_count_lit(fb), 50)
        self.assertLess(el, 30)

    def test_render_sphere(self):
        fb, el = self._render("sphere")
        self.assertGreater(_count_lit(fb), 50)

    def test_render_cornell(self):
        fb, el = self._render("cornell")
        self.assertGreater(_count_lit(fb), 100)

    def test_render_shadow_demo(self):
        fb, el = self._render("shadow_demo")
        self.assertGreater(_count_lit(fb), 100)

    def test_render_showcase(self):
        fb, el = self._render("showcase")
        self.assertGreater(_count_lit(fb), 100)

    def test_normals_mode_produces_color(self):
        """shade_mode='normals' renders normal vectors as RGB (not Phong output)."""
        fb = Framebuffer(64, 64)
        fb.clear((0, 0, 0))
        cam = Camera(eye=Vec3(0,0,3), center=Vec3(0,0,0), fov_y=60,
                     aspect=1.0, near=0.1, far=20, width=64, height=64)
        lights = [Light.ambient()]
        mesh = _make_sphere(rings=12, sectors=12)
        from src.math3d import Mat4
        ctx = RenderContext(fb, cam, lights, shade_mode='normals')
        render_mesh(ctx, mesh, Mat4.identity())
        # Centre pixel should be blue-ish (front-facing normal maps to high Z → high B)
        r, g, b = fb.get_pixel(32, 32)
        self.assertGreater(b, 0.6, f"Expected blue-dominant center normal, got r={r:.2f} g={g:.2f} b={b:.2f}")
        # Should produce colored pixels across the sphere
        colored = sum(1 for x in range(64) for y in range(64)
                      if any(fb.get_pixel(x,y)[c] > 0.1 for c in range(3)))
        self.assertGreater(colored, 200)

    def test_shadow_pass_reduces_light(self):
        """Rendering with shadow=True produces same or fewer bright pixels."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "prism2", os.path.join(os.path.dirname(__file__), '..', 'prism.py'))
        prism = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(prism)
        textures = prism._build_textures()
        fb_no, _ = prism._render_scene("shadow_demo", 64, 64, msaa=1,
                                       shadow=False, textures=textures)
        fb_sh, _ = prism._render_scene("shadow_demo", 64, 64, msaa=1,
                                       shadow=True, textures=textures)
        # Shadow version should have fewer or equal bright pixels (shadows darken)
        bright_no = _count_lit(fb_no, 0.3)
        bright_sh = _count_lit(fb_sh, 0.3)
        self.assertLessEqual(bright_sh, bright_no + 10)  # shadows reduce brightness


if __name__ == '__main__':
    unittest.main(verbosity=2)
