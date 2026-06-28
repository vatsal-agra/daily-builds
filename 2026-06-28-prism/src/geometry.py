"""Mesh, material, OBJ/MTL loader, and procedural model generators."""
import math
import os
from .math3d import Vec3


class Material:
    def __init__(self, name="default"):
        self.name = name
        self.ambient   = Vec3(0.1, 0.1, 0.1)
        self.diffuse   = Vec3(0.7, 0.7, 0.7)
        self.specular  = Vec3(0.3, 0.3, 0.3)
        self.shininess = 32.0
        self.alpha     = 1.0
        self.texture   = None  # Texture object or None

    @staticmethod
    def default(): return Material("default")

    @staticmethod
    def colored(r, g, b, shininess=32.0):
        m = Material("colored")
        m.ambient  = Vec3(r*0.15, g*0.15, b*0.15)
        m.diffuse  = Vec3(r, g, b)
        m.specular = Vec3(0.4, 0.4, 0.4)
        m.shininess = shininess
        return m


class Vertex:
    __slots__ = ('pos', 'normal', 'uv')
    def __init__(self, pos, normal=None, uv=None):
        self.pos    = pos
        self.normal = normal if normal else Vec3(0,1,0)
        self.uv     = uv if uv else (0.0, 0.0)


class Triangle:
    __slots__ = ('v', 'material')
    def __init__(self, v0, v1, v2, material=None):
        self.v = (v0, v1, v2)
        self.material = material or Material.default()


class Mesh:
    def __init__(self, name="mesh"):
        self.name = name
        self.triangles = []  # list of Triangle


def _parse_mtl(path):
    """Parse MTL file, return dict name→Material."""
    mats = {}
    cur = None
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'): continue
                tok = line.split()
                cmd = tok[0].lower()
                if cmd == 'newmtl':
                    name = tok[1] if len(tok)>1 else 'mat'
                    cur = Material(name)
                    mats[name] = cur
                elif cur is None:
                    continue
                elif cmd == 'ka' and len(tok)>=4:
                    cur.ambient = Vec3(float(tok[1]),float(tok[2]),float(tok[3]))
                elif cmd == 'kd' and len(tok)>=4:
                    cur.diffuse = Vec3(float(tok[1]),float(tok[2]),float(tok[3]))
                elif cmd == 'ks' and len(tok)>=4:
                    cur.specular = Vec3(float(tok[1]),float(tok[2]),float(tok[3]))
                elif cmd == 'ns' and len(tok)>=2:
                    cur.shininess = float(tok[1])
                elif cmd == 'd' and len(tok)>=2:
                    cur.alpha = float(tok[1])
    except FileNotFoundError:
        pass
    return mats


def load_obj(path):
    """Load Wavefront OBJ, return Mesh."""
    mesh = Mesh(os.path.splitext(os.path.basename(path))[0])
    positions = []; normals = []; uvs = [(0.0, 0.0)]
    all_mats = {}
    cur_mat = Material.default()
    obj_dir = os.path.dirname(os.path.abspath(path))

    # Accumulate raw faces as tuples (p_idx, uv_idx, n_idx) triples
    raw_faces = []  # each: (mat, [(p,uv,n), (p,uv,n), ...])

    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'): continue
            tok = line.split()
            cmd = tok[0].lower()
            if cmd == 'v' and len(tok)>=4:
                positions.append(Vec3(float(tok[1]),float(tok[2]),float(tok[3])))
            elif cmd == 'vn' and len(tok)>=4:
                normals.append(Vec3(float(tok[1]),float(tok[2]),float(tok[3])))
            elif cmd == 'vt' and len(tok)>=3:
                uvs.append((float(tok[1]), float(tok[2])))
            elif cmd == 'mtllib':
                for mtl_file in tok[1:]:
                    mtl_path = os.path.join(obj_dir, mtl_file)
                    all_mats.update(_parse_mtl(mtl_path))
            elif cmd == 'usemtl' and len(tok)>=2:
                cur_mat = all_mats.get(tok[1], Material.default())
            elif cmd == 'f' and len(tok)>=4:
                verts = []
                for part in tok[1:]:
                    parts = part.split('/')
                    pi = int(parts[0]) - 1
                    ui = int(parts[1])-1 if len(parts)>1 and parts[1] else 0
                    ni = int(parts[2])-1 if len(parts)>2 and parts[2] else -1
                    verts.append((pi, ui+1, ni))  # ui+1 because uvs[0] is (0,0)
                raw_faces.append((cur_mat, verts))

    # Build triangles via fan triangulation
    for mat, verts in raw_faces:
        for i in range(1, len(verts)-1):
            tri_verts = [verts[0], verts[i], verts[i+1]]
            vtx = []
            for pi, ui, ni in tri_verts:
                pos = positions[pi] if 0<=pi<len(positions) else Vec3()
                uv  = uvs[ui] if 0<=ui<len(uvs) else (0.0,0.0)
                nrm = normals[ni].normalize() if 0<=ni<len(normals) else Vec3(0,1,0)
                vtx.append(Vertex(pos, nrm, uv))
            # Compute face normal if normals missing
            if all(vi[2]==-1 for vi in tri_verts):
                e1 = vtx[1].pos - vtx[0].pos
                e2 = vtx[2].pos - vtx[0].pos
                fn = e1.cross(e2).normalize()
                for v in vtx: v.normal = fn
            mesh.triangles.append(Triangle(vtx[0], vtx[1], vtx[2], mat))

    return mesh


# ── Procedural model generators ──

def _make_sphere(radius=1.0, rings=24, sectors=24, material=None):
    mat = material or Material.default()
    mesh = Mesh("sphere")
    for r in range(rings):
        for s in range(sectors):
            def vert(ri, si):
                phi   = math.pi * ri / rings
                theta = 2*math.pi * si / sectors
                x = radius * math.sin(phi)*math.cos(theta)
                y = radius * math.cos(phi)
                z = radius * math.sin(phi)*math.sin(theta)
                nx,ny,nz = x/radius, y/radius, z/radius
                u = si/sectors
                v = ri/rings
                return Vertex(Vec3(x,y,z), Vec3(nx,ny,nz), (u,v))
            v00 = vert(r,  s  ); v10 = vert(r+1,s  )
            v01 = vert(r,  s+1); v11 = vert(r+1,s+1)
            if r > 0:
                mesh.triangles.append(Triangle(v00, v10, v11, mat))
            if r < rings-1:
                mesh.triangles.append(Triangle(v00, v11, v01, mat))
    return mesh


def _make_torus(R=1.0, r=0.35, rings=40, sectors=20, material=None):
    mat = material or Material.default()
    mesh = Mesh("torus")
    for i in range(rings):
        for j in range(sectors):
            def vert(ii, jj):
                u = 2*math.pi*ii/rings
                v = 2*math.pi*jj/sectors
                cx = (R + r*math.cos(v))*math.cos(u)
                cy = r*math.sin(v)
                cz = (R + r*math.cos(v))*math.sin(u)
                nx = math.cos(v)*math.cos(u)
                ny = math.sin(v)
                nz = math.cos(v)*math.sin(u)
                return Vertex(Vec3(cx,cy,cz), Vec3(nx,ny,nz), (ii/rings, jj/sectors))
            v00 = vert(i,j); v10 = vert(i+1,j)
            v01 = vert(i,j+1); v11 = vert(i+1,j+1)
            mesh.triangles.append(Triangle(v00, v10, v11, mat))
            mesh.triangles.append(Triangle(v00, v11, v01, mat))
    return mesh


def _make_cube(size=1.0, material=None):
    mat = material or Material.default()
    mesh = Mesh("cube")
    s = size*0.5
    faces = [
        # (normal, p0, p1, p2, p3)  CCW winding
        (Vec3( 0, 0, 1), (-s,-s, s),(s,-s, s),(s, s, s),(-s, s, s)),
        (Vec3( 0, 0,-1), ( s,-s,-s),(-s,-s,-s),(-s, s,-s),(s, s,-s)),
        (Vec3( 0, 1, 0), (-s, s,-s),(s, s,-s),(s, s, s),(-s, s, s)),
        (Vec3( 0,-1, 0), (-s,-s, s),(s,-s, s),(s,-s,-s),(-s,-s,-s)),
        (Vec3( 1, 0, 0), (s,-s, s),(s,-s,-s),(s, s,-s),(s, s, s)),
        (Vec3(-1, 0, 0), (-s,-s,-s),(-s,-s, s),(-s, s, s),(-s, s,-s)),
    ]
    uvs = [(0,0),(1,0),(1,1),(0,1)]
    for n, p0,p1,p2,p3 in faces:
        pts = [p0,p1,p2,p3]
        verts = [Vertex(Vec3(*p), n, uvs[k]) for k,p in enumerate(pts)]
        mesh.triangles.append(Triangle(verts[0],verts[1],verts[2], mat))
        mesh.triangles.append(Triangle(verts[0],verts[2],verts[3], mat))
    return mesh


def _make_plane(size=2.0, subdivisions=1, material=None):
    mat = material or Material.default()
    mesh = Mesh("plane")
    n = subdivisions
    step = size / n
    for i in range(n):
        for j in range(n):
            x0 = -size/2 + i*step; x1 = x0+step
            z0 = -size/2 + j*step; z1 = z0+step
            u0,u1 = i/n, (i+1)/n; v0,v1 = j/n, (j+1)/n
            v00 = Vertex(Vec3(x0,0,z0), Vec3(0,1,0), (u0,v0))
            v10 = Vertex(Vec3(x1,0,z0), Vec3(0,1,0), (u1,v0))
            v01 = Vertex(Vec3(x0,0,z1), Vec3(0,1,0), (u0,v1))
            v11 = Vertex(Vec3(x1,0,z1), Vec3(0,1,0), (u1,v1))
            mesh.triangles.append(Triangle(v00,v10,v11, mat))
            mesh.triangles.append(Triangle(v00,v11,v01, mat))
    return mesh


def _make_cylinder(radius=0.5, height=1.0, sectors=24, material=None):
    mat = material or Material.default()
    mesh = Mesh("cylinder")
    h = height*0.5
    for i in range(sectors):
        a0 = 2*math.pi*i/sectors; a1 = 2*math.pi*(i+1)/sectors
        x0,z0 = radius*math.cos(a0), radius*math.sin(a0)
        x1,z1 = radius*math.cos(a1), radius*math.sin(a1)
        n0 = Vec3(math.cos(a0),0,math.sin(a0))
        n1 = Vec3(math.cos(a1),0,math.sin(a1))
        # Side quad
        vBL = Vertex(Vec3(x0,-h,z0), n0, (i/sectors, 0))
        vBR = Vertex(Vec3(x1,-h,z1), n1, ((i+1)/sectors, 0))
        vTL = Vertex(Vec3(x0, h,z0), n0, (i/sectors, 1))
        vTR = Vertex(Vec3(x1, h,z1), n1, ((i+1)/sectors, 1))
        mesh.triangles.append(Triangle(vBL,vBR,vTR, mat))
        mesh.triangles.append(Triangle(vBL,vTR,vTL, mat))
        # Top cap
        tc = Vertex(Vec3(0,h,0), Vec3(0,1,0), (0.5,0.5))
        t0 = Vertex(Vec3(x0,h,z0), Vec3(0,1,0), (math.cos(a0)*0.5+0.5, math.sin(a0)*0.5+0.5))
        t1 = Vertex(Vec3(x1,h,z1), Vec3(0,1,0), (math.cos(a1)*0.5+0.5, math.sin(a1)*0.5+0.5))
        mesh.triangles.append(Triangle(tc,t1,t0, mat))
        # Bottom cap
        bc = Vertex(Vec3(0,-h,0), Vec3(0,-1,0), (0.5,0.5))
        b0 = Vertex(Vec3(x0,-h,z0), Vec3(0,-1,0), (math.cos(a0)*0.5+0.5, math.sin(a0)*0.5+0.5))
        b1 = Vertex(Vec3(x1,-h,z1), Vec3(0,-1,0), (math.cos(a1)*0.5+0.5, math.sin(a1)*0.5+0.5))
        mesh.triangles.append(Triangle(bc,b0,b1, mat))
    return mesh


def make_scene_objects(scene_name, textures=None):
    """Return list of (mesh, model_matrix) for named built-in scenes."""
    from .math3d import Mat4
    textures = textures or {}
    if scene_name == "torus":
        mat_gold = Material.colored(0.85, 0.65, 0.1, shininess=80)
        mat_gold.specular = Vec3(1.0, 0.9, 0.5)
        torus = _make_torus(material=mat_gold)
        return [(torus, Mat4.identity())]
    elif scene_name == "sphere":
        mat = Material.colored(0.8, 0.2, 0.2)
        if 'checker' in textures:
            mat.texture = textures['checker']
        sph = _make_sphere(material=mat)
        return [(sph, Mat4.identity())]
    elif scene_name == "cornell":
        from .math3d import Mat4
        objects = []
        # Floor
        flmat = Material.colored(0.73, 0.73, 0.73)
        floor = _make_plane(size=4.0, subdivisions=4, material=flmat)
        objects.append((floor, Mat4.identity()))
        # Left wall (red): normal must point +X (inward) → rotation_z(-pi/2)
        lmat = Material.colored(0.65, 0.05, 0.05)
        lwall = _make_plane(size=4.0, subdivisions=4, material=lmat)
        objects.append((lwall,
            Mat4.translation(-2,2,0)*Mat4.rotation_z(-math.pi/2)))
        # Right wall (green): normal must point -X (inward) → rotation_z(+pi/2)
        rmat = Material.colored(0.12, 0.45, 0.15)
        rwall = _make_plane(size=4.0, subdivisions=4, material=rmat)
        objects.append((rwall,
            Mat4.translation(2,2,0)*Mat4.rotation_z(math.pi/2)))
        # Back wall
        bkmat = Material.colored(0.73, 0.73, 0.73)
        bkwall = _make_plane(size=4.0, subdivisions=4, material=bkmat)
        objects.append((bkwall,
            Mat4.translation(0,2,-2)*Mat4.rotation_x(math.pi/2)))
        # Ceiling
        cmat = Material.colored(0.73, 0.73, 0.73)
        ceiling = _make_plane(size=4.0, subdivisions=4, material=cmat)
        objects.append((ceiling, Mat4.translation(0,4,0)*Mat4.rotation_z(math.pi)))
        # Two boxes
        smat = Material.colored(0.73, 0.73, 0.73, shininess=10)
        tallbox = _make_cube(size=1.2, material=smat)
        objects.append((tallbox, Mat4.translation(-0.6, 1.2, -0.4)*Mat4.rotation_y(0.15)))
        shortbox = _make_cube(size=0.9, material=smat)
        objects.append((shortbox, Mat4.translation(0.7, 0.45, 0.3)*Mat4.rotation_y(-0.25)))
        # Sphere
        spmat = Material.colored(0.9,0.9,0.9, shininess=120)
        spmat.specular = Vec3(0.8,0.8,0.8)
        sp = _make_sphere(radius=0.5, material=spmat)
        objects.append((sp, Mat4.translation(0, 0.5, 0.5)))
        return objects
    elif scene_name == "shadow_demo":
        objects = []
        # Ground plane with checkerboard texture
        pmat = Material.colored(0.9, 0.9, 0.9, shininess=5)
        if 'checker' in textures:
            pmat.texture = textures['checker']
        plane = _make_plane(size=8.0, subdivisions=8, material=pmat)
        objects.append((plane, Mat4.translation(0, -1.2, 0)))
        # Sphere
        spmat = Material.colored(0.3, 0.5, 0.9, shininess=64)
        sp = _make_sphere(radius=0.7, material=spmat)
        objects.append((sp, Mat4.translation(-1.2, -0.5, 0)))
        # Torus
        tmat = Material.colored(0.9, 0.4, 0.1, shininess=40)
        torus = _make_torus(R=0.7, r=0.25, material=tmat)
        objects.append((torus, Mat4.translation(1.0, -0.3, 0.3)*Mat4.rotation_x(0.5)))
        # Box
        bmat = Material.colored(0.8, 0.7, 0.2, shininess=20)
        box = _make_cube(size=0.8, material=bmat)
        objects.append((box, Mat4.translation(-0.1, -0.8, -0.5)*Mat4.rotation_y(0.8)))
        return objects
    elif scene_name == "showcase":
        from .math3d import Mat4
        objects = []
        # Ground
        gmat = Material.colored(0.5, 0.5, 0.6, shininess=5)
        if 'marble' in textures:
            gmat.texture = textures['marble']
        floor = _make_plane(size=10.0, subdivisions=10, material=gmat)
        objects.append((floor, Mat4.translation(0,-1.5,0)))
        # Torus (gold)
        tmat = Material.colored(0.9, 0.75, 0.15, shininess=100)
        tmat.specular = Vec3(1.0, 0.95, 0.6)
        torus = _make_torus(material=tmat)
        objects.append((torus, Mat4.translation(-2.5, 0, 0)))
        # Sphere (earth texture)
        spmat = Material.colored(0.6, 0.7, 0.9, shininess=30)
        if 'earth' in textures:
            spmat.texture = textures['earth']
        sp = _make_sphere(rings=32, sectors=32, material=spmat)
        objects.append((sp, Mat4.translation(0, 0, 0)))
        # Cylinder (marble)
        cmat = Material.colored(0.8, 0.8, 0.9, shininess=50)
        if 'marble' in textures:
            cmat.texture = textures['marble']
        cyl = _make_cylinder(radius=0.5, height=1.5, material=cmat)
        objects.append((cyl, Mat4.translation(2.5, -0.25, 0)))
        # Small cube on top of cylinder
        bmat = Material.colored(0.9, 0.3, 0.3, shininess=60)
        box = _make_cube(size=0.7, material=bmat)
        objects.append((box, Mat4.translation(2.5, 0.85, 0)*Mat4.rotation_y(0.5)))
        return objects
    raise ValueError(f"Unknown scene: {scene_name!r}")
