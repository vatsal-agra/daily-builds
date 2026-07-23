"""Image-quality and rate-distortion metrics: PSNR, a windowed SSIM, and
compression-ratio / bits-per-pixel reporting."""

import math


def mse(a, b):
    if a.width != b.width or a.height != b.height:
        raise ValueError("images must have matching dimensions")
    total = 0
    n = a.width * a.height
    for (r1, g1, b1), (r2, g2, b2) in zip(a.pixels, b.pixels):
        total += (r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2
    return total / (n * 3)


def psnr(a, b):
    m = mse(a, b)
    if m == 0:
        return float("inf")
    return 10.0 * math.log10((255.0 ** 2) / m)


def _luma(image):
    out = [0.0] * (image.width * image.height)
    for i, (r, g, b) in enumerate(image.pixels):
        out[i] = 0.299 * r + 0.587 * g + 0.114 * b
    return out


def ssim(a, b, window=8):
    """Windowed (non-overlapping block) structural similarity index,
    computed on luma, averaged over all windows — a simplified but
    faithful implementation of the Wang et al. 2004 SSIM formula (uniform
    window instead of the paper's Gaussian window)."""
    if a.width != b.width or a.height != b.height:
        raise ValueError("images must have matching dimensions")
    C1 = (0.01 * 255) ** 2
    C2 = (0.03 * 255) ** 2
    la, lb = _luma(a), _luma(b)
    w, h = a.width, a.height
    scores = []
    for y0 in range(0, h, window):
        for x0 in range(0, w, window):
            wa, wb = [], []
            for y in range(y0, min(y0 + window, h)):
                base = y * w
                for x in range(x0, min(x0 + window, w)):
                    wa.append(la[base + x])
                    wb.append(lb[base + x])
            n = len(wa)
            if n == 0:
                continue
            mean_a = sum(wa) / n
            mean_b = sum(wb) / n
            var_a = sum((v - mean_a) ** 2 for v in wa) / n
            var_b = sum((v - mean_b) ** 2 for v in wb) / n
            cov = sum((wa[i] - mean_a) * (wb[i] - mean_b) for i in range(n)) / n
            numerator = (2 * mean_a * mean_b + C1) * (2 * cov + C2)
            denominator = (mean_a ** 2 + mean_b ** 2 + C1) * (var_a + var_b + C2)
            scores.append(numerator / denominator)
    return sum(scores) / len(scores) if scores else 1.0


def compression_stats(image, encoded_bytes):
    width, height = image.width, image.height
    raw_bytes = width * height * 3
    compressed = len(encoded_bytes)
    return {
        "raw_bytes": raw_bytes,
        "compressed_bytes": compressed,
        "ratio": raw_bytes / compressed if compressed else float("inf"),
        "bits_per_pixel": (compressed * 8) / (width * height),
    }
