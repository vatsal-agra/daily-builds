"""Framebuffer: color buffer (RGB floats) + depth buffer (float32)."""
import array
import math


class Framebuffer:
    def __init__(self, width, height, msaa=1):
        self.width = width
        self.height = height
        self.msaa = msaa  # 1 = no MSAA, 2 = 2x MSAA (4 samples)
        # Actual rasterization dimensions
        self.rw = width * msaa
        self.rh = height * msaa
        n = self.rw * self.rh
        # Color: r,g,b per pixel as floats
        self.r = array.array('f', [0.0]*n)
        self.g = array.array('f', [0.0]*n)
        self.b = array.array('f', [0.0]*n)
        # Depth: positive = further from camera
        self.depth = array.array('f', [math.inf]*n)

    def clear(self, color=(0.05, 0.05, 0.1)):
        n = self.rw * self.rh
        for i in range(n):
            self.r[i] = color[0]
            self.g[i] = color[1]
            self.b[i] = color[2]
            self.depth[i] = math.inf

    def idx(self, x, y):
        return y * self.rw + x

    def set_pixel(self, x, y, r, g, b):
        i = y * self.rw + x
        self.r[i] = r; self.g[i] = g; self.b[i] = b

    def get_pixel(self, x, y):
        i = y * self.rw + x
        return self.r[i], self.g[i], self.b[i]

    def depth_test_and_set(self, x, y, z):
        """Returns True and writes depth if z < current depth."""
        i = y * self.rw + x
        if z < self.depth[i]:
            self.depth[i] = z
            return True
        return False

    def get_depth(self, x, y):
        return self.depth[y * self.rw + x]

    def resolve_to_rgb_bytes(self, gamma=2.2):
        """MSAA resolve + gamma correction → flat bytes (r,g,b per pixel)."""
        inv_samples = 1.0 / (self.msaa * self.msaa)
        inv_gamma = 1.0 / gamma
        out = bytearray(self.width * self.height * 3)
        idx_out = 0
        for py in range(self.height):
            for px in range(self.width):
                sr = sg = sb = 0.0
                for sy in range(self.msaa):
                    for sx in range(self.msaa):
                        i = (py*self.msaa+sy)*self.rw + (px*self.msaa+sx)
                        sr += self.r[i]; sg += self.g[i]; sb += self.b[i]
                sr *= inv_samples; sg *= inv_samples; sb *= inv_samples
                # Reinhard tonemapping then gamma
                sr = sr/(1+sr); sg = sg/(1+sg); sb = sb/(1+sb)
                out[idx_out]   = int(max(0,min(255, (sr**inv_gamma)*255 + 0.5))  )
                out[idx_out+1] = int(max(0,min(255, (sg**inv_gamma)*255 + 0.5))  )
                out[idx_out+2] = int(max(0,min(255, (sb**inv_gamma)*255 + 0.5))  )
                idx_out += 3
        return bytes(out)


class DepthBuffer:
    """Standalone depth buffer for shadow maps."""
    def __init__(self, width, height):
        self.width = width
        self.height = height
        n = width * height
        self.depth = array.array('f', [math.inf]*n)

    def clear(self):
        n = self.width * self.height
        for i in range(n): self.depth[i] = math.inf

    def depth_test_and_set(self, x, y, z):
        i = y * self.width + x
        if z < self.depth[i]:
            self.depth[i] = z
            return True
        return False

    def get(self, x, y):
        x = max(0, min(self.width-1, x))
        y = max(0, min(self.height-1, y))
        return self.depth[y * self.width + x]
