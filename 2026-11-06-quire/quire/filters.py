"""Stream filters. decode_stream() applies every non-image filter in the chain and
stops (returning the remaining image filter name) at DCTDecode/JPXDecode/CCITTFaxDecode/JBIG2Decode."""
import re
import zlib

IMAGE_FILTERS = ("DCTDecode", "DCT", "JPXDecode", "CCITTFaxDecode", "CCF", "JBIG2Decode")
ABBREV = {"Fl": "FlateDecode", "AHx": "ASCIIHexDecode", "A85": "ASCII85Decode", "LZW": "LZWDecode",
          "RL": "RunLengthDecode", "DCT": "DCTDecode", "CCF": "CCITTFaxDecode"}


class FilterError(Exception):
    pass


def flate(data):
    """Inflate, tolerating truncated or corrupt tails (returns what was recovered)."""
    try:
        return zlib.decompress(data)
    except zlib.error:
        pass
    out = bytearray()
    d = zlib.decompressobj()
    # feed in chunks so a corrupt tail only loses the tail
    for i in range(0, len(data), 256):
        try:
            out += d.decompress(data[i:i + 256])
        except zlib.error:
            break
    if out:
        return bytes(out)
    # maybe a raw deflate stream without zlib header
    try:
        return zlib.decompress(data, -15)
    except zlib.error:
        pass
    # leading garbage (e.g. a stray newline before the zlib header)
    s = data.lstrip(b"\r\n \x00")
    if s != data and s:
        return flate(s)
    raise FilterError("cannot inflate stream")


def ascii_hex(data):
    end = data.find(b">")
    body = re.sub(rb"[^0-9A-Fa-f]", b"", data if end < 0 else data[:end])
    if len(body) % 2:
        body += b"0"
    return bytes.fromhex(body.decode())


def ascii85(data):
    data = data.strip()
    if data.startswith(b"<~"):
        data = data[2:]
    e = data.find(b"~>")
    if e >= 0:
        data = data[:e]
    out = bytearray()
    group = []
    for c in data:
        if c in b" \t\r\n\f\x00":
            continue
        if c == 0x7A and not group:  # 'z'
            out += b"\0\0\0\0"
            continue
        if not 0x21 <= c <= 0x75:
            raise FilterError("bad ASCII85 byte")
        group.append(c - 33)
        if len(group) == 5:
            v = 0
            for g in group:
                v = v * 85 + g
            out += (v & 0xFFFFFFFF).to_bytes(4, "big")
            group = []
    if group:
        n = len(group)
        if n == 1:
            raise FilterError("bad ASCII85 tail")
        group += [84] * (5 - n)
        v = 0
        for g in group:
            v = v * 85 + g
        out += (v & 0xFFFFFFFF).to_bytes(4, "big")[:n - 1]
    return bytes(out)


def lzw(data, early=1):
    out = bytearray()
    table = [bytes([i]) for i in range(256)] + [b"", b""]
    bits, nbits, width, prev = 0, 0, 9, None
    for byte in data:
        bits = (bits << 8) | byte
        nbits += 8
        while nbits >= width:
            code = (bits >> (nbits - width)) & ((1 << width) - 1)
            nbits -= width
            bits &= (1 << nbits) - 1
            if code == 256:
                table = table[:258]
                width, prev = 9, None
                continue
            if code == 257:
                return bytes(out)
            if prev is None:
                if code >= len(table):
                    raise FilterError("bad LZW code")
                entry = table[code]
            else:
                if code < len(table):
                    entry = table[code]
                    table.append(prev + entry[:1])
                elif code == len(table):
                    entry = prev + prev[:1]
                    table.append(entry)
                else:
                    raise FilterError("bad LZW code")
            out += entry
            prev = entry
            n = len(table) + early
            width = 9 if n < 512 else 10 if n < 1024 else 11 if n < 2048 else 12
    return bytes(out)


def run_length(data):
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        c = data[i]
        i += 1
        if c == 128:
            break
        if c < 128:
            out += data[i:i + c + 1]
            i += c + 1
        else:
            if i < n:
                out += bytes([data[i]]) * (257 - c)
            i += 1
    return bytes(out)


def predictor(data, parms):
    pred = parms.get("Predictor", 1) or 1
    if pred == 1:
        return data
    colors = parms.get("Colors", 1) or 1
    bpc = parms.get("BitsPerComponent", 8) or 8
    cols = parms.get("Columns", 1) or 1
    bpp = max(1, (colors * bpc + 7) // 8)
    rowlen = (colors * bpc * cols + 7) // 8
    if pred == 2:  # TIFF
        if bpc != 8:
            raise FilterError("TIFF predictor only for 8-bit")
        out = bytearray(data)
        for r in range(0, len(out) - rowlen + 1, rowlen):
            for i in range(r + bpp, r + rowlen):
                out[i] = (out[i] + out[i - bpp]) & 0xFF
        return bytes(out)
    out = bytearray()
    prev = bytearray(rowlen)
    pos = 0
    n = len(data)
    while pos < n:
        ft = data[pos]
        row = bytearray(data[pos + 1:pos + 1 + rowlen])
        pos += 1 + rowlen
        if len(row) < rowlen:
            row += bytes(rowlen - len(row))
        if ft == 1:
            for i in range(bpp, rowlen):
                row[i] = (row[i] + row[i - bpp]) & 0xFF
        elif ft == 2:
            for i in range(rowlen):
                row[i] = (row[i] + prev[i]) & 0xFF
        elif ft == 3:
            for i in range(rowlen):
                left = row[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ft == 4:
            for i in range(rowlen):
                a = row[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if pa <= pb and pa <= pc else b if pb <= pc else c
                row[i] = (row[i] + pr) & 0xFF
        out += row
        prev = row
    return bytes(out)


def filter_chain(sd, resolve):
    f = resolve(sd.get("Filter"))
    p = resolve(sd.get("DecodeParms", sd.get("DP")))
    if f is None:
        return []
    if not isinstance(f, list):
        f = [f]
        p = [p]
    else:
        p = p if isinstance(p, list) else [p] * len(f)
    p = list(p) + [None] * (len(f) - len(p))
    out = []
    for name, parm in zip(f, p):
        name = ABBREV.get(str(resolve(name)), str(resolve(name)))
        parm = resolve(parm) or {}
        parm = {k: resolve(v) for k, v in parm.items()} if isinstance(parm, dict) else {}
        out.append((name, parm))
    return out


def decode_stream(raw, chain):
    """Returns (bytes, remaining_image_filter or None, its parms)."""
    data = raw
    for i, (name, parm) in enumerate(chain):
        if name == "FlateDecode":
            data = predictor(flate(data), parm)
        elif name == "LZWDecode":
            data = predictor(lzw(data, parm.get("EarlyChange", 1)), parm)
        elif name == "ASCIIHexDecode":
            data = ascii_hex(data)
        elif name == "ASCII85Decode":
            data = ascii85(data)
        elif name == "RunLengthDecode":
            data = run_length(data)
        elif name == "Crypt":
            pass
        elif name in IMAGE_FILTERS:
            return data, name, parm
        else:
            raise FilterError(f"unsupported filter {name}")
    return data, None, None
