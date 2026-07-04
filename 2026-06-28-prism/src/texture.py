"""Texture: procedural textures and bilinear sampling."""
import math
import array


class Texture:
    def __init__(self, width, height, data=None):
        self.width = width
        self.height = height
        if data is None:
            self.data = bytearray(width * height * 3)
        else:
            self.data = bytearray(data)

    def _idx(self, x, y): return (y * self.width + x) * 3

    def set_pixel(self, x, y, r, g, b):
        i = self._idx(x, y)
        self.data[i] = int(r); self.data[i+1] = int(g); self.data[i+2] = int(b)

    def get_pixel_raw(self, x, y):
        x = x % self.width; y = y % self.height
        i = self._idx(x, y)
        return self.data[i]/255.0, self.data[i+1]/255.0, self.data[i+2]/255.0

    def sample(self, u, v):
        """Bilinear sample at normalized (u,v) with wrapping."""
        u = u - math.floor(u)
        v = v - math.floor(v)
        fx = u * (self.width - 1)
        fy = v * (self.height - 1)
        x0 = int(fx); y0 = int(fy)
        x1 = (x0+1) % self.width; y1 = (y0+1) % self.height
        tx = fx - x0; ty = fy - y0

        r00, g00, b00 = self.get_pixel_raw(x0, y0)
        r10, g10, b10 = self.get_pixel_raw(x1, y0)
        r01, g01, b01 = self.get_pixel_raw(x0, y1)
        r11, g11, b11 = self.get_pixel_raw(x1, y1)

        def blerp(a, b, c, d): return (a*(1-tx)+b*tx)*(1-ty) + (c*(1-tx)+d*tx)*ty
        return blerp(r00,r10,r01,r11), blerp(g00,g10,g01,g11), blerp(b00,b10,b01,b11)


# ── Procedural texture generators ──

def checkerboard(w, h, color_a=(0.9,0.9,0.9), color_b=(0.1,0.1,0.1), tiles=8):
    tex = Texture(w, h)
    for y in range(h):
        for x in range(w):
            tx = int(x * tiles / w); ty = int(y * tiles / h)
            c = color_a if (tx+ty) % 2 == 0 else color_b
            tex.set_pixel(x, y, int(c[0]*255), int(c[1]*255), int(c[2]*255))
    return tex


def uv_grid(w, h):
    """Debug UV grid: red=U, green=V, lines at 0.1 intervals."""
    tex = Texture(w, h)
    for y in range(h):
        for x in range(w):
            u = x / (w-1); v = y / (h-1)
            # Grid lines at every 0.1
            in_line = (u % 0.1 < 0.01) or (v % 0.1 < 0.01)
            if in_line:
                r, g, b = 0, 0, 0
            else:
                r = int(u * 255); g = int(v * 255); b = 64
            tex.set_pixel(x, y, r, g, b)
    return tex


def _smooth_noise(x, y):
    """Simple value noise via integer hash."""
    def hash_f(a, b):
        h = (a*1231 + b*7919 + 13) & 0x7FFFFFFF
        h = (h ^ (h >> 16)) * 0x45d9f3b & 0x7FFFFFFF
        h = (h ^ (h >> 16))
        return (h & 0xFFFF) / 0xFFFF
    ix = int(math.floor(x)); iy = int(math.floor(y))
    fx = x - ix; fy = y - iy
    # Smoothstep
    ux = fx*fx*(3-2*fx); uy = fy*fy*(3-2*fy)
    return (hash_f(ix,iy)*(1-ux)*(1-uy) +
            hash_f(ix+1,iy)*ux*(1-uy) +
            hash_f(ix,iy+1)*(1-ux)*uy +
            hash_f(ix+1,iy+1)*ux*uy)


def marble(w, h, freq=4.0, octaves=4):
    """Marble-like procedural texture."""
    tex = Texture(w, h)
    for y in range(h):
        for x in range(w):
            u = x/w; v = y/h
            turbulence = 0.0
            amp = 1.0; frq = freq
            for _ in range(octaves):
                turbulence += amp * _smooth_noise(u*frq, v*frq)
                amp *= 0.5; frq *= 2
            val = math.sin(u*4*math.pi + turbulence*2)*0.5 + 0.5
            # Map to marble colors: cream + dark veins
            r = int(max(0,min(255, (0.3 + val*0.65)*255)))
            g = int(max(0,min(255, (0.25 + val*0.6)*255)))
            b = int(max(0,min(255, (0.2 + val*0.55)*255)))
            tex.set_pixel(x, y, r, g, b)
    return tex


def gradient(w, h, color_top=(0.1,0.2,0.8), color_bot=(0.8,0.5,0.1)):
    tex = Texture(w, h)
    for y in range(h):
        t = y / (h-1)
        r = color_top[0]*(1-t)+color_bot[0]*t
        g = color_top[1]*(1-t)+color_bot[1]*t
        b = color_top[2]*(1-t)+color_bot[2]*t
        for x in range(w):
            tex.set_pixel(x, y, int(r*255), int(g*255), int(b*255))
    return tex


def earth_like(w, h):
    """Procedural blue-green sphere texture (no image file needed)."""
    tex = Texture(w, h)
    for y in range(h):
        lat = (y/h - 0.5)*math.pi
        for x in range(w):
            lon = (x/w)*2*math.pi
            # Continent noise
            nx = math.cos(lat)*math.cos(lon)
            ny = math.cos(lat)*math.sin(lon)
            nz = math.sin(lat)
            # Several octaves of noise
            land = 0.0
            amp = 1.0; frq = 3.0
            for _ in range(5):
                land += amp*_smooth_noise((nx+1)*frq, (ny+nz+1)*frq)
                amp *= 0.5; frq *= 2.2
            land = land/1.9  # normalize ~[0,1]
            polar = abs(lat) > 1.2
            if polar:
                r,g,b = 240,245,255  # ice
            elif land > 0.52:
                # land: green to tan based on latitude
                green_mix = max(0, 1 - abs(lat)/0.8)
                r = int(120 + (1-green_mix)*80)
                g = int(100 + green_mix*60)
                b = 60
            else:
                # ocean
                depth = (0.52 - land)/0.52
                r = int(10 + depth*30)
                g = int(40 + depth*60)
                b = int(120 + depth*80)
            tex.set_pixel(x, y, r, g, b)
    return tex
