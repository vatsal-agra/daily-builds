//! Small shared pieces: error type, PRNG, checked binary (de)serialisation.
use std::fmt;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Error {
    /// Input data failed validation (corrupt file, wrong magic, bad lengths).
    Corrupt(String),
    /// The caller supplied something unusable (non-monotone input, empty pattern, ...).
    Invalid(String),
    Io(String),
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::Corrupt(s) => write!(f, "corrupt data: {s}"),
            Error::Invalid(s) => write!(f, "invalid input: {s}"),
            Error::Io(s) => write!(f, "io error: {s}"),
        }
    }
}
impl std::error::Error for Error {}
impl From<std::io::Error> for Error {
    fn from(e: std::io::Error) -> Self {
        Error::Io(e.to_string())
    }
}
pub type Result<T> = std::result::Result<T, Error>;

/// xorshift64* — deterministic, good enough for tests and benchmarks.
pub struct Rng(pub u64);
impl Rng {
    pub fn new(seed: u64) -> Self {
        Rng(seed.wrapping_mul(0x9E37_79B9_7F4A_7C15) | 1)
    }
    pub fn next_u64(&mut self) -> u64 {
        let mut x = self.0;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        self.0 = x;
        x.wrapping_mul(0x2545_F491_4F6C_DD1D)
    }
    /// Uniform in [0, n). n must be > 0.
    pub fn below(&mut self, n: u64) -> u64 {
        self.next_u64() % n
    }
    pub fn chance(&mut self, p: f64) -> bool {
        (self.next_u64() >> 11) as f64 / (1u64 << 53) as f64 <= p
    }
}

pub fn fnv1a(data: &[u8]) -> u64 {
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    for &b in data {
        h ^= b as u64;
        h = h.wrapping_mul(0x0000_0100_0000_01B3);
    }
    h
}

/// Number of bits needed to represent values 0..=max.
pub fn bits_for(max: u64) -> u32 {
    if max == 0 {
        1
    } else {
        64 - max.leading_zeros()
    }
}

#[derive(Default)]
pub struct Writer {
    pub buf: Vec<u8>,
}
impl Writer {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn u8(&mut self, v: u8) {
        self.buf.push(v);
    }
    pub fn u64(&mut self, v: u64) {
        self.buf.extend_from_slice(&v.to_le_bytes());
    }
    pub fn usize(&mut self, v: usize) {
        self.u64(v as u64);
    }
    pub fn u32s(&mut self, v: &[u32]) {
        self.usize(v.len());
        for &x in v {
            self.buf.extend_from_slice(&x.to_le_bytes());
        }
    }
    pub fn words(&mut self, w: &[u64]) {
        self.usize(w.len());
        for &x in w {
            self.u64(x);
        }
    }
    pub fn bytes(&mut self, b: &[u8]) {
        self.usize(b.len());
        self.buf.extend_from_slice(b);
    }
}

pub struct Reader<'a> {
    data: &'a [u8],
    pos: usize,
}
impl<'a> Reader<'a> {
    pub fn new(data: &'a [u8]) -> Self {
        Reader { data, pos: 0 }
    }
    fn take(&mut self, n: usize) -> Result<&'a [u8]> {
        let end = self
            .pos
            .checked_add(n)
            .filter(|&e| e <= self.data.len())
            .ok_or_else(|| Error::Corrupt("unexpected end of data".into()))?;
        let s = &self.data[self.pos..end];
        self.pos = end;
        Ok(s)
    }
    pub fn u8(&mut self) -> Result<u8> {
        Ok(self.take(1)?[0])
    }
    pub fn u64(&mut self) -> Result<u64> {
        Ok(u64::from_le_bytes(self.take(8)?.try_into().unwrap()))
    }
    pub fn usize(&mut self) -> Result<usize> {
        let v = self.u64()?;
        usize::try_from(v).map_err(|_| Error::Corrupt("length overflow".into()))
    }
    pub fn u32s(&mut self) -> Result<Vec<u32>> {
        let n = self.usize()?;
        if n > self.remaining() / 4 {
            return Err(Error::Corrupt("u32 array longer than file".into()));
        }
        let raw = self.take(n * 4)?;
        Ok(raw.chunks_exact(4).map(|c| u32::from_le_bytes(c.try_into().unwrap())).collect())
    }
    pub fn words(&mut self) -> Result<Vec<u64>> {
        let n = self.usize()?;
        // Bound by remaining bytes so a corrupt length cannot trigger a huge allocation.
        if n > (self.data.len() - self.pos) / 8 {
            return Err(Error::Corrupt("word array longer than file".into()));
        }
        let raw = self.take(n * 8)?;
        Ok(raw.chunks_exact(8).map(|c| u64::from_le_bytes(c.try_into().unwrap())).collect())
    }
    /// Read a word array whose length must equal `expect` (the stored length prefix is checked).
    pub fn words_exact(&mut self, expect: usize) -> Result<Vec<u64>> {
        let w = self.words()?;
        if w.len() != expect {
            return Err(Error::Corrupt(format!("word array has {} words, expected {}", w.len(), expect)));
        }
        Ok(w)
    }
    pub fn bytes(&mut self) -> Result<Vec<u8>> {
        let n = self.usize()?;
        Ok(self.take(n)?.to_vec())
    }
    pub fn remaining(&self) -> usize {
        self.data.len() - self.pos
    }
}

/// Implemented by every persistent structure.
pub trait Ser: Sized {
    fn write(&self, w: &mut Writer);
    fn read(r: &mut Reader) -> Result<Self>;
    /// Bytes this structure occupies when serialised (a faithful space measure).
    fn size_bytes(&self) -> usize {
        let mut w = Writer::new();
        self.write(&mut w);
        w.buf.len()
    }
}

/// Wrap a payload in magic + version + checksum.
pub fn seal(magic: &[u8; 4], payload: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(payload.len() + 20);
    out.extend_from_slice(magic);
    out.extend_from_slice(&1u32.to_le_bytes());
    out.extend_from_slice(&(payload.len() as u64).to_le_bytes());
    out.extend_from_slice(payload);
    out.extend_from_slice(&fnv1a(payload).to_le_bytes());
    out
}

pub fn unseal<'a>(magic: &[u8; 4], data: &'a [u8]) -> Result<&'a [u8]> {
    if data.len() < 24 || &data[0..4] != magic {
        return Err(Error::Corrupt("bad magic (not a Sux file of this kind)".into()));
    }
    if u32::from_le_bytes(data[4..8].try_into().unwrap()) != 1 {
        return Err(Error::Corrupt("unsupported version".into()));
    }
    let len = u64::from_le_bytes(data[8..16].try_into().unwrap()) as usize;
    if data.len() != 16 + len + 8 {
        return Err(Error::Corrupt("length mismatch (truncated or padded file)".into()));
    }
    let payload = &data[16..16 + len];
    let sum = u64::from_le_bytes(data[16 + len..].try_into().unwrap());
    if fnv1a(payload) != sum {
        return Err(Error::Corrupt("checksum mismatch".into()));
    }
    Ok(payload)
}
