"""Minimal .obj file loader → list of Triangle primitives."""
from .vec3 import Vec3
from .primitives import Triangle


def load_obj(path, material, scale=1.0, offset=None):
    """
    Parse a .obj file, returning a list of Triangle objects.
    Handles v (vertex) and f (face) lines; silently ignores everything else.
    Faces with >3 vertices are fan-triangulated.
    """
    if offset is None:
        offset = Vec3(0, 0, 0)

    vertices = []
    triangles = []

    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if parts[0] == 'v':
                x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
                vertices.append(Vec3(x * scale + offset.x,
                                     y * scale + offset.y,
                                     z * scale + offset.z))
            elif parts[0] == 'f':
                # Face indices may be "v", "v/vt", or "v/vt/vn" — we only need v
                def parse_idx(token):
                    return int(token.split('/')[0]) - 1
                indices = [parse_idx(t) for t in parts[1:]]
                # Fan-triangulate
                for i in range(1, len(indices) - 1):
                    v0 = vertices[indices[0]]
                    v1 = vertices[indices[i]]
                    v2 = vertices[indices[i + 1]]
                    triangles.append(Triangle(v0, v1, v2, material))

    return triangles
