"""Vec3, Vec4, Mat4 — minimal linear algebra for a 3D rasterizer."""
import math


class Vec3:
    __slots__ = ('x', 'y', 'z')

    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = float(x); self.y = float(y); self.z = float(z)

    def __add__(self, o): return Vec3(self.x+o.x, self.y+o.y, self.z+o.z)
    def __sub__(self, o): return Vec3(self.x-o.x, self.y-o.y, self.z-o.z)
    def __neg__(self): return Vec3(-self.x, -self.y, -self.z)
    def __mul__(self, s):
        if isinstance(s, Vec3): return Vec3(self.x*s.x, self.y*s.y, self.z*s.z)
        return Vec3(self.x*s, self.y*s, self.z*s)
    def __rmul__(self, s): return self.__mul__(s)
    def __truediv__(self, s): return Vec3(self.x/s, self.y/s, self.z/s)
    def __repr__(self): return f"Vec3({self.x:.4f},{self.y:.4f},{self.z:.4f})"
    def __iter__(self): yield self.x; yield self.y; yield self.z
    def __getitem__(self, i):
        if i == 0: return self.x
        if i == 1: return self.y
        if i == 2: return self.z
        raise IndexError(i)

    def dot(self, o): return self.x*o.x + self.y*o.y + self.z*o.z
    def cross(self, o):
        return Vec3(self.y*o.z - self.z*o.y,
                    self.z*o.x - self.x*o.z,
                    self.x*o.y - self.y*o.x)
    def length_sq(self): return self.x*self.x + self.y*self.y + self.z*self.z
    def length(self): return math.sqrt(self.length_sq())
    def normalize(self):
        l = self.length()
        if l < 1e-12: return Vec3(0.0, 0.0, 1.0)
        return self / l
    def lerp(self, o, t): return self*(1-t) + o*t
    def clamp(self, lo=0.0, hi=1.0):
        return Vec3(max(lo, min(hi, self.x)),
                    max(lo, min(hi, self.y)),
                    max(lo, min(hi, self.z)))
    def reflect(self, n):
        return self - n * (2.0 * self.dot(n))

    @staticmethod
    def zero(): return Vec3(0.0, 0.0, 0.0)
    @staticmethod
    def one(): return Vec3(1.0, 1.0, 1.0)


class Vec4:
    __slots__ = ('x', 'y', 'z', 'w')

    def __init__(self, x=0.0, y=0.0, z=0.0, w=1.0):
        self.x = float(x); self.y = float(y)
        self.z = float(z); self.w = float(w)

    def __repr__(self): return f"Vec4({self.x:.4f},{self.y:.4f},{self.z:.4f},{self.w:.4f})"
    def __iter__(self): yield self.x; yield self.y; yield self.z; yield self.w
    def __getitem__(self, i):
        if i == 0: return self.x
        if i == 1: return self.y
        if i == 2: return self.z
        if i == 3: return self.w
        raise IndexError(i)

    def xyz(self): return Vec3(self.x, self.y, self.z)
    def to_vec3_div(self):
        """Perspective divide: return xyz/w."""
        iw = 1.0 / self.w if abs(self.w) > 1e-12 else 0.0
        return Vec3(self.x*iw, self.y*iw, self.z*iw)

    @staticmethod
    def from_vec3(v, w=1.0): return Vec4(v.x, v.y, v.z, w)


class Mat4:
    """Column-major 4×4 matrix, matching GLSL convention."""
    __slots__ = ('m',)

    def __init__(self, m=None):
        if m is None:
            self.m = [0.0]*16
        else:
            self.m = list(m)

    def __repr__(self):
        rows = []
        for r in range(4):
            rows.append([self.m[c*4+r] for c in range(4)])
        lines = ["[" + ", ".join(f"{v:7.3f}" for v in row) + "]" for row in rows]
        return "\n".join(lines)

    # Element access: m[row][col] via m[col*4+row]
    def get(self, row, col): return self.m[col*4 + row]
    def set(self, row, col, v): self.m[col*4 + row] = v

    @staticmethod
    def identity():
        m = Mat4()
        m.m[0] = m.m[5] = m.m[10] = m.m[15] = 1.0
        return m

    def __mul__(self, other):
        if isinstance(other, Mat4):
            r = Mat4()
            for row in range(4):
                for col in range(4):
                    s = 0.0
                    for k in range(4):
                        s += self.m[k*4 + row] * other.m[col*4 + k]
                    r.m[col*4 + row] = s
            return r
        if isinstance(other, Vec4):
            x = sum(self.m[c*4+0]*other[c] for c in range(4))
            y = sum(self.m[c*4+1]*other[c] for c in range(4))
            z = sum(self.m[c*4+2]*other[c] for c in range(4))
            w = sum(self.m[c*4+3]*other[c] for c in range(4))
            return Vec4(x, y, z, w)
        if isinstance(other, Vec3):
            v = Vec4.from_vec3(other)
            return (self * v).xyz()
        return NotImplemented

    def transform_point(self, v):
        """Transform a Vec3 as a point (w=1), return Vec3 after perspective divide."""
        r = self * Vec4.from_vec3(v, 1.0)
        return r.to_vec3_div()

    def transform_direction(self, v):
        """Transform a Vec3 as a direction (w=0), return Vec3 (no translation/divide)."""
        r = self * Vec4.from_vec3(v, 0.0)
        return r.xyz()

    @staticmethod
    def translation(tx, ty, tz):
        m = Mat4.identity()
        m.m[12] = tx; m.m[13] = ty; m.m[14] = tz
        return m

    @staticmethod
    def scale(sx, sy, sz):
        m = Mat4()
        m.m[0] = sx; m.m[5] = sy; m.m[10] = sz; m.m[15] = 1.0
        return m

    @staticmethod
    def rotation_x(angle):
        c = math.cos(angle); s = math.sin(angle)
        m = Mat4.identity()
        m.m[5] = c; m.m[9] = -s; m.m[6] = s; m.m[10] = c
        return m

    @staticmethod
    def rotation_y(angle):
        c = math.cos(angle); s = math.sin(angle)
        m = Mat4.identity()
        m.m[0] = c; m.m[8] = s; m.m[2] = -s; m.m[10] = c
        return m

    @staticmethod
    def rotation_z(angle):
        c = math.cos(angle); s = math.sin(angle)
        m = Mat4.identity()
        m.m[0] = c; m.m[4] = -s; m.m[1] = s; m.m[5] = c
        return m

    @staticmethod
    def rotation_axis(axis, angle):
        ax = axis.normalize()
        c = math.cos(angle); s = math.sin(angle); t = 1-c
        x, y, z = ax.x, ax.y, ax.z
        m = Mat4.identity()
        m.set(0,0, t*x*x+c);   m.set(0,1, t*x*y-s*z); m.set(0,2, t*x*z+s*y)
        m.set(1,0, t*x*y+s*z); m.set(1,1, t*y*y+c);   m.set(1,2, t*y*z-s*x)
        m.set(2,0, t*x*z-s*y); m.set(2,1, t*y*z+s*x); m.set(2,2, t*z*z+c)
        return m

    @staticmethod
    def look_at(eye, center, up):
        f = (center - eye).normalize()
        r = f.cross(up).normalize()
        u = r.cross(f)
        m = Mat4.identity()
        m.set(0,0, r.x);  m.set(0,1, r.y);  m.set(0,2, r.z)
        m.set(1,0, u.x);  m.set(1,1, u.y);  m.set(1,2, u.z)
        m.set(2,0,-f.x);  m.set(2,1,-f.y);  m.set(2,2,-f.z)
        m.set(0,3, -r.dot(eye))
        m.set(1,3, -u.dot(eye))
        m.set(2,3,  f.dot(eye))
        return m

    @staticmethod
    def perspective(fov_y, aspect, near, far):
        t = math.tan(fov_y * 0.5)
        m = Mat4()
        m.set(0,0, 1.0/(aspect*t))
        m.set(1,1, 1.0/t)
        m.set(2,2, -(far+near)/(far-near))
        m.set(3,2, -1.0)
        m.set(2,3, -2.0*far*near/(far-near))
        return m

    @staticmethod
    def orthographic(left, right, bottom, top, near, far):
        m = Mat4()
        m.set(0,0, 2.0/(right-left))
        m.set(1,1, 2.0/(top-bottom))
        m.set(2,2, -2.0/(far-near))
        m.set(0,3, -(right+left)/(right-left))
        m.set(1,3, -(top+bottom)/(top-bottom))
        m.set(2,3, -(far+near)/(far-near))
        m.set(3,3, 1.0)
        return m

    def transpose(self):
        m = Mat4()
        for r in range(4):
            for c in range(4):
                m.set(r, c, self.get(c, r))
        return m

    def inverse(self):
        """Gauss-Jordan inversion."""
        a = list(self.m)
        b = [1.0 if i%5==0 else 0.0 for i in range(16)]  # identity
        # Pivot elimination
        for col in range(4):
            # find pivot
            best = col
            for row in range(col+1, 4):
                if abs(a[col*4+row]) > abs(a[col*4+best]):
                    best = row
            if best != col:
                for c in range(4):
                    a[c*4+col], a[c*4+best] = a[c*4+best], a[c*4+col]
                    b[c*4+col], b[c*4+best] = b[c*4+best], b[c*4+col]
            pivot = a[col*4+col]
            if abs(pivot) < 1e-12:
                raise ValueError("Matrix is singular")
            inv_p = 1.0/pivot
            for c in range(4):
                a[c*4+col] *= inv_p
                b[c*4+col] *= inv_p
            for row in range(4):
                if row == col: continue
                factor = a[col*4+row]
                for c in range(4):
                    a[c*4+row] -= factor * a[c*4+col]
                    b[c*4+row] -= factor * b[c*4+col]
        return Mat4(b)

    def normal_matrix(self):
        """Upper-left 3×3 of (M⁻¹)ᵀ — transforms normals correctly."""
        inv = self.inverse()
        return inv.transpose()
