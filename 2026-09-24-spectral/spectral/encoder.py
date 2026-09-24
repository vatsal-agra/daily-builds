"""The baseline sequential JPEG encoder: RGB -> valid JFIF bytes.

Pipeline: RGB -> YCbCr -> chroma subsample -> 8x8 block split -> level
shift -> forward DCT -> quantize -> zigzag -> DC-diff/AC-run-length ->
Huffman -> byte-stuffed bitstream -> marker-framed JFIF file.
"""
from . import colorspace, dct, quant, huffman, bitstream, markers, entropy
from .layout import compute_layout, iter_mcu_blocks


def _extract_block(plane, padded_w, bx, by):
    block = [0.0] * 64
    base_y, base_x = by * 8, bx * 8
    for r in range(8):
        row_off = (base_y + r) * padded_w + base_x
        for c in range(8):
            block[r * 8 + c] = plane[row_off + c] - 128.0
    return block


def forward_transform(image, layout, quality):
    """RGB image -> per-component quantized zigzag coefficient blocks."""
    width, height = image.width, image.height
    y_full, cb_full, cr_full = image.to_ycbcr_planes()
    src_planes = {"Y": y_full, "Cb": cb_full, "Cr": cr_full}

    qtables = {
        "luma": quant.scale_qtable(quant.STD_LUMA_QTABLE, quality),
        "chroma": quant.scale_qtable(quant.STD_CHROMA_QTABLE, quality),
    }

    coeff_blocks = {}
    for comp in layout["components"]:
        name = comp["name"]
        src = src_planes[name]
        if comp["hsub"] > 1 or comp["vsub"] > 1:
            sub_plane, sub_w, sub_h = colorspace.subsample_plane(
                src, width, height, comp["hsub"], comp["vsub"]
            )
        else:
            sub_plane, sub_w, sub_h = src, width, height
        padded = colorspace.pad_plane(sub_plane, sub_w, sub_h, comp["padded_w"], comp["padded_h"])

        qtable = qtables[comp["qkind"]]
        bw, bh = comp["blocks_x"], comp["blocks_y"]
        blocks = [None] * (bw * bh)
        for by in range(bh):
            for bx in range(bw):
                block = _extract_block(padded, comp["padded_w"], bx, by)
                coeffs = dct.dct_2d(block)
                qz = quant.quantize(coeffs, qtable)
                blocks[by * bw + bx] = quant.to_zigzag(qz)
        coeff_blocks[name] = blocks
    return coeff_blocks, qtables


def _blocks_per_component(layout, coeff_blocks):
    for name, bx, by in iter_mcu_blocks(layout):
        bw = next(c["blocks_x"] for c in layout["components"] if c["name"] == name)
        yield name, coeff_blocks[name][by * bw + bx]


def collect_frequencies(layout, coeff_blocks):
    """First pass: what Huffman symbols would this image's coefficients
    actually produce, per table kind? Used to build optimized tables.
    """
    freqs = {"dc_luma": {}, "dc_chroma": {}, "ac_luma": {}, "ac_chroma": {}}
    dc_pred = {c["name"]: 0 for c in layout["components"]}
    for name, zz in _blocks_per_component(layout, coeff_blocks):
        new_pred, tokens = entropy.block_symbols(zz, dc_pred[name])
        dc_pred[name] = new_pred
        is_luma = name == "Y"
        for kind, sym, _extra, _nbits in tokens:
            key = f"{kind}_{'luma' if is_luma else 'chroma'}"
            freqs[key][sym] = freqs[key].get(sym, 0) + 1
    return freqs


def write_scan(layout, coeff_blocks, tables):
    """Second pass: actually emit the Huffman-coded, byte-stuffed scan
    bitstream using the given (possibly optimized) tables.
    """
    writer = bitstream.BitWriter()
    dc_pred = {c["name"]: 0 for c in layout["components"]}
    for name, zz in _blocks_per_component(layout, coeff_blocks):
        new_pred, tokens = entropy.block_symbols(zz, dc_pred[name])
        dc_pred[name] = new_pred
        is_luma = name == "Y"
        dc_table = tables["dc_luma"] if is_luma else tables["dc_chroma"]
        ac_table = tables["ac_luma"] if is_luma else tables["ac_chroma"]
        for kind, sym, extra, nbits in tokens:
            table = dc_table if kind == entropy.DC else ac_table
            table.encode_symbol(writer, sym)
            if nbits:
                writer.write_bits(extra, nbits)
    writer.align_byte()
    return writer.getvalue()


def build_tables(layout, coeff_blocks, optimize=False):
    if not optimize:
        return {
            "dc_luma": huffman.STD_TABLES[("dc", "luma")],
            "dc_chroma": huffman.STD_TABLES[("dc", "chroma")],
            "ac_luma": huffman.STD_TABLES[("ac", "luma")],
            "ac_chroma": huffman.STD_TABLES[("ac", "chroma")],
        }
    freqs = collect_frequencies(layout, coeff_blocks)
    dc_luma, _ = huffman.optimize_table(freqs["dc_luma"], huffman.STD_DC_LUMA_BITS, huffman.STD_DC_LUMA_VALS)
    dc_chroma, _ = huffman.optimize_table(freqs["dc_chroma"], huffman.STD_DC_CHROMA_BITS, huffman.STD_DC_CHROMA_VALS)
    ac_luma, _ = huffman.optimize_table(freqs["ac_luma"], huffman.STD_AC_LUMA_BITS, huffman.STD_AC_LUMA_VALS)
    ac_chroma, _ = huffman.optimize_table(freqs["ac_chroma"], huffman.STD_AC_CHROMA_BITS, huffman.STD_AC_CHROMA_VALS)
    return {"dc_luma": dc_luma, "dc_chroma": dc_chroma, "ac_luma": ac_luma, "ac_chroma": ac_chroma}


def encode(image, quality=75, subsampling="420", optimize_huffman=False):
    """Encode an RGB `colorspace.Image` to a full, valid baseline JFIF
    byte string.
    """
    if image.width <= 0 or image.height <= 0:
        raise ValueError("image must have positive width and height")
    if image.width > 65535 or image.height > 65535:
        raise ValueError("image dimensions must fit in JPEG's 16-bit SOF fields")

    layout = compute_layout(image.width, image.height, subsampling)
    coeff_blocks, qtables = forward_transform(image, layout, quality)
    tables = build_tables(layout, coeff_blocks, optimize=optimize_huffman)
    entropy_data = write_scan(layout, coeff_blocks, tables)

    luma = next(c for c in layout["components"] if c["name"] == "Y")
    out = bytearray()
    out += markers.write_soi()
    out += markers.write_jfif_app0()
    out += markers.write_dqt(0, quant.to_zigzag(qtables["luma"]))
    out += markers.write_dqt(1, quant.to_zigzag(qtables["chroma"]))
    out += markers.write_sof(
        image.width, image.height,
        [(1, luma["h"], luma["v"], 0), (2, 1, 1, 1), (3, 1, 1, 1)],
    )
    out += markers.write_dht(0, 0, tables["dc_luma"])
    out += markers.write_dht(0, 1, tables["dc_chroma"])
    out += markers.write_dht(1, 0, tables["ac_luma"])
    out += markers.write_dht(1, 1, tables["ac_chroma"])
    out += markers.write_sos([(1, 0, 0), (2, 1, 1), (3, 1, 1)])
    out += entropy_data
    out += markers.write_eoi()
    return bytes(out)
