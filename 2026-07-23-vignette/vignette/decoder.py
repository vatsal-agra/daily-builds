"""Baseline JPEG decoder: real JFIF/JPEG bytes -> pixels.

Parses marker segments from scratch, Huffman-decodes the entropy-coded
scan, dequantizes and inverse-DCTs every block, upsamples subsampled
chroma, and converts back to RGB. Scope: baseline sequential DCT (SOF0)
with Huffman coding (no restart intervals, no progressive/arithmetic
coding, no more than 4:2:0-style 1x/2x sampling factors) — everything this
package's own encoder produces, and the common case for baseline JPEGs in
general.
"""

from . import color
from . import dct as dctmod
from . import huffman
from . import tables
from .image import Image

SOF0 = 0xC0
SOF2 = 0xC2
DHT = 0xC4
DQT = 0xDB
SOS = 0xDA
DRI = 0xDD
SOI = 0xD8
EOI = 0xD9
APPn = set(range(0xE0, 0xF0))
RSTn = set(range(0xD0, 0xD8))


class JpegSyntaxError(Exception):
    pass


def _u16(data, pos):
    return (data[pos] << 8) | data[pos + 1]


def decode(data):
    if data[0:2] != bytes([0xFF, SOI]):
        raise JpegSyntaxError("missing SOI marker")

    pos = 2
    quant_tables = {}
    huff_tables = {}
    frame = None
    scan_components = None
    scan_data_start = None
    restart_interval = 0

    while pos < len(data):
        if data[pos] != 0xFF:
            raise JpegSyntaxError(f"expected marker at offset {pos}")
        marker = data[pos + 1]
        pos += 2
        if marker == EOI:
            break
        if marker in RSTn or marker == 0x01:
            continue

        length = _u16(data, pos)
        seg_start = pos + 2
        seg_end = pos + length

        if marker == DQT:
            _parse_dqt(data, seg_start, seg_end, quant_tables)
        elif marker == DHT:
            _parse_dht(data, seg_start, seg_end, huff_tables)
        elif marker == SOF0:
            frame = _parse_sof(data, seg_start)
        elif marker == SOF2:
            raise JpegSyntaxError("progressive JPEG (SOF2) not supported")
        elif marker == DRI:
            restart_interval = _u16(data, seg_start)
        elif marker == SOS:
            scan_components = _parse_sos(data, seg_start, frame)
            scan_data_start = seg_end
            break  # entropy-coded data follows; handled below
        # APPn, COM, and anything else: skip the segment
        pos = seg_end

    if frame is None or scan_components is None:
        raise JpegSyntaxError("file is missing SOF0 or SOS")
    if restart_interval:
        raise JpegSyntaxError("restart intervals (DRI) not supported")

    return _decode_scan(
        data, scan_data_start, frame, scan_components, quant_tables, huff_tables
    )


def _parse_dqt(data, start, end, quant_tables):
    pos = start
    while pos < end:
        pq_tq = data[pos]
        precision, table_id = pq_tq >> 4, pq_tq & 0xF
        pos += 1
        n = 64 * (2 if precision else 1)
        raw = data[pos:pos + n]
        pos += n
        qt = [0] * 64
        for i in range(64):
            v = raw[2 * i] << 8 | raw[2 * i + 1] if precision else raw[i]
            qt[tables.ZIGZAG[i]] = v
        quant_tables[table_id] = qt


def _parse_dht(data, start, end, huff_tables):
    pos = start
    while pos < end:
        tc_th = data[pos]
        cls, table_id = tc_th >> 4, tc_th & 0xF
        pos += 1
        bits = list(data[pos:pos + 16])
        pos += 16
        n = sum(bits)
        huffval = list(data[pos:pos + n])
        pos += n
        huff_tables[(cls, table_id)] = huffman.HuffTable(bits, huffval)


def _parse_sof(data, start):
    pos = start
    precision = data[pos]
    height = _u16(data, pos + 1)
    width = _u16(data, pos + 3)
    n_comp = data[pos + 5]
    pos += 6
    components = []
    for _ in range(n_comp):
        cid = data[pos]
        sampling = data[pos + 1]
        qtsel = data[pos + 2]
        h, v = sampling >> 4, sampling & 0xF
        components.append({"id": cid, "h": h, "v": v, "qtsel": qtsel})
        pos += 3
    if precision != 8:
        raise JpegSyntaxError("only 8-bit precision baseline supported")
    return {
        "width": width,
        "height": height,
        "components": components,
    }


def _parse_sos(data, start, frame):
    pos = start
    n_comp = data[pos]
    pos += 1
    sel = {}
    for _ in range(n_comp):
        cid = data[pos]
        tsel = data[pos + 1]
        sel[cid] = {"dc": tsel >> 4, "ac": tsel & 0xF}
        pos += 2
    ss, se, ahal = data[pos], data[pos + 1], data[pos + 2]
    if not (ss == 0 and se == 63):
        raise JpegSyntaxError("only full-spectrum baseline scans supported")
    order = [c["id"] for c in frame["components"]]
    return [{"id": cid, **sel[cid]} for cid in order]


def _decode_scan(data, start, frame, scan_components, quant_tables, huff_tables):
    width, height = frame["width"], frame["height"]
    comps = frame["components"]
    hmax = max(c["h"] for c in comps)
    vmax = max(c["v"] for c in comps)
    mcu_w, mcu_h = 8 * hmax, 8 * vmax
    mcus_x = (width + mcu_w - 1) // mcu_w
    mcus_y = (height + mcu_h - 1) // mcu_h

    planes = {}
    plane_dims = {}
    dc_pred = {}
    for c in comps:
        pw = mcus_x * c["h"] * 8
        ph = mcus_y * c["v"] * 8
        planes[c["id"]] = [0] * (pw * ph)
        plane_dims[c["id"]] = (pw, ph)
        dc_pred[c["id"]] = 0

    comp_by_id = {c["id"]: c for c in comps}
    scan_by_id = {s["id"]: s for s in scan_components}

    reader = huffman.BitReader(data, start)

    for my in range(mcus_y):
        for mx in range(mcus_x):
            for c in comps:
                sc = scan_by_id[c["id"]]
                dc_table = huff_tables[(0, sc["dc"])]
                ac_table = huff_tables[(1, sc["ac"])]
                qt = quant_tables[c["qtsel"]]
                pw, _ = plane_dims[c["id"]]
                for v in range(c["v"]):
                    for h in range(c["h"]):
                        zz = _decode_block(reader, dc_table, ac_table)
                        dc_pred[c["id"]] += zz[0]
                        zz[0] = dc_pred[c["id"]]
                        pixels = _dequant_idct(zz, qt)
                        bx = mx * c["h"] + h
                        by = my * c["v"] + v
                        _store_block(planes[c["id"]], pw, bx, by, pixels)

    return _reassemble(planes, plane_dims, comps, hmax, vmax, width, height)


def _decode_block(reader, dc_table, ac_table):
    zz = [0] * 64
    size = dc_table.decode_one(reader)
    bits = _read_bits(reader, size)
    zz[0] = tables.decode_magnitude(bits, size)

    k = 1
    while k < 64:
        rs = ac_table.decode_one(reader)
        run, size = rs >> 4, rs & 0xF
        if rs == 0x00:  # EOB
            break
        if rs == 0xF0:  # ZRL
            k += 16
            continue
        k += run
        if k >= 64:
            break
        bits = _read_bits(reader, size)
        zz[k] = tables.decode_magnitude(bits, size)
        k += 1
    return zz


def _read_bits(reader, n):
    v = 0
    for _ in range(n):
        v = (v << 1) | reader.read_bit()
    return v


def _dequant_idct(zz, qt):
    # `qt` (from _parse_dqt) is in natural (row-major) order.
    natural = [0.0] * 64
    for i in range(64):
        n = tables.ZIGZAG[i]
        natural[n] = zz[i] * qt[n]
    block = [[natural[r * 8 + c] for c in range(8)] for r in range(8)]
    spatial = dctmod.idct_2d(block)
    out = [[0] * 8 for _ in range(8)]
    for r in range(8):
        for c in range(8):
            v = int(round(spatial[r][c] + 128.0))
            out[r][c] = 0 if v < 0 else 255 if v > 255 else v
    return out


def _store_block(plane, pw, bx, by, pixels):
    base_y = by * 8
    base_x = bx * 8
    for r in range(8):
        row_off = (base_y + r) * pw + base_x
        for c in range(8):
            plane[row_off + c] = pixels[r][c]


def _reassemble(planes, plane_dims, comps, hmax, vmax, width, height):
    y_id, cb_id, cr_id = comps[0]["id"], comps[1]["id"], comps[2]["id"]
    y_plane = planes[y_id]
    cb_plane = planes[cb_id]
    cr_plane = planes[cr_id]
    yw, yh = plane_dims[y_id]
    cbw, cbh = plane_dims[cb_id]
    crw, crh = plane_dims[cr_id]
    y_h, y_v = comp_h_v(comps, y_id)
    cb_h, cb_v = comp_h_v(comps, cb_id)
    cr_h, cr_v = comp_h_v(comps, cr_id)

    out_pixels = [(0, 0, 0)] * (width * height)
    for py in range(height):
        y_row = (py * y_v) // vmax
        cb_row = (py * cb_v) // vmax
        cr_row = (py * cr_v) // vmax
        for px in range(width):
            y_col = (px * y_h) // hmax
            cb_col = (px * cb_h) // hmax
            cr_col = (px * cr_h) // hmax
            yy = y_plane[y_row * yw + y_col]
            cb = cb_plane[cb_row * cbw + cb_col]
            cr = cr_plane[cr_row * crw + cr_col]
            out_pixels[py * width + px] = color.ycbcr_to_rgb(yy, cb, cr)
    return Image(width, height, out_pixels)


def comp_h_v(comps, cid):
    for c in comps:
        if c["id"] == cid:
            return c["h"], c["v"]
    raise KeyError(cid)
