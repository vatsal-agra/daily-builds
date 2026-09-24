"""JFIF/JPEG marker segment writing and a tolerant parser.

A JPEG file is a sequence of marker segments (each starting with 0xFF and
a marker-type byte) plus, after the Start-Of-Scan marker, raw
entropy-coded bit data. This module only knows about marker *framing* --
building/parsing the segments themselves and handing the compressed scan
bytes off to the caller; it knows nothing about DCT/Huffman/quantization.
"""
import struct

SOI = 0xD8
EOI = 0xD9
APP0 = 0xE0
DQT = 0xDB
SOF0 = 0xC0  # baseline DCT, sequential, Huffman
SOF2 = 0xC2  # progressive DCT, Huffman
DHT = 0xC4
SOS = 0xDA
DRI = 0xDD
RST0 = 0xD0  # RST0..RST7 = 0xD0..0xD7


class JpegParseError(Exception):
    pass


def marker(code):
    return bytes([0xFF, code])


def _segment(code, payload):
    length = len(payload) + 2
    if length > 0xFFFF:
        raise ValueError("marker segment too large")
    return marker(code) + struct.pack(">H", length) + payload


def write_soi():
    return marker(SOI)


def write_eoi():
    return marker(EOI)


def write_jfif_app0():
    payload = b"JFIF\x00" + bytes([1, 1]) + bytes([0]) + struct.pack(">HH", 1, 1) + bytes([0, 0])
    return _segment(APP0, payload)


def write_dqt(table_id, qtable_zigzag):
    """qtable_zigzag: 64 ints, already in zigzag order, precision 8-bit."""
    payload = bytes([table_id & 0x0F]) + bytes(qtable_zigzag)
    return _segment(DQT, payload)


def write_sof(width, height, components, progressive=False):
    """components: list of (component_id, h, v, qtable_id)."""
    payload = bytearray()
    payload.append(8)  # sample precision
    payload += struct.pack(">HH", height, width)
    payload.append(len(components))
    for cid, h, v, qid in components:
        payload.append(cid)
        payload.append(((h & 0x0F) << 4) | (v & 0x0F))
        payload.append(qid)
    return _segment(SOF2 if progressive else SOF0, bytes(payload))


def write_dht(table_class, table_id, huff_table):
    """table_class: 0=DC, 1=AC."""
    tc_th = ((table_class & 0x0F) << 4) | (table_id & 0x0F)
    payload = bytes([tc_th]) + huff_table.as_marker_bytes()
    return _segment(DHT, payload)


def write_sos(scan_components, spectral_start=0, spectral_end=63, ah=0, al=0):
    """scan_components: list of (component_id, dc_table_id, ac_table_id)."""
    payload = bytearray()
    payload.append(len(scan_components))
    for cid, dc_id, ac_id in scan_components:
        payload.append(cid)
        payload.append(((dc_id & 0x0F) << 4) | (ac_id & 0x0F))
    payload.append(spectral_start)
    payload.append(spectral_end)
    payload.append(((ah & 0x0F) << 4) | (al & 0x0F))
    return _segment(SOS, bytes(payload))


def write_dri(restart_interval):
    return _segment(DRI, struct.pack(">H", restart_interval))


class ParsedFrame:
    def __init__(self):
        self.width = 0
        self.height = 0
        self.progressive = False
        self.components = []  # list of dict: id,h,v,qtable_id
        self.qtables = {}  # id -> 64 ints, natural order
        self.dc_tables = {}  # id -> (bits, values)
        self.ac_tables = {}  # id -> (bits, values)
        self.restart_interval = 0
        self.scans = []  # list of (scan_components, ss, se, ah, al, entropy_data)


def parse(data):
    """Tolerant JPEG parser: raises JpegParseError with a clear message on
    malformed input instead of an opaque exception/traceback.
    """
    if len(data) < 4 or data[0] != 0xFF or data[1] != SOI:
        raise JpegParseError("not a JPEG file (missing SOI marker)")

    pos = 2
    frame = ParsedFrame()
    n = len(data)

    while True:
        if pos + 1 >= n:
            raise JpegParseError("truncated JPEG: ran out of data looking for a marker")
        if data[pos] != 0xFF:
            raise JpegParseError(f"corrupt JPEG: expected marker byte 0xFF at offset {pos}")
        code = data[pos + 1]
        while code == 0xFF:  # fill bytes before a real marker are legal
            pos += 1
            if pos + 1 >= n:
                raise JpegParseError("truncated JPEG inside marker fill bytes")
            code = data[pos + 1]
        pos += 2

        if code == EOI:
            break
        if code == SOI:
            continue

        if pos + 1 >= n:
            raise JpegParseError(f"truncated JPEG: marker 0x{code:02X} has no length field")
        seg_len = struct.unpack(">H", data[pos:pos + 2])[0]
        if seg_len < 2 or pos + seg_len > n:
            raise JpegParseError(f"corrupt JPEG: bad segment length for marker 0x{code:02X}")
        payload = data[pos + 2:pos + seg_len]
        pos += seg_len

        if code == APP0 or (0xE1 <= code <= 0xEF) or code == 0xFE:
            pass  # APPn / COM: not needed for decoding
        elif code == DQT:
            _parse_dqt(payload, frame)
        elif code in (SOF0, SOF2):
            frame.progressive = (code == SOF2)
            _parse_sof(payload, frame)
        elif code == DHT:
            _parse_dht(payload, frame)
        elif code == DRI:
            frame.restart_interval = struct.unpack(">H", payload[:2])[0]
        elif code == SOS:
            scan_components, ss, se, ah, al = _parse_sos_header(payload)
            entropy_start = pos
            entropy_end, next_pos = _find_scan_end(data, entropy_start)
            frame.scans.append((scan_components, ss, se, ah, al, data[entropy_start:entropy_end]))
            pos = next_pos
        elif 0xD0 <= code <= 0xD7:
            pass  # bare restart marker outside a scan: ignore
        else:
            pass  # unknown/unsupported marker: skip, tolerant of extensions

    if frame.width == 0:
        raise JpegParseError("no SOF (frame header) marker found")
    if not frame.scans:
        raise JpegParseError("no SOS (scan) marker found")
    return frame


def _parse_dqt(payload, frame):
    from .quant import from_zigzag
    pos = 0
    while pos < len(payload):
        pq_tq = payload[pos]
        pq = pq_tq >> 4
        tq = pq_tq & 0x0F
        pos += 1
        if pq == 0:
            vals = list(payload[pos:pos + 64])
            pos += 64
        else:
            vals = list(struct.unpack(">64H", payload[pos:pos + 128]))
            pos += 128
        frame.qtables[tq] = from_zigzag(vals)


def _parse_sof(payload, frame):
    if len(payload) < 6:
        raise JpegParseError("truncated SOF segment")
    precision = payload[0]
    if precision != 8:
        raise JpegParseError(f"unsupported sample precision {precision} (only 8-bit supported)")
    frame.height, frame.width = struct.unpack(">HH", payload[1:5])
    if frame.width == 0 or frame.height == 0:
        raise JpegParseError("SOF declares zero width or height")
    ncomp = payload[5]
    pos = 6
    for _ in range(ncomp):
        if pos + 3 > len(payload):
            raise JpegParseError("truncated SOF component list")
        cid = payload[pos]
        hv = payload[pos + 1]
        qid = payload[pos + 2]
        h, v = hv >> 4, hv & 0x0F
        if h == 0 or v == 0:
            raise JpegParseError(f"component {cid} has zero sampling factor")
        frame.components.append({"id": cid, "h": h, "v": v, "qtable_id": qid})
        pos += 3


def _parse_dht(payload, frame):
    pos = 0
    while pos < len(payload):
        tc_th = payload[pos]
        tc = tc_th >> 4
        th = tc_th & 0x0F
        pos += 1
        if pos + 16 > len(payload):
            raise JpegParseError("truncated DHT segment (bits array)")
        bits = list(payload[pos:pos + 16])
        pos += 16
        nvals = sum(bits)
        if pos + nvals > len(payload):
            raise JpegParseError("truncated DHT segment (values array)")
        vals = list(payload[pos:pos + nvals])
        pos += nvals
        if tc == 0:
            frame.dc_tables[th] = (bits, vals)
        else:
            frame.ac_tables[th] = (bits, vals)


def _parse_sos_header(payload):
    ns = payload[0]
    pos = 1
    scan_components = []
    for _ in range(ns):
        cid = payload[pos]
        td_ta = payload[pos + 1]
        scan_components.append((cid, td_ta >> 4, td_ta & 0x0F))
        pos += 2
    ss, se, ahal = payload[pos], payload[pos + 1], payload[pos + 2]
    return scan_components, ss, se, ahal >> 4, ahal & 0x0F


def _find_scan_end(data, start):
    """Entropy-coded data runs until the next marker that isn't a stuffed
    0xFF00 or a restart marker (RST0-RST7, which are part of the scan).
    Returns (entropy_data_end, position_after_it_to_resume_marker_parsing).
    """
    pos = start
    n = len(data)
    while pos < n:
        if data[pos] == 0xFF:
            if pos + 1 >= n:
                return pos, pos
            nxt = data[pos + 1]
            if nxt == 0x00:
                pos += 2
                continue
            if 0xD0 <= nxt <= 0xD7:
                pos += 2
                continue
            return pos, pos
        pos += 1
    return pos, pos
