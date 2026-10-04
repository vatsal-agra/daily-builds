//! From-scratch PNG encoder (RGB8, stored/uncompressed deflate) plus base64.

fn crc_table() -> [u32; 256] {
    let mut t = [0u32; 256];
    for n in 0..256u32 {
        let mut c = n;
        for _ in 0..8 {
            c = if c & 1 != 0 { 0xEDB8_8320 ^ (c >> 1) } else { c >> 1 };
        }
        t[n as usize] = c;
    }
    t
}

pub fn crc32(data: &[u8]) -> u32 {
    let t = crc_table();
    let mut c = 0xFFFF_FFFFu32;
    for &b in data {
        c = t[((c ^ b as u32) & 0xFF) as usize] ^ (c >> 8);
    }
    c ^ 0xFFFF_FFFF
}

pub fn adler32(data: &[u8]) -> u32 {
    let (mut a, mut b) = (1u32, 0u32);
    for &d in data {
        a = (a + d as u32) % 65521;
        b = (b + a) % 65521;
    }
    (b << 16) | a
}

fn chunk(out: &mut Vec<u8>, kind: &[u8; 4], data: &[u8]) {
    out.extend_from_slice(&(data.len() as u32).to_be_bytes());
    let mut body = kind.to_vec();
    body.extend_from_slice(data);
    out.extend_from_slice(&body);
    out.extend_from_slice(&crc32(&body).to_be_bytes());
}

// ------------------------------------------------------------------ deflate (compress)

struct BitWriter {
    out: Vec<u8>,
    acc: u32,
    n: u32,
}
impl BitWriter {
    fn bits(&mut self, v: u32, count: u32) {
        // LSB-first
        self.acc |= v << self.n;
        self.n += count;
        while self.n >= 8 {
            self.out.push(self.acc as u8);
            self.acc >>= 8;
            self.n -= 8;
        }
    }
    /// Huffman codes are packed MSB-first.
    fn code(&mut self, code: u32, len: u32) {
        let mut r = 0;
        for i in 0..len {
            r |= ((code >> i) & 1) << (len - 1 - i);
        }
        self.bits(r, len);
    }
    fn flush(&mut self) {
        if self.n > 0 {
            self.out.push(self.acc as u8);
            self.acc = 0;
            self.n = 0;
        }
    }
}

const LEN_BASE: [u16; 29] = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258];
const LEN_EXTRA: [u8; 29] = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0];
const DIST_BASE: [u16; 30] = [1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577];
const DIST_EXTRA: [u8; 30] = [0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13];

fn fixed_lit(w: &mut BitWriter, sym: u32) {
    match sym {
        0..=143 => w.code(0x30 + sym, 8),
        144..=255 => w.code(0x190 + sym - 144, 9),
        256..=279 => w.code(sym - 256, 7),
        _ => w.code(0xC0 + sym - 280, 8),
    }
}

/// LZ77 (hash chains, 32 KiB window) + fixed-Huffman deflate, wrapped as a zlib stream.
pub fn zlib_compress(data: &[u8]) -> Vec<u8> {
    const WIN: usize = 32768;
    const HBITS: usize = 15;
    let mut w = BitWriter { out: vec![0x78, 0x9C], acc: 0, n: 0 };
    w.bits(1, 1); // final block
    w.bits(1, 2); // fixed Huffman
    let mut head = vec![usize::MAX; 1 << HBITS];
    let mut prev = vec![usize::MAX; data.len()];
    let hash = |i: usize| -> usize {
        let v = (data[i] as u32) << 16 | (data[i + 1] as u32) << 8 | data[i + 2] as u32;
        (v.wrapping_mul(2654435761) >> (32 - HBITS as u32)) as usize
    };
    let mut i = 0;
    while i < data.len() {
        let (mut best_len, mut best_dist) = (0usize, 0usize);
        if i + 3 <= data.len() {
            let h = hash(i);
            let mut cand = head[h];
            let mut tries = 48;
            while cand != usize::MAX && i - cand <= WIN && tries > 0 {
                let max = (data.len() - i).min(258);
                let mut l = 0;
                while l < max && data[cand + l] == data[i + l] {
                    l += 1;
                }
                if l > best_len {
                    best_len = l;
                    best_dist = i - cand;
                    if l == max {
                        break;
                    }
                }
                cand = prev[cand];
                tries -= 1;
            }
        }
        let step;
        if best_len >= 3 {
            let li = LEN_BASE.iter().rposition(|&b| b as usize <= best_len).unwrap();
            fixed_lit(&mut w, 257 + li as u32);
            w.bits((best_len - LEN_BASE[li] as usize) as u32, LEN_EXTRA[li] as u32);
            let di = DIST_BASE.iter().rposition(|&b| b as usize <= best_dist).unwrap();
            w.code(di as u32, 5);
            w.bits((best_dist - DIST_BASE[di] as usize) as u32, DIST_EXTRA[di] as u32);
            step = best_len;
        } else {
            fixed_lit(&mut w, data[i] as u32);
            step = 1;
        }
        for k in i..i + step {
            if k + 3 <= data.len() {
                let h = hash(k);
                prev[k] = head[h];
                head[h] = k;
            }
        }
        i += step;
    }
    fixed_lit(&mut w, 256);
    w.flush();
    let mut out = w.out;
    out.extend_from_slice(&adler32(data).to_be_bytes());
    out
}

// ------------------------------------------------------------------ inflate (decompress)

struct BitReader<'a> {
    d: &'a [u8],
    pos: usize,
    bit: u32,
}
impl<'a> BitReader<'a> {
    fn bit(&mut self) -> Result<u32, String> {
        let byte = *self.d.get(self.pos).ok_or("unexpected end of deflate data")?;
        let v = (byte >> self.bit) as u32 & 1;
        self.bit += 1;
        if self.bit == 8 {
            self.bit = 0;
            self.pos += 1;
        }
        Ok(v)
    }
    fn bits(&mut self, n: u32) -> Result<u32, String> {
        let mut v = 0;
        for i in 0..n {
            v |= self.bit()? << i;
        }
        Ok(v)
    }
}

struct Huff {
    count: [u16; 16],
    symbol: Vec<u16>,
}
impl Huff {
    fn new(lengths: &[u8]) -> Huff {
        let mut count = [0u16; 16];
        for &l in lengths {
            count[l as usize] += 1;
        }
        count[0] = 0;
        let mut offs = [0u16; 16];
        for i in 1..16 {
            offs[i] = offs[i - 1] + count[i - 1];
        }
        let mut symbol = vec![0u16; lengths.len()];
        for (s, &l) in lengths.iter().enumerate() {
            if l != 0 {
                symbol[offs[l as usize] as usize] = s as u16;
                offs[l as usize] += 1;
            }
        }
        Huff { count, symbol }
    }
    fn decode(&self, r: &mut BitReader) -> Result<usize, String> {
        let (mut code, mut first, mut index) = (0i32, 0i32, 0i32);
        for len in 1..16 {
            code |= r.bit()? as i32;
            let c = self.count[len] as i32;
            if code - c < first {
                return Ok(self.symbol[(index + (code - first)) as usize] as usize);
            }
            index += c;
            first = (first + c) << 1;
            code <<= 1;
        }
        Err("invalid Huffman code".into())
    }
}

/// Decode a zlib stream (stored, fixed and dynamic blocks).
pub fn zlib_decompress(z: &[u8]) -> Result<Vec<u8>, String> {
    if z.len() < 6 || z[0] & 0x0F != 8 {
        return Err("not a zlib stream".into());
    }
    let mut r = BitReader { d: &z[2..z.len() - 4], pos: 0, bit: 0 };
    let mut out: Vec<u8> = Vec::new();
    loop {
        let last = r.bit()?;
        match r.bits(2)? {
            0 => {
                if r.bit != 0 {
                    r.bit = 0;
                    r.pos += 1;
                }
                if r.pos + 4 > r.d.len() {
                    return Err("truncated stored block".into());
                }
                let len = r.d[r.pos] as usize | (r.d[r.pos + 1] as usize) << 8;
                r.pos += 4;
                if r.pos + len > r.d.len() {
                    return Err("truncated stored block".into());
                }
                out.extend_from_slice(&r.d[r.pos..r.pos + len]);
                r.pos += len;
            }
            t @ (1 | 2) => {
                let (lit, dist) = if t == 1 {
                    let mut l = [0u8; 288];
                    for (i, v) in l.iter_mut().enumerate() {
                        *v = match i {
                            0..=143 => 8,
                            144..=255 => 9,
                            256..=279 => 7,
                            _ => 8,
                        };
                    }
                    (Huff::new(&l), Huff::new(&[5u8; 30]))
                } else {
                    let nlen = r.bits(5)? as usize + 257;
                    let ndist = r.bits(5)? as usize + 1;
                    let ncode = r.bits(4)? as usize + 4;
                    const ORDER: [usize; 19] = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15];
                    let mut cl = [0u8; 19];
                    for &o in ORDER.iter().take(ncode) {
                        cl[o] = r.bits(3)? as u8;
                    }
                    let ch = Huff::new(&cl);
                    let mut lens = vec![0u8; nlen + ndist];
                    let mut i = 0;
                    while i < nlen + ndist {
                        let sym = ch.decode(&mut r)?;
                        if sym < 16 {
                            lens[i] = sym as u8;
                            i += 1;
                        } else {
                            let (val, rep) = match sym {
                                16 => {
                                    if i == 0 {
                                        return Err("bad repeat".into());
                                    }
                                    (lens[i - 1], 3 + r.bits(2)? as usize)
                                }
                                17 => (0, 3 + r.bits(3)? as usize),
                                _ => (0, 11 + r.bits(7)? as usize),
                            };
                            if i + rep > nlen + ndist {
                                return Err("bad code length repeat".into());
                            }
                            for _ in 0..rep {
                                lens[i] = val;
                                i += 1;
                            }
                        }
                    }
                    (Huff::new(&lens[..nlen]), Huff::new(&lens[nlen..]))
                };
                loop {
                    let sym = lit.decode(&mut r)?;
                    if sym < 256 {
                        out.push(sym as u8);
                    } else if sym == 256 {
                        break;
                    } else {
                        let li = sym - 257;
                        if li >= 29 {
                            return Err("bad length symbol".into());
                        }
                        let len = LEN_BASE[li] as usize + r.bits(LEN_EXTRA[li] as u32)? as usize;
                        let di = dist.decode(&mut r)?;
                        if di >= 30 {
                            return Err("bad distance symbol".into());
                        }
                        let d = DIST_BASE[di] as usize + r.bits(DIST_EXTRA[di] as u32)? as usize;
                        if d > out.len() {
                            return Err("distance too far back".into());
                        }
                        for _ in 0..len {
                            out.push(out[out.len() - d]);
                        }
                    }
                }
            }
            _ => return Err("invalid deflate block type".into()),
        }
        if last == 1 {
            break;
        }
    }
    Ok(out)
}

// ------------------------------------------------------------------ PNG

/// Encode an RGB image. `pixels` is row-major `0xRRGGBB`, length w*h. Uses the Sub filter and
/// LZ77 deflate, so flat-colour pixel art compresses by 50-200x.
pub fn encode(w: usize, h: usize, pixels: &[u32]) -> Vec<u8> {
    assert_eq!(pixels.len(), w * h, "pixel buffer size mismatch");
    let mut raw = Vec::with_capacity(h * (1 + 3 * w));
    for y in 0..h {
        raw.push(1); // filter: Sub
        for x in 0..w {
            let p = pixels[y * w + x];
            let q = if x > 0 { pixels[y * w + x - 1] } else { 0 };
            for sh in [16, 8, 0] {
                raw.push(((p >> sh) as u8).wrapping_sub((q >> sh) as u8));
            }
        }
    }
    let z = zlib_compress(&raw);
    let mut out = vec![0x89, b'P', b'N', b'G', 0x0D, 0x0A, 0x1A, 0x0A];
    let mut ihdr = Vec::new();
    ihdr.extend_from_slice(&(w as u32).to_be_bytes());
    ihdr.extend_from_slice(&(h as u32).to_be_bytes());
    ihdr.extend_from_slice(&[8, 2, 0, 0, 0]);
    chunk(&mut out, b"IHDR", &ihdr);
    chunk(&mut out, b"IDAT", &z);
    chunk(&mut out, b"IEND", &[]);
    out
}

/// Decode a non-interlaced 8-bit PNG (gray, RGB, palette, gray+alpha, RGBA) to `0xRRGGBB` pixels.
pub fn decode(b: &[u8]) -> Result<(usize, usize, Vec<u32>), String> {
    if b.len() < 8 || b[..8] != [0x89, b'P', b'N', b'G', 0x0D, 0x0A, 0x1A, 0x0A] {
        return Err("not a PNG file".into());
    }
    let mut pos = 8;
    let (mut w, mut h, mut depth, mut ctype, mut interlace) = (0usize, 0usize, 0u8, 0u8, 0u8);
    let mut plte: Vec<u8> = Vec::new();
    let mut idat: Vec<u8> = Vec::new();
    while pos + 12 <= b.len() {
        let len = u32::from_be_bytes(b[pos..pos + 4].try_into().unwrap()) as usize;
        let kind = &b[pos + 4..pos + 8];
        if pos + 12 + len > b.len() {
            return Err("truncated PNG chunk".into());
        }
        let data = &b[pos + 8..pos + 8 + len];
        let crc = u32::from_be_bytes(b[pos + 8 + len..pos + 12 + len].try_into().unwrap());
        if crc32(&b[pos + 4..pos + 8 + len]) != crc {
            return Err(format!("bad CRC in {} chunk", String::from_utf8_lossy(kind)));
        }
        match kind {
            b"IHDR" => {
                if len < 13 {
                    return Err("short IHDR".into());
                }
                w = u32::from_be_bytes(data[0..4].try_into().unwrap()) as usize;
                h = u32::from_be_bytes(data[4..8].try_into().unwrap()) as usize;
                depth = data[8];
                ctype = data[9];
                interlace = data[12];
            }
            b"PLTE" => plte = data.to_vec(),
            b"IDAT" => idat.extend_from_slice(data),
            b"IEND" => break,
            _ => {}
        }
        pos += 12 + len;
    }
    if w == 0 || h == 0 {
        return Err("PNG has no IHDR".into());
    }
    if w * h > 16_000_000 {
        return Err("PNG too large to use as a sample".into());
    }
    if depth != 8 || interlace != 0 {
        return Err(format!("unsupported PNG (bit depth {}, interlace {}): need 8-bit, non-interlaced", depth, interlace));
    }
    let bpp = match ctype {
        0 => 1,
        2 => 3,
        3 => 1,
        4 => 2,
        6 => 4,
        _ => return Err("unsupported PNG colour type".into()),
    };
    let raw = zlib_decompress(&idat)?;
    let stride = w * bpp;
    if raw.len() < h * (stride + 1) {
        return Err("PNG pixel data is truncated".into());
    }
    let mut img = vec![0u8; h * stride];
    for y in 0..h {
        let f = raw[y * (stride + 1)];
        let line = &raw[y * (stride + 1) + 1..(y + 1) * (stride + 1)];
        for x in 0..stride {
            let a = if x >= bpp { img[y * stride + x - bpp] as i32 } else { 0 };
            let up = if y > 0 { img[(y - 1) * stride + x] as i32 } else { 0 };
            let c = if x >= bpp && y > 0 { img[(y - 1) * stride + x - bpp] as i32 } else { 0 };
            let pred = match f {
                0 => 0,
                1 => a,
                2 => up,
                3 => (a + up) / 2,
                4 => {
                    let p = a + up - c;
                    let (pa, pb, pc) = ((p - a).abs(), (p - up).abs(), (p - c).abs());
                    if pa <= pb && pa <= pc {
                        a
                    } else if pb <= pc {
                        up
                    } else {
                        c
                    }
                }
                _ => return Err("bad PNG filter type".into()),
            };
            img[y * stride + x] = (line[x] as i32 + pred) as u8;
        }
    }
    let mut px = Vec::with_capacity(w * h);
    for i in 0..w * h {
        let p = &img[i * bpp..(i + 1) * bpp];
        px.push(match ctype {
            0 | 4 => (p[0] as u32) * 0x010101,
            2 | 6 => (p[0] as u32) << 16 | (p[1] as u32) << 8 | p[2] as u32,
            _ => {
                let k = p[0] as usize * 3;
                if k + 2 >= plte.len() {
                    return Err("palette index out of range".into());
                }
                (plte[k] as u32) << 16 | (plte[k + 1] as u32) << 8 | plte[k + 2] as u32
            }
        });
    }
    Ok((w, h, px))
}

pub fn base64(data: &[u8]) -> String {
    const A: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut s = String::with_capacity(data.len() * 4 / 3 + 4);
    for c in data.chunks(3) {
        let n = (c[0] as u32) << 16 | (*c.get(1).unwrap_or(&0) as u32) << 8 | *c.get(2).unwrap_or(&0) as u32;
        s.push(A[(n >> 18) as usize & 63] as char);
        s.push(A[(n >> 12) as usize & 63] as char);
        s.push(if c.len() > 1 { A[(n >> 6) as usize & 63] as char } else { '=' });
        s.push(if c.len() > 2 { A[n as usize & 63] as char } else { '=' });
    }
    s
}

/// Nearest-neighbour upscale by an integer factor.
pub fn upscale(w: usize, h: usize, px: &[u32], k: usize) -> (usize, usize, Vec<u32>) {
    let k = k.max(1);
    let (nw, nh) = (w * k, h * k);
    let mut out = vec![0u32; nw * nh];
    for y in 0..nh {
        for x in 0..nw {
            out[y * nw + x] = px[(y / k) * w + x / k];
        }
    }
    (nw, nh, out)
}
