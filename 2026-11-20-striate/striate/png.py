"""Minimal PNG / PGM codec on top of zlib. Decodes gray, gray+alpha, RGB, RGBA, palette (non-interlaced)."""
import struct
import zlib

SIG = b"\x89PNG\r\n\x1a\n"


class PNGError(ValueError):
    pass


def _chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def encode_gray(rows, width, height):
    """rows: list of bytes/bytearray, each `width` long, 8-bit grayscale."""
    raw = bytearray()
    for r in rows:
        raw.append(0)
        raw.extend(r)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return SIG + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + _chunk(b"IEND", b"")


def encode_rgb(rows, width, height):
    """rows: list of bytes of length 3*width."""
    raw = bytearray()
    for r in rows:
        raw.append(0)
        raw.extend(r)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return SIG + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + _chunk(b"IEND", b"")


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _unfilter(raw, width, height, bpp, stride):
    rows, prev, pos = [], bytearray(stride), 0
    for _ in range(height):
        if pos + 1 + stride > len(raw):
            raise PNGError("truncated image data")
        ft = raw[pos]; line = bytearray(raw[pos + 1:pos + 1 + stride]); pos += 1 + stride
        if ft == 0:
            pass
        elif ft == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 255
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif ft == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 255
        elif ft == 4:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                ul = prev[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + _paeth(left, prev[i], ul)) & 255
        else:
            raise PNGError(f"bad filter type {ft}")
        rows.append(line); prev = line
    return rows


def decode(data):
    """Return (width, height, rows_of_gray_bytearrays). Colour is converted with Rec.601 luma."""
    if data[:8] != SIG:
        raise PNGError("not a PNG file")
    pos, idat, plte, hdr = 8, bytearray(), None, None
    while pos + 8 <= len(data):
        ln, tag = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + ln]
        if len(body) < ln:
            raise PNGError("truncated chunk")
        pos += 12 + ln
        if tag == b"IHDR":
            hdr = struct.unpack(">IIBBBBB", body)
        elif tag == b"PLTE":
            plte = body
        elif tag == b"IDAT":
            idat.extend(body)
        elif tag == b"IEND":
            break
    if hdr is None or not idat:
        raise PNGError("missing IHDR/IDAT")
    w, h, depth, ctype, _, _, interlace = hdr
    if interlace:
        raise PNGError("interlaced PNGs are not supported")
    if w == 0 or h == 0 or w * h > 64_000_000:
        raise PNGError("unreasonable image size")
    chans = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if chans is None or depth not in (1, 2, 4, 8, 16) or (ctype != 0 and ctype != 3 and depth < 8) or (ctype == 3 and depth == 16):
        raise PNGError(f"unsupported PNG format (type {ctype}, depth {depth})")
    bits = chans * depth
    stride = (w * bits + 7) // 8
    bpp = max(1, bits // 8)
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as e:
        raise PNGError(f"corrupt image data: {e}")
    rows = _unfilter(raw, w, h, bpp, stride)
    out = []
    for line in rows:
        if depth < 8:
            vals = bytearray()
            mask = (1 << depth) - 1
            for i in range(w):
                bit = i * depth
                vals.append((line[bit >> 3] >> (8 - depth - (bit & 7))) & mask)
            if ctype == 3:
                if plte is None:
                    raise PNGError("palette missing")
                out.append(bytearray(_luma(plte[3 * v:3 * v + 3]) for v in vals))
            else:
                scale = 255 // mask
                out.append(bytearray(v * scale for v in vals))
        elif ctype == 3:
            if plte is None:
                raise PNGError("palette missing")
            out.append(bytearray(_luma(plte[3 * v:3 * v + 3]) for v in line[:w]))
        else:
            step = depth // 8
            px = line[::step] if step == 2 else line  # 16-bit: keep high byte
            if step == 2:
                px = bytearray(line[i] for i in range(0, len(line), 2))
            if ctype == 0:
                out.append(bytearray(px[:w]))
            elif ctype == 4:
                out.append(bytearray(px[0:2 * w:2]))
            else:
                n = 3 if ctype == 2 else 4
                out.append(bytearray((299 * px[i] + 587 * px[i + 1] + 114 * px[i + 2]) // 1000 for i in range(0, n * w, n)))
    return w, h, out


def _luma(rgb):
    if len(rgb) < 3:
        raise PNGError("bad palette index")
    return (299 * rgb[0] + 587 * rgb[1] + 114 * rgb[2]) // 1000


def decode_pgm(data):
    """Binary (P5) or ASCII (P2) PGM."""
    toks, i, n = [], 0, len(data)
    magic = data[:2]
    if magic not in (b"P5", b"P2"):
        raise PNGError("not a PGM file")
    i = 2
    while len(toks) < 3:
        while i < n and data[i:i + 1].isspace():
            i += 1
        if i < n and data[i:i + 1] == b"#":
            while i < n and data[i:i + 1] != b"\n":
                i += 1
            continue
        j = i
        while j < n and not data[j:j + 1].isspace():
            j += 1
        toks.append(int(data[i:j])); i = j
    w, h, mx = toks
    if mx > 255 or mx < 1:
        raise PNGError("only 8-bit PGM supported")
    if magic == b"P5":
        body = data[i + 1:i + 1 + w * h]
        if len(body) < w * h:
            raise PNGError("truncated PGM")
        vals = list(body)
    else:
        vals = [int(x) for x in data[i:].split()][: w * h]
        if len(vals) < w * h:
            raise PNGError("truncated PGM")
    vals = [v * 255 // mx for v in vals]
    return w, h, [bytearray(vals[r * w:(r + 1) * w]) for r in range(h)]


def load(path):
    """Load PNG or PGM from path -> (w, h, rows)."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] == SIG:
        return decode(data)
    if data[:2] in (b"P5", b"P2"):
        return decode_pgm(data)
    raise PNGError("unrecognised image format (need PNG or PGM)")
