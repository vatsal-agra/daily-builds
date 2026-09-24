"""The baseline sequential JPEG decoder: JFIF bytes -> RGB image.

The exact inverse of encoder.py's pipeline: parse markers -> Huffman
decode -> DC/AC reconstruction -> dequantize -> inverse DCT -> level
unshift -> reassemble padded planes -> crop -> chroma upsample ->
YCbCr -> RGB.
"""
from . import colorspace, dct, quant, huffman, bitstream, markers


class JpegDecodeError(Exception):
    pass


def decode_baseline_scan(frame, scan_components, entropy_bytes, comps_by_id):
    dc_tables = {}
    ac_tables = {}
    for cid, dc_id, ac_id in scan_components:
        if dc_id not in frame.dc_tables:
            raise JpegDecodeError(f"scan references undefined DC Huffman table {dc_id}")
        if ac_id not in frame.ac_tables:
            raise JpegDecodeError(f"scan references undefined AC Huffman table {ac_id}")
        dc_tables[cid] = huffman.HuffmanTable(*frame.dc_tables[dc_id])
        ac_tables[cid] = huffman.HuffmanTable(*frame.ac_tables[ac_id])

    reader = bitstream.BitReader(entropy_bytes)
    dc_pred = {cid: 0 for cid, _, _ in scan_components}

    for my in range(frame._mcus_y):
        for mx in range(frame._mcus_x):
            for cid, _dc_id, _ac_id in scan_components:
                comp = comps_by_id[cid]
                for v in range(comp["v"]):
                    by = my * comp["v"] + v
                    for h in range(comp["h"]):
                        bx = mx * comp["h"] + h
                        zz = _decode_block(reader, dc_tables[cid], ac_tables[cid], dc_pred, cid)
                        idx = by * comp["blocks_x"] + bx
                        comp["coeffs"][idx] = zz


def _decode_block(reader, dc_table, ac_table, dc_pred, cid):
    category = dc_table.decode_symbol(reader)
    if category is None:
        raise JpegDecodeError("unexpected end of entropy data while decoding a DC symbol")
    if category > 11:
        raise JpegDecodeError(f"invalid DC coefficient category {category}")
    bits = reader.read_bits(category) if category else 0
    if category and bits is None:
        raise JpegDecodeError("unexpected end of entropy data while reading DC magnitude bits")
    diff = bitstream.extend_receive(bits or 0, category)
    dc_pred[cid] += diff

    zz = [0] * 64
    zz[0] = dc_pred[cid]

    k = 1
    while k < 64:
        symbol = ac_table.decode_symbol(reader)
        if symbol is None:
            raise JpegDecodeError("unexpected end of entropy data while decoding an AC symbol")
        run = symbol >> 4
        size = symbol & 0x0F
        if size == 0:
            if run == 15:
                k += 16  # ZRL: 16 zero coefficients, no value
                continue
            break  # EOB: all remaining coefficients are 0
        k += run
        if k >= 64:
            raise JpegDecodeError("AC coefficient run overflowed the block")
        bits = reader.read_bits(size)
        if bits is None:
            raise JpegDecodeError("unexpected end of entropy data while reading AC magnitude bits")
        zz[k] = bitstream.extend_receive(bits, size)
        k += 1

    return zz


def reconstruct_planes(frame, comps_by_id):
    planes = {}
    for cid, comp in comps_by_id.items():
        bw, bh = comp["blocks_x"], comp["blocks_y"]
        padded_w, padded_h = bw * 8, bh * 8
        plane = [0.0] * (padded_w * padded_h)
        qtable_id = comp["qtable_id"]
        if qtable_id not in frame.qtables:
            raise JpegDecodeError(f"component {cid} references undefined quantization table {qtable_id}")
        qtable = frame.qtables[qtable_id]
        for by in range(bh):
            for bx in range(bw):
                zz = comp["coeffs"][by * bw + bx]
                natural = quant.from_zigzag(zz)
                deq = quant.dequantize(natural, qtable)
                spatial = dct.idct_2d(deq)
                base_y, base_x = by * 8, bx * 8
                for r in range(8):
                    row_off = (base_y + r) * padded_w + base_x
                    for c in range(8):
                        plane[row_off + c] = spatial[r * 8 + c] + 128.0
        planes[cid] = (plane, padded_w, padded_h)
    return planes


def decode(data):
    """Decode JFIF bytes into a `colorspace.Image`. Raises
    JpegDecodeError / JpegParseError with a clear message (never a raw
    traceback) on malformed input.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("decode() expects raw JPEG bytes")

    frame = markers.parse(data)  # raises JpegParseError on malformed input
    if frame.progressive:
        raise JpegDecodeError("this is a progressive JPEG; use progressive.decode() instead")

    width, height = frame.width, frame.height
    hmax = max(c["h"] for c in frame.components)
    vmax = max(c["v"] for c in frame.components)
    mcu_w, mcu_h = 8 * hmax, 8 * vmax
    mcus_x = -(-width // mcu_w)
    mcus_y = -(-height // mcu_h)
    frame._mcus_x, frame._mcus_y = mcus_x, mcus_y

    comps_by_id = {}
    for c in frame.components:
        c = dict(c)
        c["blocks_x"] = mcus_x * c["h"]
        c["blocks_y"] = mcus_y * c["v"]
        c["coeffs"] = [[0] * 64 for _ in range(c["blocks_x"] * c["blocks_y"])]
        comps_by_id[c["id"]] = c

    if len(frame.scans) != 1:
        raise JpegDecodeError(f"baseline decoder expects exactly one scan, found {len(frame.scans)}")
    scan_components, ss, se, ah, al = frame.scans[0][:5]
    entropy_bytes = frame.scans[0][5]
    if set(cid for cid, _, _ in scan_components) != set(comps_by_id):
        raise JpegDecodeError("baseline scan does not cover every frame component")

    decode_baseline_scan(frame, scan_components, entropy_bytes, comps_by_id)

    planes = reconstruct_planes(frame, comps_by_id)

    y_plane, y_pw, _ = planes[1]
    y_full = colorspace.crop_plane(y_plane, y_pw, width, height)

    def chroma_full(cid):
        comp = comps_by_id[cid]
        plane, pw, _ = planes[cid]
        hsub = hmax // comp["h"]
        vsub = vmax // comp["v"]
        sub_w = -(-width // hsub)
        sub_h = -(-height // vsub)
        cropped = colorspace.crop_plane(plane, pw, sub_w, sub_h)
        if hsub == 1 and vsub == 1:
            return cropped
        return colorspace.upsample_plane(cropped, sub_w, sub_h, hsub, vsub, width, height)

    cb_full = chroma_full(2)
    cr_full = chroma_full(3)

    return colorspace.Image.from_ycbcr_planes(width, height, y_full, cb_full, cr_full)
