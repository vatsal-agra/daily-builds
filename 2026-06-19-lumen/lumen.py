#!/usr/bin/env python3
"""Lumen — a physically-based path tracer from scratch.

Usage:
  python3 lumen.py render <scene> [options]
  python3 lumen.py demo
  python3 lumen.py gallery

Scenes: cornell | spheres | caustic | custom <file.json>
"""

import argparse
import base64
import json
import math
import os
import struct
import sys
import time
import zlib
from dataclasses import dataclass, field
from multiprocessing import Pool, cpu_count
from typing import List, Optional, Tuple

import numpy as np

# ─── PNG encoder (no Pillow needed) ──────────────────────────────────────────

def encode_png(pixels: np.ndarray) -> bytes:
    """Encode H×W×3 uint8 array as PNG bytes."""
    h, w = pixels.shape[:2]

    def chunk(ctype: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(ctype + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", crc)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    raw = bytearray()
    for row in pixels:
        raw.append(0)  # filter: None
        raw.extend(row.ravel().tobytes())
    idat = chunk(b"IDAT", zlib.compress(bytes(raw), level=1))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend

# ─── Vec3 helpers ─────────────────────────────────────────────────────────────

def v3(x=0.0, y=None, z=None) -> np.ndarray:
    if y is None:
        return np.array([float(x), float(x), float(x)])
    return np.array([float(x), float(y), float(z)])


def normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v3(0, 0, 1)


def reflect(v: np.ndarray, n: np.ndarray) -> np.ndarray:
    return v - 2 * np.dot(v, n) * n


def refract(uv: np.ndarray, n: np.ndarray, eta_ratio: float) -> Optional[np.ndarray]:
    cos_theta = min(float(np.dot(-uv, n)), 1.0)
    r_perp = eta_ratio * (uv + cos_theta * n)
    perp_sq = float(np.dot(r_perp, r_perp))
    if perp_sq >= 1.0:
        return None
    r_parallel = -math.sqrt(1.0 - perp_sq) * n
    return r_perp + r_parallel


def schlick(cosine: float, ref_idx: float) -> float:
    r0 = ((1 - ref_idx) / (1 + ref_idx)) ** 2
    return r0 + (1 - r0) * (1 - cosine) ** 5


def _rand_unit_sphere(rng: np.random.Generator) -> np.ndarray:
    while True:
        p = rng.uniform(-1.0, 1.0, 3)
        if np.dot(p, p) < 1.0:
            return p


def _rand_unit_disk(rng: np.random.Generator) -> np.ndarray:
    while True:
        p = rng.uniform(-1.0, 1.0, 2)
        if p[0] ** 2 + p[1] ** 2 < 1.0:
            return p


def _cosine_direction(rng: np.random.Generator) -> np.ndarray:
    r1, r2 = rng.random(), rng.random()
    z = math.sqrt(1.0 - r2)
    phi = 2 * math.pi * r1
    return np.array([math.cos(phi) * math.sqrt(r2), math.sin(phi) * math.sqrt(r2), z])


def _rand_to_sphere(rng, radius: float, dist_sq: float) -> np.ndarray:
    r1, r2 = rng.random(), rng.random()
    z = 1 + r2 * (math.sqrt(max(0.0, 1 - radius ** 2 / dist_sq)) - 1)
    phi = 2 * math.pi * r1
    s = math.sqrt(max(0.0, 1 - z * z))
    return np.array([math.cos(phi) * s, math.sin(phi) * s, z])


class ONB:
    """Orthonormal basis for hemisphere sampling."""
    def __init__(self, n: np.ndarray):
        self.w = normalize(n)
        a = v3(1, 0, 0) if abs(self.w[0]) < 0.9 else v3(0, 1, 0)
        self.v = normalize(np.cross(self.w, a))
        self.u = np.cross(self.w, self.v)

    def local(self, a: np.ndarray) -> np.ndarray:
        return a[0] * self.u + a[1] * self.v + a[2] * self.w


# ─── Ray + HitRecord ──────────────────────────────────────────────────────────

@dataclass
class Ray:
    origin: np.ndarray
    direction: np.ndarray

    def at(self, t: float) -> np.ndarray:
        return self.origin + t * self.direction


@dataclass
class Hit:
    t: float
    p: np.ndarray
    normal: np.ndarray
    front_face: bool
    material: object
    u: float = 0.0
    v: float = 0.0

    @staticmethod
    def make(t, p, outward_n, ray, mat, u=0.0, v=0.0) -> "Hit":
        ff = float(np.dot(ray.direction, outward_n)) < 0.0
        return Hit(t, p, outward_n if ff else -outward_n, ff, mat, u, v)


# ─── Textures ─────────────────────────────────────────────────────────────────

class SolidColor:
    def __init__(self, color):
        self.c = np.asarray(color, dtype=float)

    def value(self, u, v, p) -> np.ndarray:
        return self.c


class CheckerTexture:
    def __init__(self, c1, c2, scale=10.0):
        self.odd = SolidColor(c1)
        self.even = SolidColor(c2)
        self.scale = scale

    def value(self, u, v, p) -> np.ndarray:
        s = math.sin(self.scale * p[0]) * math.sin(self.scale * p[1]) * math.sin(self.scale * p[2])
        return self.odd.c if s < 0 else self.even.c


class PerlinTexture:
    """Gradient Perlin noise texture."""
    def __init__(self, c1, c2, scale=4.0, turbulence=0):
        self.c1 = np.asarray(c1, dtype=float)
        self.c2 = np.asarray(c2, dtype=float)
        self.scale = scale
        self.turb = turbulence
        rng = np.random.default_rng(12345)
        perm = np.arange(256)
        rng.shuffle(perm)
        self._perm = np.concatenate([perm, perm])
        vecs = rng.standard_normal((256, 3))
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        self._grad = vecs / np.where(norms > 0, norms, 1.0)

    def _noise(self, p: np.ndarray) -> float:
        x, y, z = p * self.scale
        ix, iy, iz = int(math.floor(x)) & 255, int(math.floor(y)) & 255, int(math.floor(z)) & 255
        fx, fy, fz = x - math.floor(x), y - math.floor(y), z - math.floor(z)
        ux = fx * fx * (3 - 2 * fx)
        uy = fy * fy * (3 - 2 * fy)
        uz = fz * fz * (3 - 2 * fz)
        pm = self._perm
        g = self._grad
        corners = []
        for di in range(2):
            for dj in range(2):
                for dk in range(2):
                    idx = pm[pm[pm[ix + di] + iy + dj] + iz + dk]
                    gv = g[idx]
                    corners.append(gv[0] * (fx - di) + gv[1] * (fy - dj) + gv[2] * (fz - dk))
        c000, c100, c010, c110, c001, c101, c011, c111 = corners
        val = (c000 * (1-ux)*(1-uy)*(1-uz) + c100 * ux*(1-uy)*(1-uz) +
               c010 * (1-ux)*uy*(1-uz) + c110 * ux*uy*(1-uz) +
               c001 * (1-ux)*(1-uy)*uz + c101 * ux*(1-uy)*uz +
               c011 * (1-ux)*uy*uz + c111 * ux*uy*uz)
        return 0.5 * (1 + val)

    def value(self, u, v, p) -> np.ndarray:
        if self.turb > 0:
            noise = sum(0.5 ** i * abs(2 * self._noise(p * (2 ** i)) - 1)
                        for i in range(self.turb))
            t = 0.5 * (1 + math.sin(self.scale * p[2] + 10 * noise))
        else:
            t = self._noise(p)
        return t * self.c1 + (1 - t) * self.c2


def _make_tex(src):
    """Coerce a color list/array to a SolidColor, or pass through a Texture."""
    if isinstance(src, (list, tuple, np.ndarray)):
        return SolidColor(src)
    return src


# ─── Materials ────────────────────────────────────────────────────────────────

class Lambertian:
    def __init__(self, albedo):
        self.tex = _make_tex(albedo)

    def scatter(self, ray_in: Ray, hit: Hit, rng) -> Optional[Tuple]:
        onb = ONB(hit.normal)
        direction = onb.local(_cosine_direction(rng))
        if np.dot(direction, direction) < 1e-14:
            direction = hit.normal
        scattered = Ray(hit.p, normalize(direction))
        attenuation = self.tex.value(hit.u, hit.v, hit.p)
        return scattered, attenuation, False  # not specular

    def emitted(self, u, v, p) -> np.ndarray:
        return v3(0)

    def scattering_pdf(self, ray_in: Ray, hit: Hit, scattered: Ray) -> float:
        cos = float(np.dot(hit.normal, normalize(scattered.direction)))
        return max(cos, 0.0) / math.pi


class Metal:
    def __init__(self, albedo, roughness=0.0):
        self.albedo = np.asarray(albedo, dtype=float)
        self.rough = min(max(float(roughness), 0.0), 1.0)

    def scatter(self, ray_in: Ray, hit: Hit, rng) -> Optional[Tuple]:
        reflected = reflect(normalize(ray_in.direction), hit.normal)
        if self.rough > 0:
            reflected = reflected + self.rough * _rand_unit_sphere(rng)
        direction = normalize(reflected)
        if np.dot(direction, hit.normal) <= 0:
            return None
        return Ray(hit.p, direction), self.albedo, True  # specular

    def emitted(self, u, v, p) -> np.ndarray:
        return v3(0)

    def scattering_pdf(self, *_) -> float:
        return 0.0


class Dielectric:
    def __init__(self, ior=1.5):
        self.ior = float(ior)

    def scatter(self, ray_in: Ray, hit: Hit, rng) -> Optional[Tuple]:
        eta = 1.0 / self.ior if hit.front_face else self.ior
        unit_d = normalize(ray_in.direction)
        cos_theta = min(float(np.dot(-unit_d, hit.normal)), 1.0)
        sin_theta = math.sqrt(1.0 - cos_theta ** 2)

        if eta * sin_theta > 1.0 or schlick(cos_theta, eta) > rng.random():
            direction = reflect(unit_d, hit.normal)
        else:
            refracted = refract(unit_d, hit.normal, eta)
            direction = refracted if refracted is not None else reflect(unit_d, hit.normal)

        return Ray(hit.p, normalize(direction)), v3(1), True  # specular

    def emitted(self, u, v, p) -> np.ndarray:
        return v3(0)

    def scattering_pdf(self, *_) -> float:
        return 0.0


class DiffuseLight:
    def __init__(self, color, intensity=1.0):
        self.color = np.asarray(color, dtype=float) * float(intensity)

    def scatter(self, *_) -> None:
        return None

    def emitted(self, u, v, p) -> np.ndarray:
        return self.color

    def scattering_pdf(self, *_) -> float:
        return 0.0


# ─── AABB ─────────────────────────────────────────────────────────────────────

class AABB:
    INF = 1e30

    def __init__(self, lo, hi):
        self.lo = np.asarray(lo, dtype=float)
        self.hi = np.asarray(hi, dtype=float)

    def hit(self, ray: Ray, t0: float, t1: float) -> bool:
        for i in range(3):
            d = ray.direction[i]
            if abs(d) < 1e-12:
                if ray.origin[i] < self.lo[i] or ray.origin[i] > self.hi[i]:
                    return False
                continue
            inv = 1.0 / d
            ta = (self.lo[i] - ray.origin[i]) * inv
            tb = (self.hi[i] - ray.origin[i]) * inv
            if inv < 0:
                ta, tb = tb, ta
            t0 = max(t0, ta)
            t1 = min(t1, tb)
            if t1 <= t0:
                return False
        return True

    @staticmethod
    def surround(a: "AABB", b: "AABB") -> "AABB":
        return AABB(np.minimum(a.lo, b.lo), np.maximum(a.hi, b.hi))

    @staticmethod
    def empty() -> "AABB":
        return AABB(v3(AABB.INF), v3(-AABB.INF))

    @property
    def centroid(self) -> np.ndarray:
        return 0.5 * (self.lo + self.hi)


# ─── Geometry ─────────────────────────────────────────────────────────────────

class Sphere:
    def __init__(self, center, radius, material):
        self.center = np.asarray(center, dtype=float)
        self.radius = float(radius)
        self.material = material
        e = v3(abs(self.radius))
        self.bbox = AABB(self.center - e, self.center + e)

    def hit(self, ray: Ray, tmin: float, tmax: float) -> Optional[Hit]:
        oc = ray.origin - self.center
        a = float(np.dot(ray.direction, ray.direction))
        hb = float(np.dot(oc, ray.direction))
        c = float(np.dot(oc, oc)) - self.radius ** 2
        disc = hb * hb - a * c
        if disc < 0:
            return None
        sqd = math.sqrt(disc)
        for root in ((-hb - sqd) / a, (-hb + sqd) / a):
            if tmin < root < tmax:
                p = ray.at(root)
                outward_n = (p - self.center) / self.radius
                theta = math.acos(max(-1.0, min(1.0, -outward_n[1])))
                phi = math.atan2(-outward_n[2], outward_n[0]) + math.pi
                return Hit.make(root, p, outward_n, ray, self.material,
                                phi / (2 * math.pi), theta / math.pi)
        return None

    def pdf_value(self, origin: np.ndarray, direction: np.ndarray) -> float:
        h = self.hit(Ray(origin, direction), 1e-4, 1e30)
        if h is None:
            return 0.0
        dist_sq = float(np.dot(self.center - origin, self.center - origin))
        cos_max = math.sqrt(max(0.0, 1 - self.radius ** 2 / dist_sq))
        solid_angle = 2 * math.pi * (1 - cos_max)
        return 1.0 / solid_angle if solid_angle > 0 else 0.0

    def random_dir(self, origin: np.ndarray, rng) -> np.ndarray:
        to_c = self.center - origin
        onb = ONB(to_c)
        return onb.local(_rand_to_sphere(rng, self.radius, float(np.dot(to_c, to_c))))


class Quad:
    """Planar quad: corner q, edges u and v (parallelogram q + s*u + t*v, s,t in [0,1])."""
    def __init__(self, q, u, v, material):
        self.q = np.asarray(q, dtype=float)
        self.u = np.asarray(u, dtype=float)
        self.v = np.asarray(v, dtype=float)
        self.material = material
        n_raw = np.cross(self.u, self.v)
        self.normal = normalize(n_raw)
        self.d = float(np.dot(self.normal, self.q))
        self.w = n_raw / float(np.dot(n_raw, n_raw))  # for barycentric
        self.area = float(np.linalg.norm(n_raw))
        corners = [self.q, self.q + self.u, self.q + self.v, self.q + self.u + self.v]
        stacked = np.stack(corners)
        self.bbox = AABB(stacked.min(axis=0) - 1e-4, stacked.max(axis=0) + 1e-4)

    def hit(self, ray: Ray, tmin: float, tmax: float) -> Optional[Hit]:
        denom = float(np.dot(self.normal, ray.direction))
        if abs(denom) < 1e-12:
            return None
        t = (self.d - float(np.dot(self.normal, ray.origin))) / denom
        if not (tmin < t < tmax):
            return None
        p = ray.at(t)
        local = p - self.q
        alpha = float(np.dot(self.w, np.cross(local, self.v)))
        beta = float(np.dot(self.w, np.cross(self.u, local)))
        if not (0.0 <= alpha <= 1.0 and 0.0 <= beta <= 1.0):
            return None
        return Hit.make(t, p, self.normal, ray, self.material, alpha, beta)

    def pdf_value(self, origin: np.ndarray, direction: np.ndarray) -> float:
        h = self.hit(Ray(origin, direction), 1e-4, 1e30)
        if h is None:
            return 0.0
        dist_sq = h.t * h.t * float(np.dot(direction, direction))
        cos = abs(float(np.dot(normalize(direction), h.normal)))
        return dist_sq / (cos * self.area) if cos > 1e-12 else 0.0

    def random_dir(self, origin: np.ndarray, rng) -> np.ndarray:
        p = self.q + rng.random() * self.u + rng.random() * self.v
        return normalize(p - origin)


class Box:
    """Axis-aligned box from 6 quads with correct outward normals."""
    def __init__(self, a, b, material):
        a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
        mn, mx = np.minimum(a, b), np.maximum(a, b)
        dx = np.array([mx[0]-mn[0], 0, 0])
        dy = np.array([0, mx[1]-mn[1], 0])
        dz = np.array([0, 0, mx[2]-mn[2]])
        # Winding chosen so cross(u,v) gives outward normal for each face.
        # -z face: cross(dy, dx) = (0,0,-1)*scale → outward -Z
        # +z face: cross(dx, dy) = (0,0,+1)*scale → outward +Z
        # -y face: cross(dx, dz) = (0,-1,0)*scale → outward -Y
        # +y face: cross(dz, dx) = (0,+1,0)*scale → outward +Y
        # -x face: cross(dz, dy) = (-1,0,0)*scale → outward -X
        # +x face: cross(dy, dz) = (+1,0,0)*scale → outward +X
        self.sides = [
            Quad(mn,        dy, dx, material),  # -z face (front)
            Quad(mn + dz,   dx, dy, material),  # +z face (back)
            Quad(mn,        dx, dz, material),  # -y face (bottom)
            Quad(mn + dy,   dz, dx, material),  # +y face (top)
            Quad(mn,        dz, dy, material),  # -x face (left)
            Quad(mn + dx,   dy, dz, material),  # +x face (right)
        ]
        self.bbox = AABB(mn - 1e-4, mx + 1e-4)

    def hit(self, ray: Ray, tmin: float, tmax: float) -> Optional[Hit]:
        closest = None
        for s in self.sides:
            h = s.hit(ray, tmin, tmax)
            if h is not None:
                tmax = h.t
                closest = h
        return closest


class Translate:
    def __init__(self, obj, offset):
        self.obj = obj
        self.off = np.asarray(offset, dtype=float)
        b = obj.bbox
        self.bbox = AABB(b.lo + self.off, b.hi + self.off)

    def hit(self, ray: Ray, tmin: float, tmax: float) -> Optional[Hit]:
        moved = Ray(ray.origin - self.off, ray.direction)
        h = self.obj.hit(moved, tmin, tmax)
        if h is None:
            return None
        h.p = h.p + self.off
        return h


class RotateY:
    def __init__(self, obj, angle_deg: float):
        a = math.radians(angle_deg)
        self.sin_a = math.sin(a)
        self.cos_a = math.cos(a)
        self.obj = obj
        # Compute rotated bounding box
        b = obj.bbox
        lo, hi = b.lo, b.hi
        corners = [[lo[0], lo[1], lo[2]], [hi[0], lo[1], lo[2]],
                   [lo[0], hi[1], lo[2]], [hi[0], hi[1], lo[2]],
                   [lo[0], lo[1], hi[2]], [hi[0], lo[1], hi[2]],
                   [lo[0], hi[1], hi[2]], [hi[0], hi[1], hi[2]]]
        pts = []
        for c in corners:
            x = self.cos_a * c[0] + self.sin_a * c[2]
            z = -self.sin_a * c[0] + self.cos_a * c[2]
            pts.append([x, c[1], z])
        pts = np.array(pts)
        self.bbox = AABB(pts.min(axis=0), pts.max(axis=0))

    def _rot_inv(self, v: np.ndarray) -> np.ndarray:
        return np.array([self.cos_a * v[0] - self.sin_a * v[2], v[1],
                         self.sin_a * v[0] + self.cos_a * v[2]])

    def _rot_fwd(self, v: np.ndarray) -> np.ndarray:
        return np.array([self.cos_a * v[0] + self.sin_a * v[2], v[1],
                        -self.sin_a * v[0] + self.cos_a * v[2]])

    def hit(self, ray: Ray, tmin: float, tmax: float) -> Optional[Hit]:
        ro = self._rot_inv(ray.origin)
        rd = self._rot_inv(ray.direction)
        h = self.obj.hit(Ray(ro, rd), tmin, tmax)
        if h is None:
            return None
        h.p = self._rot_fwd(h.p)
        h.normal = self._rot_fwd(h.normal)
        return h


# ─── BVH ──────────────────────────────────────────────────────────────────────

class BVH:
    def __init__(self, objects: list, rng=None):
        if rng is None:
            rng = np.random.default_rng(0)
        n = len(objects)
        if n == 0:
            raise ValueError("Empty BVH")
        elif n == 1:
            self.left = self.right = objects[0]
        elif n == 2:
            self.left, self.right = objects[0], objects[1]
        else:
            # Choose longest axis for split
            bboxes = [o.bbox for o in objects]
            lo = np.array([b.lo for b in bboxes]).min(axis=0)
            hi = np.array([b.hi for b in bboxes]).max(axis=0)
            axis = int(np.argmax(hi - lo))
            objects = sorted(objects, key=lambda o: o.bbox.centroid[axis])
            mid = n // 2
            self.left = BVH(objects[:mid], rng)
            self.right = BVH(objects[mid:], rng)
        self.bbox = AABB.surround(self.left.bbox, self.right.bbox)

    def hit(self, ray: Ray, tmin: float, tmax: float) -> Optional[Hit]:
        if not self.bbox.hit(ray, tmin, tmax):
            return None
        h_left = self.left.hit(ray, tmin, tmax)
        h_right = self.right.hit(ray, tmin, h_left.t if h_left else tmax)
        return h_right if h_right else h_left


class World:
    """Scene container."""
    def __init__(self, objects: list = None):
        self.objects: list = objects or []
        self._bvh: Optional[BVH] = None

    def add(self, obj):
        self.objects.append(obj)
        self._bvh = None

    def build_bvh(self):
        if self.objects:
            self._bvh = BVH(self.objects)

    def hit(self, ray: Ray, tmin: float, tmax: float) -> Optional[Hit]:
        if self._bvh:
            return self._bvh.hit(ray, tmin, tmax)
        closest = None
        for obj in self.objects:
            h = obj.hit(ray, tmin, tmax)
            if h is not None:
                tmax = h.t
                closest = h
        return closest


# ─── Camera ───────────────────────────────────────────────────────────────────

class Camera:
    def __init__(self, lookfrom, lookat, vup, vfov_deg, aspect,
                 aperture=0.0, focus_dist=None):
        h = math.tan(math.radians(vfov_deg) / 2)
        vp_h = 2.0 * h
        vp_w = aspect * vp_h
        lf = np.asarray(lookfrom, dtype=float)
        la = np.asarray(lookat, dtype=float)
        up = np.asarray(vup, dtype=float)
        w = normalize(lf - la)
        u = normalize(np.cross(up, w))
        v = np.cross(w, u)
        if focus_dist is None:
            focus_dist = float(np.linalg.norm(lf - la))
        self.origin = lf
        self.horizontal = focus_dist * vp_w * u
        self.vertical = focus_dist * vp_h * v
        self.lower_left = lf - self.horizontal / 2 - self.vertical / 2 - focus_dist * w
        self.lens_r = aperture / 2.0
        self.u = u
        self.v = v

    def get_ray(self, s: float, t: float, rng) -> Ray:
        if self.lens_r > 1e-12:
            rd = self.lens_r * _rand_unit_disk(rng)
            offset = self.u * rd[0] + self.v * rd[1]
        else:
            offset = v3(0)
        d = self.lower_left + s * self.horizontal + t * self.vertical - self.origin - offset
        return Ray(self.origin + offset, normalize(d))


# ─── Integrator ───────────────────────────────────────────────────────────────

def _bg_black(_ray: Ray) -> np.ndarray:
    return v3(0)


def _bg_sky(ray: Ray) -> np.ndarray:
    t = 0.5 * (normalize(ray.direction)[1] + 1.0)
    return (1 - t) * v3(1) + t * np.array([0.5, 0.7, 1.0])


def path_trace(ray: Ray, world: World, lights: list, bg_fn,
               max_depth: int, rng) -> np.ndarray:
    """Unbiased path tracer with NEE for diffuse surfaces and Russian roulette."""
    color = v3(0)
    throughput = v3(1)
    last_specular = True  # first hit: always show emission

    for depth in range(max_depth):
        h = world.hit(ray, 1e-4, 1e30)
        if h is None:
            color += throughput * bg_fn(ray)
            break

        emitted = h.material.emitted(h.u, h.v, h.p)
        # Only add emission if previous bounce was specular (avoids double-counting with NEE)
        if last_specular:
            color += throughput * emitted

        result = h.material.scatter(ray, h, rng)
        if result is None:
            break  # absorbed (e.g. hit a light from inside)

        scattered, attenuation, is_specular = result
        last_specular = is_specular

        # NEE: for diffuse hits, directly sample lights
        if not is_specular and lights:
            nee = v3(0)
            for light in lights:
                ld = light.random_dir(h.p, rng)
                light_pdf = light.pdf_value(h.p, ld)
                if light_pdf <= 0:
                    continue
                shadow_ray = Ray(h.p, ld)
                sh = world.hit(shadow_ray, 1e-4, 1e30)
                if sh is None:
                    continue
                le = sh.material.emitted(sh.u, sh.v, sh.p)
                if not np.any(le > 0):
                    continue
                brdf_pdf = h.material.scattering_pdf(ray, h, shadow_ray)
                if brdf_pdf <= 0:
                    continue
                nee += le * attenuation * brdf_pdf / light_pdf
            color += throughput * nee

        ray = scattered
        throughput = throughput * attenuation

        # Russian roulette: terminate dim paths without bias
        if depth >= 3:
            p = float(np.clip(throughput.max(), 0.05, 0.95))
            if rng.random() > p:
                break
            throughput /= p

    return color


# ─── Tone mapping ─────────────────────────────────────────────────────────────

def aces_tonemap(x: np.ndarray) -> np.ndarray:
    """ACES filmic tone mapping curve."""
    a, b, c, d, e = 2.51, 0.03, 2.43, 0.59, 0.14
    return np.clip((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0)


def to_uint8(linear: np.ndarray, gamma: float = 2.2) -> np.ndarray:
    """ACES tone map → gamma correct → uint8."""
    mapped = aces_tonemap(linear)
    gc = np.power(np.clip(mapped, 0.0, 1.0), 1.0 / gamma)
    return (gc * 255.499).astype(np.uint8)


# ─── Built-in scenes ──────────────────────────────────────────────────────────

def make_cornell_box():
    """Classic Cornell box — two white boxes + glass sphere."""
    red = Lambertian([0.65, 0.05, 0.05])
    white = Lambertian([0.73, 0.73, 0.73])
    green = Lambertian([0.12, 0.45, 0.15])
    light = DiffuseLight([1.0, 1.0, 1.0], intensity=15.0)

    area_light = Quad([213, 554, 227], [130, 0, 0], [0, 0, 105], light)

    world = World([
        # Red wall — x=555 (appears on left in rendered image with this camera)
        Quad([555, 0, 0], [0, 555, 0],   [0, 0, 555],   red),
        # Green wall — x=0 (appears on right in rendered image)
        Quad([0, 0, 0],   [0, 555, 0],   [0, 0, 555],   green),
        # Floor — y=0
        Quad([0, 0, 0],   [555, 0, 0],   [0, 0, 555],   white),
        # Ceiling — y=555
        Quad([0, 555, 0], [555, 0, 0],   [0, 0, 555],   white),
        # Back wall — z=555
        Quad([0, 0, 555], [555, 0, 0],   [0, 555, 0],   white),
        # Light on ceiling
        area_light,
        # Short white box (right of center, rotated 15°)
        Translate(RotateY(Box([0,0,0], [165,165,165], white),  15), [130, 0,  65]),
        # Tall white box (left of center, rotated -18°)
        Translate(RotateY(Box([0,0,0], [165,330,165], white), -18), [265, 0, 295]),
        # Glass sphere sitting on top of the short box
        Sphere([185, 240, 145], 75, Dielectric(1.5)),
    ])
    world.build_bvh()

    lights = [area_light]

    cam = Camera(
        lookfrom=[278, 278, -800],
        lookat=[278, 278, 0],
        vup=[0, 1, 0],
        vfov_deg=40,
        aspect=1.0,
    )
    return world, lights, _bg_black, cam


def make_spheres_scene():
    """Metallic spheres on a checker ground."""
    checker = CheckerTexture([0.2, 0.3, 0.1], [0.9, 0.9, 0.9], scale=10.0)
    ground = Lambertian(checker)
    marble = PerlinTexture([0.8, 0.5, 0.3], [0.2, 0.1, 0.05], scale=4.0, turbulence=7)

    world = World([
        Sphere([0, -1000, 0], 1000, ground),
        # Center: glass
        Sphere([0, 1, 0], 1.0, Dielectric(1.5)),
        # Left: lambertian with marble texture
        Sphere([-4, 1, 0], 1.0, Lambertian(marble)),
        # Right: gold metal
        Sphere([4, 1, 0], 1.0, Metal([0.7, 0.6, 0.5], roughness=0.0)),
        # Extra spheres for variety
        Sphere([-2, 0.5, 2], 0.5, Metal([0.8, 0.8, 0.9], roughness=0.3)),
        Sphere([2, 0.5, 2], 0.5, Lambertian([0.4, 0.2, 0.7])),
        Sphere([0, 0.5, 3], 0.5, Metal([0.9, 0.6, 0.2], roughness=0.1)),
        Sphere([-2, 0.5, -2], 0.5, Dielectric(1.3)),
        Sphere([2, 0.5, -2], 0.5, Lambertian([0.1, 0.7, 0.3])),
    ])
    world.build_bvh()

    cam = Camera(
        lookfrom=[13, 2, 3],
        lookat=[0, 0, 0],
        vup=[0, 1, 0],
        vfov_deg=20,
        aspect=16 / 9,
        aperture=0.08,
        focus_dist=10.0,
    )
    return world, [], _bg_sky, cam


def make_caustic_scene():
    """Glass sphere + area light showing caustic ring."""
    white_diffuse = Lambertian([0.8, 0.8, 0.8])
    glass = Dielectric(1.5)
    light = DiffuseLight([1.0, 0.95, 0.85], intensity=10.0)
    checker = CheckerTexture([0.6, 0.6, 0.6], [0.3, 0.3, 0.3], scale=5.0)
    floor_mat = Lambertian(checker)

    world = World([
        # Floor
        Quad([0, 0, 0], [10, 0, 0], [0, 0, 10], floor_mat),
        # Back wall
        Quad([0, 0, 10], [10, 0, 0], [0, 10, 0], white_diffuse),
        # Left wall
        Quad([0, 0, 0], [0, 0, 10], [0, 10, 0], Lambertian([0.65, 0.05, 0.05])),
        # Glass sphere
        Sphere([5, 1.5, 5], 1.5, glass),
        # Area light above
        Quad([3, 8, 3], [4, 0, 0], [0, 0, 4], light),
    ])
    world.build_bvh()
    lights = [Quad([3, 8, 3], [4, 0, 0], [0, 0, 4], light)]

    cam = Camera(
        lookfrom=[5, 5, -3],
        lookat=[5, 1.5, 5],
        vup=[0, 1, 0],
        vfov_deg=45,
        aspect=16 / 9,
    )
    return world, lights, _bg_black, cam


# ─── Scene from JSON ──────────────────────────────────────────────────────────

_MAT_REGISTRY = {
    "lambertian": lambda d: Lambertian(d.get("albedo", [0.5, 0.5, 0.5])),
    "metal":      lambda d: Metal(d.get("albedo", [0.8, 0.8, 0.8]), d.get("roughness", 0.0)),
    "dielectric": lambda d: Dielectric(d.get("ior", 1.5)),
    "light":      lambda d: DiffuseLight(d.get("color", [1,1,1]), d.get("intensity", 1.0)),
}


def _parse_material(d: dict):
    t = d.get("type", "lambertian")
    if t not in _MAT_REGISTRY:
        raise ValueError(f"Unknown material type: {t!r}")
    return _MAT_REGISTRY[t](d)


def load_scene_json(path: str):
    with open(path) as f:
        data = json.load(f)

    mats = {k: _parse_material(v) for k, v in data.get("materials", {}).items()}

    world = World()
    lights = []
    for obj in data.get("objects", []):
        mat = mats[obj["material"]]
        t = obj["type"]
        if t == "sphere":
            s = Sphere(obj["center"], obj["radius"], mat)
            world.add(s)
            if isinstance(mat, DiffuseLight):
                lights.append(s)
        elif t == "quad":
            q = Quad(obj["q"], obj["u"], obj["v"], mat)
            world.add(q)
            if isinstance(mat, DiffuseLight):
                lights.append(q)
        elif t == "box":
            world.add(Box(obj["a"], obj["b"], mat))
        else:
            raise ValueError(f"Unknown object type: {t!r}")
    world.build_bvh()

    cam_d = data["camera"]
    bg_name = data.get("background", "black")
    bg_fn = _bg_sky if bg_name == "sky" else _bg_black

    cam = Camera(
        lookfrom=cam_d["from"],
        lookat=cam_d["to"],
        vup=cam_d.get("up", [0, 1, 0]),
        vfov_deg=cam_d.get("vfov", 40),
        aspect=cam_d.get("aspect", 1.0),
        aperture=cam_d.get("aperture", 0.0),
        focus_dist=cam_d.get("focus_dist", None),
    )
    return world, lights, bg_fn, cam


SCENES = {
    "cornell": make_cornell_box,
    "spheres": make_spheres_scene,
    "caustic": make_caustic_scene,
}


# ─── Renderer ─────────────────────────────────────────────────────────────────

def _render_tile(args):
    """Worker function — picklable by multiprocessing."""
    scene_name, json_path, cam_cfg, tile, W, H, spp, max_depth, seed = args
    rng = np.random.default_rng(seed)

    if json_path:
        world, lights, bg_fn, _cam = load_scene_json(json_path)
    else:
        world, lights, bg_fn, _cam = SCENES[scene_name]()

    cam = Camera(**cam_cfg)

    x0, y0, x1, y1 = tile
    tw, th = x1 - x0, y1 - y0
    buf = np.zeros((th, tw, 3))

    for jj in range(th):
        j = y0 + jj
        for ii in range(tw):
            i = x0 + ii
            px = v3(0)
            for _ in range(spp):
                s = (i + rng.random()) / (W - 1)
                # Flip vertical: row 0 of image = top of viewport (j small → t large)
                t = (H - 1 - j + rng.random()) / (H - 1)
                ray = cam.get_ray(s, t, rng)
                px += path_trace(ray, world, lights, bg_fn, max_depth, rng)
            buf[jj, ii] = px / spp

    return x0, y0, buf


def _cam_to_dict(cam: Camera) -> dict:
    """Convert Camera to a JSON-serialisable dict for worker reconstruction."""
    # We need to recover constructor arguments from the Camera object — impossible
    # without storing them. So we store them at construction time via a wrapper.
    raise RuntimeError("Use _CamSpec instead")


@dataclass
class _CamSpec:
    lookfrom: list
    lookat: list
    vup: list
    vfov_deg: float
    aspect: float
    aperture: float = 0.0
    focus_dist: float = None


def render(scene_name: str, json_path: str, cam_spec: _CamSpec,
           width: int, height: int, spp: int,
           max_depth: int = 10, workers: int = 1,
           verbose: bool = True) -> np.ndarray:
    """Render the scene, return linear HDR image (H×W×3 float)."""
    TILE = 32
    tiles = []
    for y in range(0, height, TILE):
        for x in range(0, width, TILE):
            tiles.append((x, y, min(x + TILE, width), min(y + TILE, height)))

    cam_cfg = {
        "lookfrom": cam_spec.lookfrom,
        "lookat": cam_spec.lookat,
        "vup": cam_spec.vup,
        "vfov_deg": cam_spec.vfov_deg,
        "aspect": cam_spec.aspect,
        "aperture": cam_spec.aperture,
        "focus_dist": cam_spec.focus_dist,
    }

    args_list = [
        (scene_name, json_path, cam_cfg, t, width, height, spp, max_depth, i * 17 + 1)
        for i, t in enumerate(tiles)
    ]

    image = np.zeros((height, width, 3))
    n_tiles = len(tiles)
    done = 0
    t0 = time.time()

    if workers <= 1:
        for args in args_list:
            x0, y0, buf = _render_tile(args)
            tile = args[3]
            x1, y1 = tile[2], tile[3]
            image[y0:y1, x0:x1] = buf
            done += 1
            if verbose:
                pct = 100 * done / n_tiles
                elapsed = time.time() - t0
                eta = elapsed / done * (n_tiles - done) if done else 0
                print(f"\r  {pct:5.1f}%  {elapsed:5.1f}s elapsed  {eta:5.1f}s ETA",
                      end="", flush=True)
    else:
        with Pool(workers) as pool:
            for x0, y0, buf in pool.imap_unordered(_render_tile, args_list):
                y1 = min(y0 + TILE, height)
                x1 = min(x0 + TILE, width)
                image[y0:y1, x0:x1] = buf
                done += 1
                if verbose:
                    pct = 100 * done / n_tiles
                    elapsed = time.time() - t0
                    eta = elapsed / done * (n_tiles - done) if done else 0
                    print(f"\r  {pct:5.1f}%  {elapsed:5.1f}s elapsed  {eta:5.1f}s ETA",
                          end="", flush=True)

    if verbose:
        print(f"\r  100.0%  {time.time()-t0:.1f}s total" + " " * 30)

    return image


# ─── HTML gallery ─────────────────────────────────────────────────────────────

def make_gallery(renders: list, output_path: str):
    """renders: list of (title, png_bytes, stats_str)."""
    cards = []
    for title, png_bytes, stats in renders:
        b64 = base64.b64encode(png_bytes).decode()
        cards.append(f"""
        <div class="card">
          <img src="data:image/png;base64,{b64}" alt="{title}">
          <div class="caption">
            <strong>{title}</strong>
            <pre>{stats}</pre>
          </div>
        </div>""")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Lumen — Path Tracer Gallery</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #111; color: #eee; font-family: 'Segoe UI', sans-serif;
         padding: 2rem; }}
  h1 {{ text-align: center; font-size: 2rem; margin-bottom: 0.3rem;
       background: linear-gradient(90deg,#f60,#f06,#60f); -webkit-background-clip: text;
       -webkit-text-fill-color: transparent; }}
  .subtitle {{ text-align: center; color: #888; margin-bottom: 2rem; font-size: 0.9rem; }}
  .gallery {{ display: flex; flex-wrap: wrap; gap: 1.5rem; justify-content: center; }}
  .card {{ background: #1e1e1e; border: 1px solid #333; border-radius: 10px;
           overflow: hidden; max-width: 700px; transition: transform 0.2s; }}
  .card:hover {{ transform: scale(1.01); }}
  .card img {{ display: block; width: 100%; }}
  .caption {{ padding: 0.8rem 1rem; }}
  .caption strong {{ font-size: 1.1rem; color: #ff9944; }}
  pre {{ font-size: 0.78rem; color: #aaa; margin-top: 0.4rem; white-space: pre-wrap; }}
</style>
</head>
<body>
<h1>Lumen</h1>
<p class="subtitle">Physically-based path tracer · built from scratch in Python</p>
<div class="gallery">
  {''.join(cards)}
</div>
</body>
</html>"""
    with open(output_path, "w") as f:
        f.write(html)
    print(f"Gallery saved → {output_path}")


# ─── CLI ──────────────────────────────────────────────────────────────────────

def _scene_cam(name: str, json_path: str = None) -> Tuple:
    if json_path:
        world, lights, bg, cam = load_scene_json(json_path)
        # Extract cam spec from the Camera object — we need to store separately
        raise ValueError("Use --scene for built-in scenes or pass cam in JSON")
    fn = SCENES.get(name)
    if fn is None:
        raise ValueError(f"Unknown scene {name!r}. Choose: {list(SCENES)}")
    _, _, _, cam = fn()
    return cam


_DEFAULT_CAMS = {
    "cornell": _CamSpec([278, 278, -800], [278, 278, 0], [0, 1, 0], 40, 1.0),
    "spheres": _CamSpec([13, 2, 3], [0, 0, 0], [0, 1, 0], 20, 16/9, aperture=0.08, focus_dist=10.0),
    "caustic": _CamSpec([5, 5, -3], [5, 1.5, 5], [0, 1, 0], 45, 16/9),
}


def cmd_render(args):
    scene_name = args.scene
    json_path = None
    if scene_name == "custom":
        if not args.file:
            print("--file required for custom scene", file=sys.stderr)
            sys.exit(1)
        json_path = args.file
        world, lights, bg, cam_obj = load_scene_json(json_path)
        cam_spec = _CamSpec(
            lookfrom=list(cam_obj.origin),
            lookat=list(cam_obj.lower_left + cam_obj.horizontal/2 + cam_obj.vertical/2 + cam_obj.origin),
            vup=[0, 1, 0], vfov_deg=40, aspect=args.width/args.height,
        )
        # Actually, JSON loader handles cam directly — just rebuild from JSON
        scene_name = None
    else:
        if scene_name not in _DEFAULT_CAMS:
            print(f"Unknown scene {scene_name!r}. Choose: {list(SCENES)}", file=sys.stderr)
            sys.exit(1)
        cam_spec = _DEFAULT_CAMS[scene_name]
        cam_spec.aspect = args.width / args.height

    workers = args.workers or max(1, cpu_count())
    print(f"Rendering {args.scene} | {args.width}×{args.height} | {args.spp} spp | "
          f"{workers} workers | depth {args.depth}")
    t0 = time.time()
    img_linear = render(
        scene_name, json_path, cam_spec,
        args.width, args.height, args.spp,
        max_depth=args.depth, workers=workers, verbose=True,
    )
    elapsed = time.time() - t0
    img8 = to_uint8(img_linear)
    png = encode_png(img8)
    out = args.output or f"{args.scene}.png"
    with open(out, "wb") as f:
        f.write(png)
    print(f"Saved {out}  ({args.width}×{args.height}, {args.spp} spp, {elapsed:.1f}s)")


def cmd_demo(args):
    """Render all three scenes at low resolution and open the gallery."""
    renders = []
    configs = [
        ("cornell", 96,  96,  8),
        ("spheres", 128, 72,  8),
        ("caustic", 128, 72,  8),
    ]
    workers = max(1, cpu_count())
    for name, w, h, spp in configs:
        print(f"\n── {name.upper()} ─────────────────────────────────")
        cam = _DEFAULT_CAMS[name]
        cam.aspect = w / h
        t0 = time.time()
        img_linear = render(name, None, cam, w, h, spp,
                            max_depth=10, workers=workers, verbose=True)
        elapsed = time.time() - t0
        img8 = to_uint8(img_linear)
        png = encode_png(img8)
        with open(f"{name}.png", "wb") as f:
            f.write(png)
        stats = (f"Resolution: {w}×{h}\n"
                 f"Samples/px: {spp}\n"
                 f"Render time: {elapsed:.1f}s\n"
                 f"Mrays/s: {w*h*spp/elapsed/1e6:.2f}")
        renders.append((name.upper(), png, stats))
        print(f"  → {name}.png  ({elapsed:.1f}s)")
    make_gallery(renders, "gallery.html")
    print("\n✓ Open gallery.html in your browser to view all renders.")


def cmd_gallery(args):
    """(Re-)build gallery from existing PNG files."""
    renders = []
    for name in ("cornell", "spheres", "caustic"):
        path = f"{name}.png"
        if os.path.exists(path):
            with open(path, "rb") as f:
                renders.append((name.upper(), f.read(), f"From file: {path}"))
    if not renders:
        print("No rendered PNG files found. Run 'demo' first.")
        sys.exit(1)
    make_gallery(renders, "gallery.html")


def main():
    ap = argparse.ArgumentParser(description="Lumen — path tracer")
    sub = ap.add_subparsers(dest="command", required=True)

    # render
    r = sub.add_parser("render", help="Render a scene to PNG")
    r.add_argument("scene", choices=list(SCENES) + ["custom"])
    r.add_argument("--file", help="JSON scene file (for custom)")
    r.add_argument("-W", "--width", type=int, default=512)
    r.add_argument("-H", "--height", type=int, default=512)
    r.add_argument("--spp", type=int, default=64, help="Samples per pixel")
    r.add_argument("--depth", type=int, default=10, help="Max bounce depth")
    r.add_argument("--workers", type=int, default=0, help="0=auto")
    r.add_argument("-o", "--output", help="Output PNG path")

    # demo
    d = sub.add_parser("demo", help="Render all scenes (low-res) + gallery")

    # gallery
    g = sub.add_parser("gallery", help="Rebuild gallery from existing PNGs")

    args = ap.parse_args()
    {
        "render": cmd_render,
        "demo": cmd_demo,
        "gallery": cmd_gallery,
    }[args.command](args)


if __name__ == "__main__":
    main()
