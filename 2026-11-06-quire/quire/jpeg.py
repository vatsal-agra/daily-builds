"""JPEG decoder: baseline + extended sequential + progressive Huffman, restart markers,
subsampling, Adobe APP14 colour transform. Returns interleaved 8-bit samples."""
import math
import struct

ZZ = [0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5, 12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6, 7, 14, 21,
      28, 35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51, 58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61,
      54, 47, 55, 62, 63]


class JpegError(Exception):
    pass


class _Huff:
    def __init__(self, counts, symbols):
        self.lookup = {}
        code = 0
        k = 0
        for ln in range(1, 17):
            for _ in range(counts[ln - 1]):
                self.lookup[(ln, code)] = symbols[k]
                k += 1
                code += 1
            code <<= 1


class _Bits:
    def __init__(self, data, pos):
        self.d = data
        self.p = pos
        self.acc = 0
        self.n = 0
        self.marker = None

    def bit(self):
        if self.n == 0:
            d = self.d
            if self.p >= len(d):
                b = 0
            else:
                b = d[self.p]
                self.p += 1
                if b == 0xFF:
                    b2 = d[self.p] if self.p < len(d) else 0
                    if b2 == 0:
                        self.p += 1
                    else:
                        self.marker = b2
                        self.p -= 1
                        b = 0
            self.acc = b
            self.n = 8
        self.n -= 1
        return (self.acc >> self.n) & 1

    def bits(self, k):
        v = 0
        for _ in range(k):
            v = (v << 1) | self.bit()
        return v

    def decode(self, h):
        code = 0
        look = h.lookup
        for ln in range(1, 17):
            code = (code << 1) | self.bit()
            s = look.get((ln, code))
            if s is not None:
                return s
        raise JpegError("bad Huffman code")

    def receive_extend(self, s):
        if s == 0:
            return 0
        v = self.bits(s)
        return v if v >= (1 << (s - 1)) else v - (1 << s) + 1

    def reset(self):
        self.acc = 0
        self.n = 0
        self.marker = None


_COS = [[math.cos((2 * x + 1) * u * math.pi / 16) * (math.sqrt(0.5) if u == 0 else 1.0) / 2.0 for u in range(8)] for x in range(8)]


def _idct(block, q):
    """block: 64 coeffs in natural order (dequantised inside). Returns 64 ints 0..255."""
    # DC-only fast path
    if not any(block[1:]):
        v = block[0] * q[0] / 8.0 + 128.5
        v = 0 if v < 0 else 255 if v > 255 else int(v)
        return [v] * 64
    c = [block[i] * q[i] for i in range(64)]
    tmp = [0.0] * 64
    for v in range(8):  # columns: sum over u (rows of coeff matrix index = v*8+u)
        row = c[v * 8:v * 8 + 8]
        if not any(row):
            continue
        for x in range(8):
            cx = _COS[x]
            tmp[v * 8 + x] = (row[0] * cx[0] + row[1] * cx[1] + row[2] * cx[2] + row[3] * cx[3] + row[4] * cx[4]
                              + row[5] * cx[5] + row[6] * cx[6] + row[7] * cx[7])
    out = [0] * 64
    for x in range(8):
        col = [tmp[v * 8 + x] for v in range(8)]
        for y in range(8):
            cy = _COS[y]
            s = (col[0] * cy[0] + col[1] * cy[1] + col[2] * cy[2] + col[3] * cy[3] + col[4] * cy[4] + col[5] * cy[5]
                 + col[6] * cy[6] + col[7] * cy[7]) + 128.5
            out[y * 8 + x] = 0 if s < 0 else 255 if s > 255 else int(s)
    return out


def decode_jpeg(data):
    """-> (width, height, ncomp, bytes interleaved). Raises JpegError for anything undecodable."""
    try:
        return _decode(data)
    except (IndexError, KeyError, struct.error, ValueError, ZeroDivisionError, TypeError) as e:
        raise JpegError(f"corrupt JPEG ({type(e).__name__}: {e})") from e


def _decode(data):
    if data[:2] != b"\xff\xd8":
        raise JpegError("not a JPEG")
    p = 2
    qt = {}
    hts = {}
    comps = []
    W = H = 0
    progressive = False
    restart = 0
    adobe = None
    coeffs = None
    eobrun = 0
    frame = None
    while p < len(data):
        if data[p] != 0xFF:
            p += 1
            continue
        while p < len(data) and data[p] == 0xFF:
            p += 1
        if p >= len(data):
            break
        m = data[p]
        p += 1
        if m == 0xD8 or 0xD0 <= m <= 0xD7 or m == 0x01 or m == 0:
            continue
        if m == 0xD9:
            break
        if p + 2 > len(data):
            break
        ln = struct.unpack(">H", data[p:p + 2])[0]
        seg = data[p + 2:p + ln]
        if m == 0xDB:
            i = 0
            while i < len(seg):
                pq, tq = seg[i] >> 4, seg[i] & 15
                i += 1
                if pq == 0:
                    vals = list(seg[i:i + 64])
                    i += 64
                else:
                    vals = list(struct.unpack(">64H", seg[i:i + 128]))
                    i += 128
                tbl = [0] * 64
                for k in range(64):
                    tbl[ZZ[k]] = vals[k]
                qt[tq] = tbl
        elif m in (0xC0, 0xC1, 0xC2):
            progressive = m == 0xC2
            prec, H, W, nc = struct.unpack(">BHHB", seg[:6])
            if prec != 8:
                raise JpegError("only 8-bit JPEG supported")
            comps = []
            for i in range(nc):
                cid, hv, tq = seg[6 + 3 * i], seg[7 + 3 * i], seg[8 + 3 * i]
                comps.append({"id": cid, "h": hv >> 4, "v": hv & 15, "tq": tq, "pred": 0})
            hmax = max(c["h"] for c in comps)
            vmax = max(c["v"] for c in comps)
            mcux = (W + 8 * hmax - 1) // (8 * hmax)
            mcuy = (H + 8 * vmax - 1) // (8 * vmax)
            for c in comps:
                c["_W"] = (W * c["h"] + hmax - 1) // hmax
                c["_H"] = (H * c["v"] + vmax - 1) // vmax
                c["bw"] = mcux * c["h"]
                c["bh"] = mcuy * c["v"]
                c["blocks"] = [[0] * 64 for _ in range(c["bw"] * c["bh"])]
            frame = (hmax, vmax, mcux, mcuy)
        elif m in (0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            raise JpegError("unsupported JPEG process (lossless/arithmetic)")
        elif m == 0xC4:
            i = 0
            while i < len(seg):
                tc, th = seg[i] >> 4, seg[i] & 15
                counts = list(seg[i + 1:i + 17])
                n = sum(counts)
                hts[(tc, th)] = _Huff(counts, list(seg[i + 17:i + 17 + n]))
                i += 17 + n
        elif m == 0xDD:
            restart = struct.unpack(">H", seg[:2])[0]
        elif m == 0xEE and seg[:5] == b"Adobe":
            adobe = seg[11] if len(seg) > 11 else 0
        elif m == 0xDA:
            if frame is None:
                raise JpegError("SOS before SOF")
            ns = seg[0]
            scomps = []
            for i in range(ns):
                cid, tt = seg[1 + 2 * i], seg[2 + 2 * i]
                c = next((c for c in comps if c["id"] == cid), None)
                if c is None:
                    raise JpegError("bad scan component")
                scomps.append((c, tt >> 4, tt & 15))
            ss, se, ahl = seg[1 + 2 * ns], seg[2 + 2 * ns], seg[3 + 2 * ns]
            ah, al = ahl >> 4, ahl & 15
            p = p + ln
            p = _scan(data, p, frame, comps, scomps, hts, restart, progressive, ss, se, ah, al)
            continue
        p += ln
    if not comps:
        raise JpegError("no frame")
    hmax, vmax, mcux, mcuy = frame
    planes = []
    for c in comps:
        q = qt.get(c["tq"])
        if q is None:
            raise JpegError("missing quant table")
        bw, bh = c["bw"], c["bh"]
        pw = bw * 8
        plane = bytearray(pw * bh * 8)
        for by in range(bh):
            for bx in range(bw):
                px = _idct(c["blocks"][by * bw + bx], q)
                base = by * 8 * pw + bx * 8
                for y in range(8):
                    plane[base + y * pw:base + y * pw + 8] = bytes(px[y * 8:y * 8 + 8])
        planes.append((plane, pw, c["h"], c["v"]))
    nc = len(comps)
    out = bytearray(W * H * nc)
    for ci, (plane, pw, h, v) in enumerate(planes):
        sx, sy = hmax // h, vmax // v
        cw = (W * h + hmax - 1) // hmax        # real component width
        chh = (H * v + vmax - 1) // vmax
        rows = [plane[y * pw:y * pw + cw] for y in range(chh)]
        for y in range(H):
            if sx == 2 and sy in (1, 2) and cw >= 2:
                if sy == 1:
                    cur = rows[min(y, chh - 1)]
                    up = [0] * (2 * cw)
                    for i in range(cw):
                        left = cur[i - 1] if i else cur[0]
                        right = cur[i + 1] if i + 1 < cw else cur[i]
                        up[2 * i] = (3 * cur[i] + left + 1) >> 2
                        up[2 * i + 1] = (3 * cur[i] + right + 2) >> 2
                else:
                    r0 = min(y // 2, chh - 1)
                    r1 = min(max(r0 + (1 if y % 2 else -1), 0), chh - 1)
                    a, b = rows[r0], rows[r1]
                    cs_ = [3 * a[i] + b[i] for i in range(cw)]
                    up = [0] * (2 * cw)
                    for i in range(cw):
                        t = cs_[i]
                        if i == 0:
                            up[0] = (t * 4 + 8) >> 4
                        else:
                            up[2 * i] = (t * 3 + cs_[i - 1] + 8) >> 4
                        if i == cw - 1:
                            up[2 * i + 1] = (t * 4 + 7) >> 4
                        else:
                            up[2 * i + 1] = (t * 3 + cs_[i + 1] + 7) >> 4
                out[y * W * nc + ci:(y + 1) * W * nc:nc] = bytes(up[:W])
            else:
                row = rows[min(y // sy, chh - 1)]
                out[y * W * nc + ci:(y + 1) * W * nc:nc] = bytes(row[min(x // sx, cw - 1)] for x in range(W))
    # colour transform
    transform = adobe if adobe is not None else (1 if nc == 3 else 0)
    if nc == 3 and transform:
        out = _ycc_to_rgb(out, 3)
    elif nc == 4:
        if transform == 2:  # YCCK -> CMYK exactly as libjpeg does: C = 255 - R, etc.; K passes through
            tmp = bytearray(W * H * 3)
            tmp[0::3], tmp[1::3], tmp[2::3] = out[0::4], out[1::4], out[2::4]
            rgb = _ycc_to_rgb(tmp, 3)
            out[0::4], out[1::4], out[2::4] = (bytes(255 - v for v in rgb[i::3]) for i in range(3))
        # NB: Adobe CMYK/YCCK files store inverted ink values; PDF carries that in /Decode [1 0 ...],
        # so the raw samples are returned untouched.
    return W, H, nc, bytes(out)


def _ycc_to_rgb(buf, n):
    out = bytearray(len(buf))
    Y, Cb, Cr = buf[0::n], buf[1::n], buf[2::n]
    cr_r = [int(round(1.402 * (v - 128))) for v in range(256)]
    cb_b = [int(round(1.772 * (v - 128))) for v in range(256)]
    cr_g = [-0.714136 * (v - 128) for v in range(256)]
    cb_g = [-0.344136 * (v - 128) for v in range(256)]
    r, g, b = bytearray(len(Y)), bytearray(len(Y)), bytearray(len(Y))
    for i in range(len(Y)):
        y = Y[i]
        t = y + cr_r[Cr[i]]
        r[i] = 0 if t < 0 else 255 if t > 255 else t
        t = int(y + cb_g[Cb[i]] + cr_g[Cr[i]] + 0.5)
        g[i] = 0 if t < 0 else 255 if t > 255 else t
        t = y + cb_b[Cb[i]]
        b[i] = 0 if t < 0 else 255 if t > 255 else t
    out[0::n], out[1::n], out[2::n] = r, g, b
    if n == 4:
        out[3::4] = buf[3::4]
    return out


def _scan(data, p, frame, comps, scomps, hts, restart, progressive, ss, se, ah, al):
    hmax, vmax, mcux, mcuy = frame
    br = _Bits(data, p)
    for c, _, _ in scomps:
        c["pred"] = 0
    single = len(scomps) == 1
    eobrun = [0]
    if single:
        c = scomps[0][0]
        # non-interleaved: blocks cover ceil(component dims / 8)
        cw = (c["_W"] + 7) // 8
        ch = (c["_H"] + 7) // 8
        total = cw * ch
    else:
        total = mcux * mcuy
    count = 0
    while count < total:
        if restart and count and count % restart == 0:
            # align and consume RSTn
            br.reset()
            q = br.p
            while q + 1 < len(data) and not (data[q] == 0xFF and 0xD0 <= data[q + 1] <= 0xD7):
                if data[q] == 0xFF and data[q + 1] not in (0, 0xFF) and not (0xD0 <= data[q + 1] <= 0xD7):
                    break
                q += 1
            if q + 1 < len(data) and data[q] == 0xFF and 0xD0 <= data[q + 1] <= 0xD7:
                br.p = q + 2
            for c, _, _ in scomps:
                c["pred"] = 0
            eobrun[0] = 0
        if single:
            c, td, ta = scomps[0]
            bx, by = count % cw, count // cw
            _block(br, c, c["blocks"][by * c["bw"] + bx], td, ta, hts, progressive, ss, se, ah, al, eobrun)
        else:
            mx, my = count % mcux, count // mcux
            for c, td, ta in scomps:
                for v in range(c["v"]):
                    for h in range(c["h"]):
                        bx, by = mx * c["h"] + h, my * c["v"] + v
                        _block(br, c, c["blocks"][by * c["bw"] + bx], td, ta, hts, progressive, ss, se, ah, al, eobrun)
        count += 1
        if br.marker is not None and br.n == 0 and br.p >= len(data):
            break
    # position after entropy-coded data: next marker
    q = br.p
    while q + 1 < len(data):
        if data[q] == 0xFF and data[q + 1] not in (0, 0xFF) and not (0xD0 <= data[q + 1] <= 0xD7):
            break
        q += 1
    return q


def _block(br, c, blk, td, ta, hts, progressive, ss, se, ah, al, eobrun):
    if not progressive:
        dc = hts[(0, td)]
        t = br.decode(dc)
        c["pred"] += br.receive_extend(t)
        blk[0] = c["pred"]
        ac = hts[(1, ta)]
        k = 1
        while k < 64:
            rs = br.decode(ac)
            r, s = rs >> 4, rs & 15
            if s == 0:
                if r == 15:
                    k += 16
                    continue
                break
            k += r
            if k > 63:
                break
            blk[ZZ[k]] = br.receive_extend(s)
            k += 1
        return
    if ss == 0:
        if ah == 0:
            t = br.decode(hts[(0, td)])
            c["pred"] += br.receive_extend(t)
            blk[0] = c["pred"] << al
        else:
            if br.bit():
                blk[0] |= 1 << al
        return
    ac = hts[(1, ta)]
    if ah == 0:
        if eobrun[0] > 0:
            eobrun[0] -= 1
            return
        k = ss
        while k <= se:
            rs = br.decode(ac)
            r, s = rs >> 4, rs & 15
            if s == 0:
                if r < 15:
                    eobrun[0] = (1 << r) - 1
                    if r:
                        eobrun[0] += br.bits(r)
                    break
                k += 16
                continue
            k += r
            if k > 63:
                break
            blk[ZZ[k]] = br.receive_extend(s) * (1 << al)
            k += 1
        return
    # AC refinement
    p1 = 1 << al
    m1 = -1 << al
    k = ss
    if eobrun[0] <= 0:
        while k <= se:
            rs = br.decode(ac)
            r, s = rs >> 4, rs & 15
            val = 0
            if s == 0:
                if r < 15:
                    eobrun[0] = (1 << r)
                    if r:
                        eobrun[0] += br.bits(r)
                    break
            else:
                val = p1 if br.bit() else m1
            while k <= se:
                z = ZZ[k]
                if blk[z] != 0:
                    if br.bit():
                        if (blk[z] & p1) == 0:
                            blk[z] += p1 if blk[z] >= 0 else m1
                else:
                    if r == 0:
                        break
                    r -= 1
                k += 1
            if val and k <= se:
                blk[ZZ[k]] = val
            k += 1
    if eobrun[0] > 0:
        while k <= se:
            z = ZZ[k]
            if blk[z] != 0:
                if br.bit():
                    if (blk[z] & p1) == 0:
                        blk[z] += p1 if blk[z] >= 0 else m1
            k += 1
        eobrun[0] -= 1
