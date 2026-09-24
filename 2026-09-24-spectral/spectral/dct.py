"""The 8x8 Discrete Cosine Transform (DCT-II / DCT-III), the heart of JPEG.

JPEG applies a 2D DCT-II to each 8x8 block of level-shifted samples. The 2D
transform is separable: it equals a 1D DCT applied to every row, followed
by a 1D DCT applied to every column (or vice versa) of the result. This
module provides:

  * `dct_1d_matrix` / `idct_1d_matrix` -- the exact 8x8 basis matrices,
    built directly from the DCT-II definition (not tuned/looked-up), used
    to do the real forward/inverse transform via two matrix multiplies.
  * `dct_2d_naive` -- a brute-force O(N^4) direct evaluation of the 2D
    DCT-II definition, with no separability trick at all. This exists
    purely as an independent reference: the tests prove the fast
    separable transform computes bit-identical (to float tolerance)
    results to this completely different code path, so a subtle
    separability bug can't hide by being self-consistent with itself.
"""
import math

N = 8

# C(0) = 1/sqrt(2), C(k>0) = 1
_C = [1.0 / math.sqrt(2.0)] + [1.0] * (N - 1)

# basis[k][n] = C(k) * cos((2n+1) * k * pi / (2N)) -- the DCT-II kernel,
# pre-scaled by sqrt(2/N) so the transform is orthonormal (forward and
# inverse use the exact same matrix, transposed).
_SCALE = math.sqrt(2.0 / N)


def _build_basis():
    basis = [[0.0] * N for _ in range(N)]
    for k in range(N):
        for n in range(N):
            basis[k][n] = _SCALE * _C[k] * math.cos((2 * n + 1) * k * math.pi / (2 * N))
    return basis


BASIS = _build_basis()  # BASIS[k][n]: forward direction (spatial n -> freq k)


def _matmul8(a, b):
    """8x8 * 8x8 matrix multiply."""
    out = [[0.0] * N for _ in range(N)]
    for i in range(N):
        ai = a[i]
        for j in range(N):
            s = 0.0
            for k in range(N):
                s += ai[k] * b[k][j]
            out[i][j] = s
    return out


def _transpose8(m):
    return [[m[j][i] for j in range(N)] for i in range(N)]


_BASIS_T = _transpose8(BASIS)


def dct_2d(block):
    """Forward 2D DCT-II on an 8x8 block (flat list of 64 floats).

    Separable formulation: F = BASIS . block . BASIS^T
    """
    m = [block[r * N:(r + 1) * N] for r in range(N)]
    tmp = _matmul8(BASIS, m)          # DCT along columns (rows dimension)
    out = _matmul8(tmp, _BASIS_T)     # DCT along rows (columns dimension)
    flat = [0.0] * 64
    for r in range(N):
        row = out[r]
        for c in range(N):
            flat[r * N + c] = row[c]
    return flat


def idct_2d(coeffs):
    """Inverse 2D DCT (= DCT-III), the exact inverse of dct_2d.

    Since BASIS is orthonormal (BASIS^T = BASIS^-1), the inverse is
    F = BASIS^T . coeffs . BASIS
    """
    m = [coeffs[r * N:(r + 1) * N] for r in range(N)]
    tmp = _matmul8(_BASIS_T, m)
    out = _matmul8(tmp, BASIS)
    flat = [0.0] * 64
    for r in range(N):
        row = out[r]
        for c in range(N):
            flat[r * N + c] = row[c]
    return flat


def dct_2d_naive(block):
    """Brute-force O(N^4) direct 2D DCT-II, no separability trick at all.

    F(u,v) = (2/N) * C(u) * C(v) * sum_x sum_y f(x,y) *
             cos((2x+1)u*pi/2N) * cos((2y+1)v*pi/2N)

    (This is exactly ITU-T T.81 Annex A's forward DCT formula for N=8,
    where 2/N = 1/4.) Used only as an independent correctness oracle in
    tests -- it shares no code with the separable matrix path above.
    """
    out = [0.0] * 64
    scale = 2.0 / N
    for u in range(N):
        for v in range(N):
            s = 0.0
            for x in range(N):
                cx = math.cos((2 * x + 1) * u * math.pi / (2 * N))
                for y in range(N):
                    cy = math.cos((2 * y + 1) * v * math.pi / (2 * N))
                    s += block[x * N + y] * cx * cy
            out[u * N + v] = scale * _C[u] * _C[v] * s
    return out
