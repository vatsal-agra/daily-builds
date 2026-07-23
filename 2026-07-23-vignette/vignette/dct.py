"""8x8 2D DCT-II / inverse DCT-II (the JPEG transform), built from the
closed-form basis functions — no FFT trick, just the separable row/column
sum-of-cosines definition used directly.

For an 8-point sequence, forward DCT-II coefficient u is:

    F(u) = C(u)/2 * sum_{x=0..7} f(x) * cos((2x+1) u*pi / 16)

with C(0) = 1/sqrt(2), C(u>0) = 1. The inverse (DCT-III) is:

    f(x) = sum_{u=0..7} C(u)/2 * F(u) * cos((2x+1) u*pi / 16)

The 2D transform over an 8x8 block is separable: apply the 1D transform to
every row, then to every column of the result (JPEG's actual definition).
"""

import math

N = 8

# Precomputed cosine basis: COS[x][u] = cos((2x+1) u pi / 16)
_COS = [[math.cos((2 * x + 1) * u * math.pi / 16) for u in range(N)] for x in range(N)]
_C = [1.0 / math.sqrt(2) if u == 0 else 1.0 for u in range(N)]


def dct_1d(f):
    """Forward DCT-II of an 8-element sequence."""
    out = [0.0] * N
    for u in range(N):
        s = 0.0
        for x in range(N):
            s += f[x] * _COS[x][u]
        out[u] = 0.5 * _C[u] * s
    return out


def idct_1d(F):
    """Inverse DCT-II (DCT-III) of an 8-element coefficient sequence."""
    out = [0.0] * N
    for x in range(N):
        s = 0.0
        for u in range(N):
            s += _C[u] * F[u] * _COS[x][u]
        out[x] = 0.5 * s
    return out


def dct_2d(block):
    """Forward 2D DCT-II over an 8x8 block (list of 8 lists of 8 floats).
    Separable: rows first, then columns."""
    tmp = [dct_1d(row) for row in block]
    out = [[0.0] * N for _ in range(N)]
    for col in range(N):
        column = [tmp[row][col] for row in range(N)]
        transformed = dct_1d(column)
        for row in range(N):
            out[row][col] = transformed[row]
    return out


def idct_2d(coeffs):
    """Inverse 2D DCT over an 8x8 coefficient block."""
    tmp = [[0.0] * N for _ in range(N)]
    for col in range(N):
        column = [coeffs[row][col] for row in range(N)]
        restored = idct_1d(column)
        for row in range(N):
            tmp[row][col] = restored[row]
    out = [idct_1d(row) for row in tmp]
    return out


def dct_2d_bruteforce(block):
    """O(N^4) direct-sum reference implementation of the 2D DCT-II, used
    only by tests to cross-check the separable version above against the
    textbook definition applied without the separability shortcut."""
    out = [[0.0] * N for _ in range(N)]
    for u in range(N):
        for v in range(N):
            s = 0.0
            for x in range(N):
                for y in range(N):
                    s += (
                        block[x][y]
                        * math.cos((2 * x + 1) * u * math.pi / 16)
                        * math.cos((2 * y + 1) * v * math.pi / 16)
                    )
            out[u][v] = 0.25 * _C[u] * _C[v] * s
    return out
