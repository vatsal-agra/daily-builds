"""Wavefront OBJ mesh loader for Lumina path tracer.

Parses vertex positions, vertex normals, and face definitions from .obj files.
Builds smooth-shading triangles using interpolated vertex normals.
Falls back to flat face normals when no normals are provided.

Supported OBJ features:
  v   x y z        vertex position
  vn  x y z        vertex normal
  f   v[/vt/vn] ...  face (triangulated; handles quads via fan triangulation)
  #   comment

Unsupported (silently ignored):
  vt texture coords, mtllib, usemtl, o, g, s
"""
import math
import os
from vec3 import Vec3
from geometry import Triangle


def load_obj(path: str, material,
             scale: float = 1.0,
             translate: Vec3 = None,
             flip_normals: bool = False) -> list:
    """Load a .obj file and return a list of Triangle primitives.

    Args:
        path:         Path to .obj file.
        material:     Material to apply to all triangles.
        scale:        Uniform scale factor applied to all vertex positions.
        translate:    Translation Vec3 applied after scaling.
        flip_normals: Flip all normals (for inside-out geometry).

    Returns:
        List of Triangle objects, ready to be added to a Scene.

    Raises:
        FileNotFoundError: If the .obj file does not exist.
        ValueError: If the file contains malformed geometry.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"OBJ file not found: {path!r}")

    translate = translate or Vec3(0.0, 0.0, 0.0)

    verts = []   # List of Vec3 positions (1-indexed in OBJ → 0-indexed here)
    normals = [] # List of Vec3 normals (1-indexed in OBJ)
    triangles = []

    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line_no, raw_line in enumerate(f, 1):
            line = raw_line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            token = parts[0]

            if token == 'v' and len(parts) >= 4:
                try:
                    x = float(parts[1]) * scale + translate.x
                    y = float(parts[2]) * scale + translate.y
                    z = float(parts[3]) * scale + translate.z
                    verts.append(Vec3(x, y, z))
                except ValueError:
                    pass

            elif token == 'vn' and len(parts) >= 4:
                try:
                    nx = float(parts[1])
                    ny = float(parts[2])
                    nz = float(parts[3])
                    n = Vec3(nx, ny, nz).normalize()
                    if flip_normals:
                        n = -n
                    normals.append(n)
                except ValueError:
                    pass

            elif token == 'f' and len(parts) >= 4:
                # Parse face vertices; each part is v[/vt[/vn]]
                face_verts = []
                face_normals = []
                for part in parts[1:]:
                    indices = part.split('/')
                    vi = int(indices[0]) - 1  # OBJ is 1-indexed
                    if vi < 0:
                        vi = len(verts) + vi + 1  # negative relative index
                    if vi < 0 or vi >= len(verts):
                        break
                    face_verts.append(verts[vi])
                    # Vertex normal (optional, third index)
                    ni = None
                    if len(indices) >= 3 and indices[2]:
                        ni = int(indices[2]) - 1
                        if ni < 0:
                            ni = len(normals) + ni + 1
                        if 0 <= ni < len(normals):
                            face_normals.append(normals[ni])
                        else:
                            face_normals.append(None)
                    else:
                        face_normals.append(None)

                # Fan-triangulate the face (handles quads and n-gons)
                n_verts = len(face_verts)
                for i in range(1, n_verts - 1):
                    v0 = face_verts[0]
                    v1 = face_verts[i]
                    v2 = face_verts[i + 1]
                    n0 = face_normals[0]
                    n1 = face_normals[i]
                    n2 = face_normals[i + 1]
                    if None in (n0, n1, n2):
                        triangles.append(Triangle(v0, v1, v2, material))
                    else:
                        # Normals already negated during vn parsing if flip_normals=True
                        triangles.append(Triangle(v0, v1, v2, material, n0, n1, n2))

    if not triangles:
        raise ValueError(f"No valid triangles found in {path!r}")
    return triangles


def generate_smooth_normals(path_in: str, path_out: str):
    """Read an OBJ with no normals, compute per-vertex angle-weighted smooth normals,
    and write a new OBJ with vn declarations. Useful for flat-shaded meshes.
    """
    verts = []
    faces_raw = []

    with open(path_in, 'r') as f:
        for line in f:
            parts = line.strip().split()
            if not parts:
                continue
            if parts[0] == 'v' and len(parts) >= 4:
                verts.append(Vec3(float(parts[1]), float(parts[2]), float(parts[3])))
            elif parts[0] == 'f' and len(parts) >= 4:
                indices = [int(p.split('/')[0]) - 1 for p in parts[1:]]
                faces_raw.append(indices)

    # Accumulate angle-weighted normals per vertex
    vertex_normals = [Vec3(0.0, 0.0, 0.0)] * len(verts)
    for idxs in faces_raw:
        n = len(idxs)
        # Fan triangulate
        for i in range(1, n - 1):
            v0, v1, v2 = verts[idxs[0]], verts[idxs[i]], verts[idxs[i + 1]]
            e1 = v1 - v0
            e2 = v2 - v0
            cross = e1.cross(e2)
            area = cross.length()
            if area < 1e-20:
                continue
            fn = cross / area
            # Angle at each vertex for weighting
            def angle_at(a, b, c):
                ba = (b - a).normalize()
                ca = (c - a).normalize()
                return math.acos(max(-1.0, min(1.0, ba.dot(ca))))
            a0 = angle_at(v0, v1, v2)
            a1 = angle_at(v1, v0, v2)
            a2 = angle_at(v2, v0, v1)
            for idx, w in [(idxs[0], a0), (idxs[i], a1), (idxs[i + 1], a2)]:
                vn = vertex_normals[idx]
                vertex_normals[idx] = Vec3(vn.x + fn.x * w,
                                           vn.y + fn.y * w,
                                           vn.z + fn.z * w)

    vertex_normals = [n.normalize() for n in vertex_normals]

    with open(path_out, 'w') as f:
        f.write(f"# Generated by Lumina smooth-normal generator\n")
        for v in verts:
            f.write(f"v {v.x} {v.y} {v.z}\n")
        for n in vertex_normals:
            f.write(f"vn {n.x} {n.y} {n.z}\n")
        for idxs in faces_raw:
            face_str = ' '.join(f"{i + 1}//{i + 1}" for i in idxs)
            f.write(f"f {face_str}\n")

    return len(verts), len(faces_raw)


def obj_bounds(triangles: list):
    """Return (min_p, max_p, center, extent) for a list of Triangle objects."""
    xs = [min(t.v0.x, t.v1.x, t.v2.x) for t in triangles]
    ys = [min(t.v0.y, t.v1.y, t.v2.y) for t in triangles]
    zs = [min(t.v0.z, t.v1.z, t.v2.z) for t in triangles]
    xs2 = [max(t.v0.x, t.v1.x, t.v2.x) for t in triangles]
    ys2 = [max(t.v0.y, t.v1.y, t.v2.y) for t in triangles]
    zs2 = [max(t.v0.z, t.v1.z, t.v2.z) for t in triangles]
    mn = Vec3(min(xs), min(ys), min(zs))
    mx = Vec3(max(xs2), max(ys2), max(zs2))
    center = Vec3((mn.x + mx.x) / 2, (mn.y + mx.y) / 2, (mn.z + mx.z) / 2)
    extent = mx - mn
    return mn, mx, center, extent
