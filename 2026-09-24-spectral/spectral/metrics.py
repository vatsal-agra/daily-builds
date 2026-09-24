"""Image-quality and compression metrics used by tests and the visualizer."""
import math


def mse(image_a, image_b):
    assert image_a.width == image_b.width and image_a.height == image_b.height
    n = image_a.width * image_a.height
    total = 0
    for plane_a, plane_b in ((image_a.r, image_b.r), (image_a.g, image_b.g), (image_a.b, image_b.b)):
        for i in range(n):
            d = plane_a[i] - plane_b[i]
            total += d * d
    return total / (n * 3)


def psnr(image_a, image_b):
    """Peak Signal-to-Noise Ratio in dB. Higher is better; identical
    images give +infinity. Typical 'visually fine' JPEG output is
    around 30-45 dB depending on content and quality setting."""
    m = mse(image_a, image_b)
    if m == 0:
        return float("inf")
    return 10.0 * math.log10((255.0 * 255.0) / m)
