"""Baseline JPEG encoder: image pixels -> real, spec-valid JFIF `.jpg` bytes.

Pipeline: RGB -> YCbCr -> 4:2:0 chroma subsampling -> 8x8 block DCT ->
quantization -> zigzag -> DC DPCM + AC run-length -> Huffman entropy coding
-> marker-framed JFIF file.
"""

import struct
from collections import Counter

from . import color
from . import dct as dctmod
from . import huffman
from . import tables

MCU = 16  # 4:2:0 MCU size in luma pixels (2x2 luma blocks wide/tall)


def _pad_plane(plane, w, h, pw, ph):
    """Edge-replicate `plane` (w x h) up to (pw x ph)."""
    out = [0.0] * (pw * ph)
    for y in range(ph):
        sy = min(y, h - 1)
        row_src = sy * w
        row_dst = y * pw
        for x in range(pw):
            sx = min(x, w - 1)
            out[row_dst + x] = plane[row_src + sx]
    return out


def _downsample_2x2(plane, pw, ph):
    """Box-filter 2x2 average downsample; pw, ph must be even."""
    ow, oh = pw // 2, ph // 2
    out = [0.0] * (ow * oh)
    for y in range(oh):
        for x in range(ow):
            sx, sy = x * 2, y * 2
            s = (
                plane[sy * pw + sx]
                + plane[sy * pw + sx + 1]
                + plane[(sy + 1) * pw + sx]
                + plane[(sy + 1) * pw + sx + 1]
            )
            out[y * ow + x] = s / 4.0
    return out


def _extract_block(plane, pw, bx, by):
    """Extract the 8x8 block at block-coords (bx,by) as an 8x8 list-of-lists,
    level-shifted by -128 (JPEG's convention: samples centered on 0)."""
    block = [[0.0] * 8 for _ in range(8)]
    base_y = by * 8
    base_x = bx * 8
    for r in range(8):
        row_off = (base_y + r) * pw + base_x
        for c in range(8):
            block[r][c] = plane[row_off + c] - 128.0
    return block


def _quantize_zigzag(block, qtable):
    coeffs = dctmod.dct_2d(block)
    natural = [0] * 64
    for r in range(8):
        for c in range(8):
            natural[r * 8 + c] = coeffs[r][c]
    zz = [0] * 64
    for i in range(64):
        n = tables.ZIGZAG[i]
        # round-half-away-from-zero, standard for JPEG quantization.
        # `qtable` is in natural (row-major) order, so index it by `n`,
        # not by the zigzag scan position `i`.
        v = natural[n] / qtable[n]
        zz[i] = int(v + (0.5 if v >= 0 else -0.5))
    return zz


def _block_symbols(zz, prev_dc, dc_class, ac_class):
    dc_diff = zz[0] - prev_dc
    size = tables.size_category(dc_diff)
    extra = tables.encode_magnitude(dc_diff, size)
    symbols = [(dc_class, size, extra, size)]

    run = 0
    for k in range(1, 64):
        val = zz[k]
        if val == 0:
            run += 1
            continue
        while run > 15:
            symbols.append((ac_class, 0xF0, 0, 0))
            run -= 16
        s = tables.size_category(val)
        ex = tables.encode_magnitude(val, s)
        rs = (run << 4) | s
        symbols.append((ac_class, rs, ex, s))
        run = 0
    if run > 0:
        symbols.append((ac_class, 0x00, 0, 0))
    return symbols, zz[0]


def _plane_from_component(comp, width, height):
    y_plane = [0.0] * (width * height)
    cb_plane = [0.0] * (width * height)
    cr_plane = [0.0] * (width * height)
    for i, (r, g, b) in enumerate(comp):
        y, cb, cr = color.rgb_to_ycbcr(r, g, b)
        y_plane[i] = y
        cb_plane[i] = cb
        cr_plane[i] = cr
    return y_plane, cb_plane, cr_plane


def encode(image, quality=75, optimal_huffman=False):
    """Encode `image` (vignette.image.Image) into baseline JFIF bytes."""
    width, height = image.width, image.height
    y_plane, cb_plane, cr_plane = _plane_from_component(image.pixels, width, height)

    pw = ((width + MCU - 1) // MCU) * MCU
    ph = ((height + MCU - 1) // MCU) * MCU

    y_pad = _pad_plane(y_plane, width, height, pw, ph)
    cb_pad = _pad_plane(cb_plane, width, height, pw, ph)
    cr_pad = _pad_plane(cr_plane, width, height, pw, ph)

    cb_sub = _downsample_2x2(cb_pad, pw, ph)
    cr_sub = _downsample_2x2(cr_pad, pw, ph)
    cpw, cph = pw // 2, ph // 2

    qt_luma = tables.scale_quant_table(tables.STD_LUMINANCE_QT, quality)
    qt_chroma = tables.scale_quant_table(tables.STD_CHROMINANCE_QT, quality)

    mcus_x = pw // MCU
    mcus_y = ph // MCU

    # -- pass 1: transform + quantize + RLE every block, collect symbol
    # streams and per-class frequency counts (needed whether or not we
    # end up using optimal tables, and avoids redoing the DCT for pass 2)
    dc_pred_y = dc_pred_cb = dc_pred_cr = 0
    all_symbols = []  # list of lists (one per block)
    freq = {
        "DC_LUMA": Counter(),
        "DC_CHROMA": Counter(),
        "AC_LUMA": Counter(),
        "AC_CHROMA": Counter(),
    }

    for my in range(mcus_y):
        for mx in range(mcus_x):
            for by in range(2):
                for bx in range(2):
                    gbx = mx * 2 + bx
                    gby = my * 2 + by
                    block = _extract_block(y_pad, pw, gbx, gby)
                    zz = _quantize_zigzag(block, qt_luma)
                    syms, dc_pred_y = _block_symbols(
                        zz, dc_pred_y, "DC_LUMA", "AC_LUMA"
                    )
                    all_symbols.append(syms)
                    for cls, sym, _, _ in syms:
                        freq[cls][sym] += 1

            block = _extract_block(cb_sub, cpw, mx, my)
            zz = _quantize_zigzag(block, qt_chroma)
            syms, dc_pred_cb = _block_symbols(
                zz, dc_pred_cb, "DC_CHROMA", "AC_CHROMA"
            )
            all_symbols.append(syms)
            for cls, sym, _, _ in syms:
                freq[cls][sym] += 1

            block = _extract_block(cr_sub, cpw, mx, my)
            zz = _quantize_zigzag(block, qt_chroma)
            syms, dc_pred_cr = _block_symbols(
                zz, dc_pred_cr, "DC_CHROMA", "AC_CHROMA"
            )
            all_symbols.append(syms)
            for cls, sym, _, _ in syms:
                freq[cls][sym] += 1

    # -- pick Huffman tables --------------------------------------------
    std = {
        "DC_LUMA": (tables.STD_DC_LUMINANCE_BITS, tables.STD_DC_LUMINANCE_VALUES),
        "DC_CHROMA": (
            tables.STD_DC_CHROMINANCE_BITS,
            tables.STD_DC_CHROMINANCE_VALUES,
        ),
        "AC_LUMA": (tables.STD_AC_LUMINANCE_BITS, tables.STD_AC_LUMINANCE_VALUES),
        "AC_CHROMA": (
            tables.STD_AC_CHROMINANCE_BITS,
            tables.STD_AC_CHROMINANCE_VALUES,
        ),
    }
    chosen = {}
    used_optimal = {}
    for cls in std:
        bits, huffval = std[cls]
        if optimal_huffman and freq[cls]:
            built = huffman.build_optimal_table(dict(freq[cls]))
            if built is not None:
                bits, huffval = built
                used_optimal[cls] = True
        chosen[cls] = huffman.HuffTable(bits, huffval)
        used_optimal.setdefault(cls, False)

    # -- pass 2: write the entropy-coded bitstream -----------------------
    writer = huffman.BitWriter()
    for syms in all_symbols:
        for cls, sym, extra, extra_len in syms:
            table = chosen[cls]
            code, length = table.encode(sym)
            writer.write_bits(code, length)
            if extra_len:
                writer.write_bits(extra, extra_len)
    entropy_bytes = writer.pad_and_get_bytes()

    out = bytearray()
    out += _marker_soi()
    out += _marker_app0()
    out += _marker_dqt(0, qt_luma)
    out += _marker_dqt(1, qt_chroma)
    out += _marker_sof0(width, height)
    out += _marker_dht(0, 0, chosen["DC_LUMA"])
    out += _marker_dht(1, 0, chosen["AC_LUMA"])
    out += _marker_dht(0, 1, chosen["DC_CHROMA"])
    out += _marker_dht(1, 1, chosen["AC_CHROMA"])
    out += _marker_sos()
    out += entropy_bytes
    out += _marker_eoi()

    stats = {"used_optimal_huffman": used_optimal, "quality": quality}
    return bytes(out), stats


# -- marker segment writers -------------------------------------------------


def _marker_soi():
    return bytes([0xFF, 0xD8])


def _marker_eoi():
    return bytes([0xFF, 0xD9])


def _marker_app0():
    ident = b"JFIF\x00"
    # version 1.1, units=0 (no units, aspect ratio only), density 1x1, no thumbnail
    body = ident + struct.pack(">BBBHHBB", 1, 1, 0, 1, 1, 0, 0)
    length = len(body) + 2
    return bytes([0xFF, 0xE0]) + struct.pack(">H", length) + body


def _marker_dqt(table_id, qtable):
    # `qtable` is natural (row-major) order; the file format stores
    # quant tables in zigzag scan order, so reorder on the way out.
    zz_order = [qtable[tables.ZIGZAG[i]] for i in range(64)]
    pq_tq = (0 << 4) | (table_id & 0xF)
    body = bytes([pq_tq]) + bytes(zz_order)
    length = len(body) + 2
    return bytes([0xFF, 0xDB]) + struct.pack(">H", length) + body


def _marker_sof0(width, height):
    # Y: 2x2 sampling (id=1, qt=0); Cb/Cr: 1x1 sampling (qt=1)
    components = [
        (1, 0x22, 0),
        (2, 0x11, 1),
        (3, 0x11, 1),
    ]
    body = bytearray()
    body.append(8)  # precision
    body += struct.pack(">H", height)
    body += struct.pack(">H", width)
    body.append(len(components))
    for cid, sampling, qtsel in components:
        body += bytes([cid, sampling, qtsel])
    length = len(body) + 2
    return bytes([0xFF, 0xC0]) + struct.pack(">H", length) + bytes(body)


def _marker_dht(cls, table_id, huff_table):
    tc_th = ((cls & 0xF) << 4) | (table_id & 0xF)
    body = bytes([tc_th]) + bytes(huff_table.bits) + bytes(huff_table.huffval)
    length = len(body) + 2
    return bytes([0xFF, 0xC4]) + struct.pack(">H", length) + body


def _marker_sos():
    components = [
        (1, 0x00),  # Y: DC table 0, AC table 0
        (2, 0x11),  # Cb: DC table 1, AC table 1
        (3, 0x11),  # Cr: DC table 1, AC table 1
    ]
    body = bytearray()
    body.append(len(components))
    for cid, tsel in components:
        body += bytes([cid, tsel])
    body += bytes([0, 63, 0])  # Ss, Se, Ah/Al (baseline sequential, full spectrum)
    length = len(body) + 2
    return bytes([0xFF, 0xDA]) + struct.pack(">H", length) + bytes(body)
