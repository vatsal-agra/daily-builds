"""
Core software rasterizer.

Pipeline per triangle:
  1. Transform vertices to clip space via MVP matrix
  2. Near-plane clip (Cohen-Sutherland w-component clip)
  3. Perspective divide → NDC
  4. Viewport transform → screen pixels
  5. Back-face cull in NDC (signed area test)
  6. Rasterize: edge functions, barycentric interp, z-test
  7. Fragment shader (Blinn-Phong)
"""
import math
from .math3d import Vec3, Vec4, Mat4
from .framebuffer import Framebuffer, DepthBuffer
from .shader import blinn_phong, sample_shadow_pcf, Light
from .geometry import Triangle, Mesh, Vertex


def _edge(ax, ay, bx, by, px, py):
    """Signed edge function for point (px,py) against edge (ax,ay)→(bx,by)."""
    return (bx - ax)*(py - ay) - (by - ay)*(px - ax)


def _clip_triangle_near(v0, v1, v2, near=0.0):
    """
    Clip a triangle against the w > near plane in clip space.
    Returns list of triangles (0, 1, or 2) as vertex tuples.
    Each vertex is a tuple: (clip Vec4, Vertex original).
    """
    eps = near
    verts = [v0, v1, v2]

    def inside_near(v): return v[0].w > eps

    result_verts = []
    n = 3
    for i in range(n):
        cur = verts[i]
        nxt = verts[(i+1) % n]
        ci = inside_near(cur)
        ni = inside_near(nxt)
        if ci:
            result_verts.append(cur)
        if ci != ni:
            # Interpolate
            cw = cur[0].w; nw = nxt[0].w
            t = (eps - cw) / (nw - cw)
            # Interpolate clip position
            ic = Vec4(
                cur[0].x + t*(nxt[0].x - cur[0].x),
                cur[0].y + t*(nxt[0].y - cur[0].y),
                cur[0].z + t*(nxt[0].z - cur[0].z),
                cur[0].w + t*(nxt[0].w - cur[0].w),
            )
            # Interpolate original vertex attributes
            co = cur[1]; no = nxt[1]
            ip_pos = co.pos + (no.pos - co.pos)*t
            ip_nrm = (co.normal + (no.normal - co.normal)*t).normalize()
            ip_uv  = (co.uv[0]+(no.uv[0]-co.uv[0])*t,
                      co.uv[1]+(no.uv[1]-co.uv[1])*t)
            from .geometry import Vertex
            io = Vertex(ip_pos, ip_nrm, ip_uv)
            result_verts.append((ic, io))

    if len(result_verts) < 3:
        return []
    # Fan-triangulate
    tris = []
    for i in range(1, len(result_verts)-1):
        tris.append((result_verts[0], result_verts[i], result_verts[i+1]))
    return tris


class RenderContext:
    def __init__(self, fb, camera, lights, shadow_map=None, light_vp=None,
                 wireframe=False):
        self.fb = fb
        self.camera = camera
        self.lights = lights          # list of Light in view space
        self.shadow_map = shadow_map  # DepthBuffer or None
        self.light_vp = light_vp      # Mat4 (light view-proj) or None
        self.wireframe = wireframe


def _draw_line(fb, x0, y0, x1, y1, r, g, b):
    """Bresenham line for wireframe mode."""
    x0,y0,x1,y1 = int(x0),int(y0),int(x1),int(y1)
    dx = abs(x1-x0); dy = abs(y1-y0)
    sx = 1 if x0<x1 else -1; sy = 1 if y0<y1 else -1
    err = dx-dy
    W,H = fb.rw,fb.rh
    while True:
        if 0<=x0<W and 0<=y0<H:
            fb.set_pixel(x0,y0,r,g,b)
        if x0==x1 and y0==y1: break
        e2 = 2*err
        if e2 > -dy: err -= dy; x0 += sx
        if e2 <  dx: err += dx; y0 += sy


def render_mesh(ctx, mesh, model_matrix):
    """Render a Mesh with the given model matrix into ctx.fb."""
    fb = ctx.fb
    cam = ctx.camera
    W, H = fb.rw, fb.rh

    view  = cam.view_matrix
    proj  = cam.proj_matrix
    mv    = view * model_matrix
    mvp   = proj * mv

    # Normal matrix: inverse-transpose of upper-left 3×3 of MV
    try:
        normal_mat = mv.normal_matrix()
    except ValueError:
        normal_mat = mv

    for tri in mesh.triangles:
        v0, v1, v2 = tri.v
        mat = tri.material

        # — Vertex stage: model → clip space —
        c0 = mvp * Vec4.from_vec3(v0.pos)
        c1 = mvp * Vec4.from_vec3(v1.pos)
        c2 = mvp * Vec4.from_vec3(v2.pos)

        # — Near-plane clip —
        clipped = _clip_triangle_near(
            (c0, v0), (c1, v1), (c2, v2), near=cam.near * 0.5
        )
        if not clipped:
            continue

        for (cc0,ov0), (cc1,ov1), (cc2,ov2) in clipped:
            # — Perspective divide → NDC —
            if abs(cc0.w)<1e-9 or abs(cc1.w)<1e-9 or abs(cc2.w)<1e-9:
                continue

            iw0 = 1.0/cc0.w; iw1 = 1.0/cc1.w; iw2 = 1.0/cc2.w

            ndcx0 = cc0.x*iw0; ndcy0 = cc0.y*iw0; ndcz0 = cc0.z*iw0
            ndcx1 = cc1.x*iw1; ndcy1 = cc1.y*iw1; ndcz1 = cc1.z*iw1
            ndcx2 = cc2.x*iw2; ndcy2 = cc2.y*iw2; ndcz2 = cc2.z*iw2

            # — Viewport transform: NDC → screen pixels —
            sx0 = (ndcx0*0.5+0.5)*W; sy0 = (1-(ndcy0*0.5+0.5))*H
            sx1 = (ndcx1*0.5+0.5)*W; sy1 = (1-(ndcy1*0.5+0.5))*H
            sx2 = (ndcx2*0.5+0.5)*W; sy2 = (1-(ndcy2*0.5+0.5))*H

            # — Back-face cull: CCW → front-facing in screen space (Y flipped) —
            area = _edge(sx0,sy0, sx1,sy1, sx2,sy2)
            if area <= 0:
                continue  # back-face or degenerate

            if ctx.wireframe:
                _draw_line(fb,sx0,sy0,sx1,sy1, 0.9,0.9,0.2)
                _draw_line(fb,sx1,sy1,sx2,sy2, 0.9,0.9,0.2)
                _draw_line(fb,sx2,sy2,sx0,sy0, 0.9,0.9,0.2)
                continue

            inv_area = 1.0 / area

            # — Bounding box (clamped to viewport) —
            min_x = max(0, int(min(sx0,sx1,sx2)))
            max_x = min(W-1, int(max(sx0,sx1,sx2))+1)
            min_y = max(0, int(min(sy0,sy1,sy2)))
            max_y = min(H-1, int(max(sy0,sy1,sy2))+1)

            # Pre-compute view-space positions and normals
            vpos0 = mv.transform_point(ov0.pos)
            vpos1 = mv.transform_point(ov1.pos)
            vpos2 = mv.transform_point(ov2.pos)

            # Transform normals by normal matrix (upper-left 3×3 of MV inverse-transpose)
            vnrm0 = normal_mat.transform_direction(ov0.normal).normalize()
            vnrm1 = normal_mat.transform_direction(ov1.normal).normalize()
            vnrm2 = normal_mat.transform_direction(ov2.normal).normalize()

            # Perspective-correct attribute interpolation needs 1/w per vertex
            # and attributes * 1/w
            u0, v_0 = ov0.uv; u1, v_1 = ov1.uv; u2, v_2 = ov2.uv

            # Pre-multiply attributes by 1/w for perspective correction
            u0w = u0*iw0; v0w = v_0*iw0
            u1w = u1*iw1; v1w = v_1*iw1
            u2w = u2*iw2; v2w = v_2*iw2

            vx0w = vpos0.x*iw0; vy0w = vpos0.y*iw0; vz0w = vpos0.z*iw0
            vx1w = vpos1.x*iw1; vy1w = vpos1.y*iw1; vz1w = vpos1.z*iw1
            vx2w = vpos2.x*iw2; vy2w = vpos2.y*iw2; vz2w = vpos2.z*iw2

            nx0w = vnrm0.x*iw0; ny0w = vnrm0.y*iw0; nz0w = vnrm0.z*iw0
            nx1w = vnrm1.x*iw1; ny1w = vnrm1.y*iw1; nz1w = vnrm1.z*iw1
            nx2w = vnrm2.x*iw2; ny2w = vnrm2.y*iw2; nz2w = vnrm2.z*iw2

            # — Rasterize: iterate over bounding box pixels —
            for py in range(min_y, max_y+1):
                for px in range(min_x, max_x+1):
                    cx = px + 0.5; cy = py + 0.5

                    # Edge functions (top-left fill rule: >= 0 for CW/flat-top/flat-left)
                    w0 = _edge(sx1,sy1, sx2,sy2, cx,cy)
                    w1 = _edge(sx2,sy2, sx0,sy0, cx,cy)
                    w2 = _edge(sx0,sy0, sx1,sy1, cx,cy)

                    # Top-left fill rule: reject pixels on shared edges
                    # Edge is "top" if horizontal and goes left; "left" if goes up
                    def is_top_left(ax,ay,bx,by):
                        return (ay==by and ax>bx) or (by<ay)

                    if w0 < 0 or w1 < 0 or w2 < 0: continue
                    if w0 == 0 and not is_top_left(sx1,sy1,sx2,sy2): continue
                    if w1 == 0 and not is_top_left(sx2,sy2,sx0,sy0): continue
                    if w2 == 0 and not is_top_left(sx0,sy0,sx1,sy1): continue

                    # Barycentric coordinates
                    b0 = w0 * inv_area
                    b1 = w1 * inv_area
                    b2 = w2 * inv_area

                    # Perspective-correct interpolate 1/w
                    inv_w = b0*iw0 + b1*iw1 + b2*iw2
                    w_frag = 1.0 / inv_w if abs(inv_w) > 1e-12 else 1.0

                    # Depth (NDC z, then convert to linear for buffer)
                    depth_ndc = b0*ndcz0 + b1*ndcz1 + b2*ndcz2

                    # Z-test
                    if not fb.depth_test_and_set(px, py, depth_ndc):
                        continue

                    # Perspective-correct attributes
                    uf = (b0*u0w + b1*u1w + b2*u2w) * w_frag
                    vf = (b0*v0w + b1*v1w + b2*v2w) * w_frag

                    vpx = (b0*vx0w + b1*vx1w + b2*vx2w) * w_frag
                    vpy = (b0*vy0w + b1*vy1w + b2*vy2w) * w_frag
                    vpz = (b0*vz0w + b1*vz1w + b2*vz2w) * w_frag
                    frag_pos_view = Vec3(vpx, vpy, vpz)

                    nx = (b0*nx0w + b1*nx1w + b2*nx2w) * w_frag
                    ny = (b0*ny0w + b1*ny1w + b2*ny2w) * w_frag
                    nz = (b0*nz0w + b1*nz1w + b2*nz2w) * w_frag
                    frag_normal = Vec3(nx, ny, nz).normalize()

                    # Shadow map lookup
                    shadow = 1.0
                    if ctx.shadow_map is not None and ctx.light_vp is not None:
                        # World position of fragment
                        # We need world pos: we have view-space pos, need to invert view
                        # Since we have model_matrix and original world_pos interpolated:
                        # Actually easier: transform frag_pos_view back to world
                        # via view_matrix inverse (= view_matrix transpose for rigid)
                        # But it's cheaper to interpolate world-space positions directly:
                        # Pre-compute world positions per vertex
                        wp0 = model_matrix.transform_point(ov0.pos)
                        wp1 = model_matrix.transform_point(ov1.pos)
                        wp2 = model_matrix.transform_point(ov2.pos)
                        wpx = (b0*wp0.x*iw0 + b1*wp1.x*iw1 + b2*wp2.x*iw2)*w_frag
                        wpy = (b0*wp0.y*iw0 + b1*wp1.y*iw1 + b2*wp2.y*iw2)*w_frag
                        wpz = (b0*wp0.z*iw0 + b1*wp1.z*iw1 + b2*wp2.z*iw2)*w_frag
                        world_pos = Vec3(wpx,wpy,wpz)
                        lc = ctx.light_vp * Vec4.from_vec3(world_pos)
                        if abs(lc.w) > 1e-9:
                            lndc = lc.to_vec3_div()
                            shadow = sample_shadow_pcf(ctx.shadow_map, lndc)

                    # Fragment shader
                    color = blinn_phong(
                        frag_pos_view, frag_normal, (uf, vf),
                        mat, ctx.lights, shadow_factor=shadow
                    )

                    fb.set_pixel(px, py, color.x, color.y, color.z)


def render_depth(depth_buf, mesh, model_matrix, camera):
    """Depth-only pass for shadow map generation."""
    view = camera.view_matrix
    proj = camera.proj_matrix
    mvp  = proj * view * model_matrix
    W, H = depth_buf.width, depth_buf.height

    for tri in mesh.triangles:
        v0, v1, v2 = tri.v
        c0 = mvp * Vec4.from_vec3(v0.pos)
        c1 = mvp * Vec4.from_vec3(v1.pos)
        c2 = mvp * Vec4.from_vec3(v2.pos)

        clipped = _clip_triangle_near((c0,v0),(c1,v1),(c2,v2), near=camera.near*0.5)
        if not clipped: continue

        for (cc0,_),(cc1,_),(cc2,_) in clipped:
            if abs(cc0.w)<1e-9 or abs(cc1.w)<1e-9 or abs(cc2.w)<1e-9: continue
            iw0=1/cc0.w; iw1=1/cc1.w; iw2=1/cc2.w
            sx0=(cc0.x*iw0*0.5+0.5)*W; sy0=(1-(cc0.y*iw0*0.5+0.5))*H
            sx1=(cc1.x*iw1*0.5+0.5)*W; sy1=(1-(cc1.y*iw1*0.5+0.5))*H
            sx2=(cc2.x*iw2*0.5+0.5)*W; sy2=(1-(cc2.y*iw2*0.5+0.5))*H
            nz0=cc0.z*iw0; nz1=cc1.z*iw1; nz2=cc2.z*iw2

            area = _edge(sx0,sy0,sx1,sy1,sx2,sy2)
            if area <= 0: continue
            inv_a = 1.0/area

            min_x=max(0,int(min(sx0,sx1,sx2))); max_x=min(W-1,int(max(sx0,sx1,sx2))+1)
            min_y=max(0,int(min(sy0,sy1,sy2))); max_y=min(H-1,int(max(sy0,sy1,sy2))+1)

            for py in range(min_y,max_y+1):
                for px in range(min_x,max_x+1):
                    cx=px+0.5; cy=py+0.5
                    w0=_edge(sx1,sy1,sx2,sy2,cx,cy)
                    w1=_edge(sx2,sy2,sx0,sy0,cx,cy)
                    w2=_edge(sx0,sy0,sx1,sy1,cx,cy)
                    if w0<0 or w1<0 or w2<0: continue
                    b0=w0*inv_a; b1=w1*inv_a; b2=w2*inv_a
                    d=b0*nz0+b1*nz1+b2*nz2
                    depth_buf.depth_test_and_set(px,py,d)
