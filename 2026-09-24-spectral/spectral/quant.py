"""Quantization tables (ITU-T T.81 Annex K), quality scaling, and zigzag order.

Quantization is where JPEG actually throws information away: each DCT
coefficient is divided by a table entry and rounded to the nearest
integer. The table entries grow with spatial frequency, because the human
eye is far less sensitive to high-frequency (fine detail) error than to
low-frequency (broad shading) error -- so high frequencies get divided by
bigger numbers and more often round to exactly zero.
"""

# Annex K.1 Table K.1 -- baseline luminance quantization table (quality 50)
STD_LUMA_QTABLE = [
    16, 11, 10, 16, 24, 40, 51, 61,
    12, 12, 14, 19, 26, 58, 60, 55,
    14, 13, 16, 24, 40, 57, 69, 56,
    14, 17, 22, 29, 51, 87, 80, 62,
    18, 22, 37, 56, 68, 109, 103, 77,
    24, 35, 55, 64, 81, 104, 113, 92,
    49, 64, 78, 87, 103, 121, 120, 101,
    72, 92, 95, 98, 112, 100, 103, 99,
]

# Annex K.1 Table K.2 -- baseline chrominance quantization table (quality 50)
STD_CHROMA_QTABLE = [
    17, 18, 24, 47, 99, 99, 99, 99,
    18, 21, 26, 66, 99, 99, 99, 99,
    24, 26, 56, 99, 99, 99, 99, 99,
    47, 66, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99,
]

# The zigzag scan order: reads an 8x8 block of DCT coefficients in
# increasing spatial frequency, so low frequencies (which carry most of
# the energy) cluster at the start of the sequence and long runs of zero
# high-frequency coefficients cluster at the end -- exactly what the AC
# run-length + EOB encoding in entropy coding wants.
ZIGZAG = [
    0, 1, 8, 16, 9, 2, 3, 10,
    17, 24, 32, 25, 18, 11, 4, 5,
    12, 19, 26, 33, 40, 48, 41, 34,
    27, 20, 13, 6, 7, 14, 21, 28,
    35, 42, 49, 56, 57, 50, 43, 36,
    29, 22, 15, 23, 30, 37, 44, 51,
    58, 59, 52, 45, 38, 31, 39, 46,
    53, 60, 61, 54, 47, 55, 62, 63,
]

INV_ZIGZAG = [0] * 64
for _i, _pos in enumerate(ZIGZAG):
    INV_ZIGZAG[_pos] = _i


def scale_qtable(base_table, quality):
    """Scale a base (quality-50) quantization table for a 1-100 quality.

    This is the exact formula the IJG reference encoder (libjpeg) uses:
      quality < 50:  scale = 5000 / quality
      quality >= 50: scale = 200 - quality * 2
    then each entry is (base * scale + 50) / 100, clamped to [1, 255].
    Quality 100 does not mean lossless (real JPEG can never reach that
    with 8-bit DCT quantization) -- it means every table entry floors at
    1, the smallest possible perceptible-loss quantizer.
    """
    quality = max(1, min(100, int(quality)))
    if quality < 50:
        scale = 5000.0 / quality
    else:
        scale = 200.0 - quality * 2.0
    out = []
    for v in base_table:
        q = int((v * scale + 50.0) / 100.0)
        q = max(1, min(255, q))
        out.append(q)
    return out


def quantize(block, qtable):
    """Divide-and-round 64 DCT coefficients by a (natural-order) qtable."""
    out = [0] * 64
    for i in range(64):
        v = block[i] / qtable[i]
        out[i] = int(round(v))
    return out


def dequantize(qcoeffs, qtable):
    out = [0.0] * 64
    for i in range(64):
        out[i] = qcoeffs[i] * qtable[i]
    return out


def to_zigzag(natural_order_block):
    out = [0] * 64
    for i in range(64):
        out[i] = natural_order_block[ZIGZAG[i]]
    return out


def from_zigzag(zigzag_order_block):
    out = [0] * 64
    for i in range(64):
        out[ZIGZAG[i]] = zigzag_order_block[i]
    return out
