"""Progressive JPEG (SOF2): the same DCT/quantization core as the
baseline encoder, but coefficients are split across multiple scans so
the image can be displayed coarse-to-fine as data arrives, instead of
top-to-bottom as one pass completes.

Two successive-approximation/spectral-selection techniques are combined:

  * **DC successive approximation** (2 scans): the first DC scan sends
    every block's DC coefficient with its lowest bit dropped (a coarse,
    blocky per-block-average preview of the whole image); a second,
    literally-raw-bit (no Huffman at all -- ITU-T T.81 G.1.2.1) DC
    refinement scan sends that dropped bit back.
  * **AC spectral selection** (2 non-interleaved scans per component):
    low AC frequencies (coarse texture/edges) are sent in one scan per
    component, the remaining higher frequencies (fine detail) in
    another. AC scans in progressive JPEG are restricted to a single
    component at a time (unlike DC and unlike every baseline scan).

AC successive approximation (bit-refining the AC coefficients the same
way DC is refined) is *not* implemented -- it requires a materially
different, notoriously fiddly refinement algorithm (correction bits
interleaved with runs of already-nonzero coefficients). Spectral
selection alone already produces a real, visually-obvious progressive
reveal (structure first, detail after) with much lower implementation
risk; see REVIEW.md for the honest accounting of this scope choice.
"""
from . import bitstream, decoder, huffman, markers, quant
from .bitstream import bits_for_value, extend_receive
from .decoder import JpegDecodeError
from .encoder import forward_transform
from .layout import compute_layout, iter_mcu_blocks, noninterleaved_block_grid
from .markers import JpegParseError

AC_BANDS = [(1, 5), (6, 63)]


def is_progressive(data):
    """Cheap check used by the CLI to route decode() vs. progressive.decode()."""
    try:
        frame = markers.parse(data)
    except JpegParseError:
        return False
    return frame.progressive


def _ac_band_tokens(zigzag_block, ss, se):
    """RRRRSSSS run-length coding within [ss, se], same alphabet as
    baseline. Always terminates a block's band with EOB run-category 0
    (byte 0x00) rather than batching an EOB run across multiple blocks --
    a real, spec-legal simplification (T.81 G.1.2.2 permits any EOB run
    length >= 1; this codec always uses exactly 1), not an approximation.
    """
    tokens = []
    run = 0
    for k in range(ss, se + 1):
        v = zigzag_block[k]
        if v == 0:
            run += 1
            continue
        while run > 15:
            tokens.append((0xF0, 0, 0))  # ZRL
            run -= 16
        nb, coded = bits_for_value(v)
        tokens.append(((run << 4) | nb, coded, nb))
        run = 0
    if run > 0:
        tokens.append((0x00, 0, 0))  # EOB, run-category 0 (exactly this block)
    return tokens


def encode(image, quality=75, subsampling="420"):
    layout = compute_layout(image.width, image.height, subsampling)
    coeff_blocks, qtables = forward_transform(image, layout, quality)
    blocks_x_of = {c["name"]: c["blocks_x"] for c in layout["components"]}

    dc_luma = huffman.STD_TABLES[("dc", "luma")]
    dc_chroma = huffman.STD_TABLES[("dc", "chroma")]
    ac_luma = huffman.STD_TABLES[("ac", "luma")]
    ac_chroma = huffman.STD_TABLES[("ac", "chroma")]

    scans = []  # (scan_component_ids, ss, se, ah, al, entropy_bytes)
    all_ids = [(c["id"], 0 if c["name"] == "Y" else 1, 0 if c["name"] == "Y" else 1) for c in layout["components"]]

    # --- Scan 1: DC first (interleaved, Ah=0, Al=1) ---
    w1 = bitstream.BitWriter()
    dc_pred = {c["name"]: 0 for c in layout["components"]}
    for name, bx, by in iter_mcu_blocks(layout):
        zz = coeff_blocks[name][by * blocks_x_of[name] + bx]
        val = zz[0] >> 1
        diff = val - dc_pred[name]
        dc_pred[name] = val
        table = dc_luma if name == "Y" else dc_chroma
        nb, coded = bits_for_value(diff)
        table.encode_symbol(w1, nb)
        if nb:
            w1.write_bits(coded, nb)
    w1.align_byte()
    scans.append((all_ids, 0, 0, 0, 1, w1.getvalue()))

    # --- Scan 2: DC refine (interleaved, Ah=1, Al=0, raw bits, no Huffman) ---
    w2 = bitstream.BitWriter()
    for name, bx, by in iter_mcu_blocks(layout):
        zz = coeff_blocks[name][by * blocks_x_of[name] + bx]
        w2.write_bits(zz[0] & 1, 1)
    w2.align_byte()
    scans.append((all_ids, 0, 0, 1, 0, w2.getvalue()))

    # --- AC scans: 2 spectral bands per component, non-interleaved ---
    for comp in layout["components"]:
        name = comp["name"]
        bw = comp["blocks_x"]
        nbx, nby = noninterleaved_block_grid(image.width, image.height, layout["hmax"], layout["vmax"], comp)
        ac_table = ac_luma if name == "Y" else ac_chroma
        dc_id = 0 if name == "Y" else 1
        for ss, se in AC_BANDS:
            w = bitstream.BitWriter()
            for by in range(nby):
                for bx in range(nbx):
                    zz = coeff_blocks[name][by * bw + bx]
                    for symbol, extra, nb in _ac_band_tokens(zz, ss, se):
                        ac_table.encode_symbol(w, symbol)
                        if nb:
                            w.write_bits(extra, nb)
            w.align_byte()
            scans.append(([(comp["id"], dc_id, dc_id)], ss, se, 0, 0, w.getvalue()))

    luma = next(c for c in layout["components"] if c["name"] == "Y")
    out = bytearray()
    out += markers.write_soi()
    out += markers.write_jfif_app0()
    out += markers.write_dqt(0, quant.to_zigzag(qtables["luma"]))
    out += markers.write_dqt(1, quant.to_zigzag(qtables["chroma"]))
    out += markers.write_sof(
        image.width, image.height,
        [(1, luma["h"], luma["v"], 0), (2, 1, 1, 1), (3, 1, 1, 1)],
        progressive=True,
    )
    out += markers.write_dht(0, 0, dc_luma)
    out += markers.write_dht(0, 1, dc_chroma)
    out += markers.write_dht(1, 0, ac_luma)
    out += markers.write_dht(1, 1, ac_chroma)
    for scan_components, ss, se, ah, al, entropy in scans:
        out += markers.write_sos(scan_components, spectral_start=ss, spectral_end=se, ah=ah, al=al)
        out += entropy
    out += markers.write_eoi()
    return bytes(out)


def _decode_dc_first_scan(frame, scan_components, entropy_bytes, comps_by_id, mcus_x, mcus_y):
    dc_tables = {}
    for cid, dc_id, _ac_id in scan_components:
        if dc_id not in frame.dc_tables:
            raise JpegDecodeError(f"scan references undefined DC Huffman table {dc_id}")
        dc_tables[cid] = huffman.HuffmanTable(*frame.dc_tables[dc_id])
    reader = bitstream.BitReader(entropy_bytes)
    dc_pred = {cid: 0 for cid, _, _ in scan_components}
    for my in range(mcus_y):
        for mx in range(mcus_x):
            for cid, _dc_id, _ac_id in scan_components:
                comp = comps_by_id[cid]
                for v in range(comp["v"]):
                    by = my * comp["v"] + v
                    for h in range(comp["h"]):
                        bx = mx * comp["h"] + h
                        category = dc_tables[cid].decode_symbol(reader)
                        if category is None:
                            raise JpegDecodeError("unexpected end of entropy data decoding a progressive DC symbol")
                        if category > 11:
                            raise JpegDecodeError(f"invalid DC coefficient category {category}")
                        bits = reader.read_bits(category) if category else 0
                        if category and bits is None:
                            raise JpegDecodeError("unexpected end of entropy data reading DC magnitude bits")
                        diff = extend_receive(bits or 0, category)
                        dc_pred[cid] += diff
                        comp["coeffs"][by * comp["blocks_x"] + bx][0] = dc_pred[cid]


def _decode_dc_refine_scan(scan_components, entropy_bytes, comps_by_id, mcus_x, mcus_y):
    reader = bitstream.BitReader(entropy_bytes)
    for my in range(mcus_y):
        for mx in range(mcus_x):
            for cid, _dc_id, _ac_id in scan_components:
                comp = comps_by_id[cid]
                for v in range(comp["v"]):
                    by = my * comp["v"] + v
                    for h in range(comp["h"]):
                        bx = mx * comp["h"] + h
                        bit = reader.read_bit()
                        if bit is None:
                            raise JpegDecodeError("unexpected end of entropy data in a DC refinement scan")
                        block = comp["coeffs"][by * comp["blocks_x"] + bx]
                        block[0] = (block[0] << 1) | bit


def _decode_ac_band_scan(frame, scan_components, ss, se, entropy_bytes, comps_by_id, width, height, hmax, vmax):
    if len(scan_components) != 1:
        raise JpegDecodeError("progressive AC scans must contain exactly one component")
    cid, _dc_id, ac_id = scan_components[0]
    if cid not in comps_by_id:
        raise JpegDecodeError(f"AC scan references undefined component {cid}")
    if ac_id not in frame.ac_tables:
        raise JpegDecodeError(f"scan references undefined AC Huffman table {ac_id}")
    ac_table = huffman.HuffmanTable(*frame.ac_tables[ac_id])
    comp = comps_by_id[cid]
    nbx, nby = noninterleaved_block_grid(width, height, hmax, vmax, comp)
    reader = bitstream.BitReader(entropy_bytes)
    eobrun = 0
    for by in range(nby):
        for bx in range(nbx):
            block = comp["coeffs"][by * comp["blocks_x"] + bx]
            k = ss
            if eobrun > 0:
                eobrun -= 1
                continue
            while k <= se:
                symbol = ac_table.decode_symbol(reader)
                if symbol is None:
                    raise JpegDecodeError("unexpected end of entropy data decoding a progressive AC symbol")
                run = symbol >> 4
                size = symbol & 0x0F
                if size == 0:
                    if run == 15:
                        k += 16  # ZRL
                        continue
                    extra = reader.read_bits(run) if run else 0
                    if run and extra is None:
                        raise JpegDecodeError("unexpected end of entropy data reading an EOB run")
                    eobrun = (1 << run) + (extra or 0) - 1
                    break
                k += run
                if k > se:
                    raise JpegDecodeError("progressive AC coefficient run overflowed its spectral band")
                bits = reader.read_bits(size)
                if bits is None:
                    raise JpegDecodeError("unexpected end of entropy data reading AC magnitude bits")
                block[k] = extend_receive(bits, size)
                k += 1


def decode(data):
    """Decode a progressive JFIF byte string into a `colorspace.Image`."""
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("decode() expects raw JPEG bytes")

    frame = markers.parse(data)
    if not frame.progressive:
        raise JpegDecodeError("this is a baseline JPEG; use decoder.decode() instead")

    hmax, vmax, mcus_x, mcus_y, comps_by_id = decoder.setup_frame_geometry(frame)

    if not frame.scans:
        raise JpegDecodeError("progressive JPEG has no scans")
    for scan_components, ss, se, ah, al, entropy_bytes in frame.scans:
        if ss == 0:
            if len(scan_components) != 3 or set(cid for cid, _, _ in scan_components) != {1, 2, 3}:
                raise JpegDecodeError("progressive DC scans must be interleaved across all 3 components")
            if ah == 0:
                _decode_dc_first_scan(frame, scan_components, entropy_bytes, comps_by_id, mcus_x, mcus_y)
            else:
                _decode_dc_refine_scan(scan_components, entropy_bytes, comps_by_id, mcus_x, mcus_y)
        else:
            _decode_ac_band_scan(frame, scan_components, ss, se, entropy_bytes, comps_by_id, frame.width, frame.height, hmax, vmax)

    planes = decoder.reconstruct_planes(frame, comps_by_id)
    return decoder.planes_to_image(frame, comps_by_id, planes, hmax, vmax)
