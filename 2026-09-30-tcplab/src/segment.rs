//! TCP segment wire format (RFC 793 / 7323): 20-byte header, options, Internet checksum.

pub const FIN: u8 = 0x01;
pub const SYN: u8 = 0x02;
pub const RST: u8 = 0x04;
pub const PSH: u8 = 0x08;
pub const ACK: u8 = 0x10;

pub const HEADER_LEN: usize = 20;
pub const IP_HEADER_LEN: usize = 20;
const OPT_EOL: u8 = 0;
const OPT_NOP: u8 = 1;
const OPT_MSS: u8 = 2;
const OPT_WSCALE: u8 = 3;

// ---- sequence-number arithmetic (mod 2^32) -------------------------------------------------

pub fn seq_lt(a: u32, b: u32) -> bool {
    (a.wrapping_sub(b) as i32) < 0
}
pub fn seq_leq(a: u32, b: u32) -> bool {
    (a.wrapping_sub(b) as i32) <= 0
}
pub fn seq_gt(a: u32, b: u32) -> bool {
    seq_lt(b, a)
}
pub fn seq_geq(a: u32, b: u32) -> bool {
    seq_leq(b, a)
}

// ---- checksum ------------------------------------------------------------------------------

/// Ones'-complement sum of big-endian 16-bit words (odd trailing byte padded with zero),
/// accumulated into `acc`. Not yet folded/complemented.
fn sum_words(mut acc: u32, data: &[u8]) -> u32 {
    let mut chunks = data.chunks_exact(2);
    for c in &mut chunks {
        acc += u16::from_be_bytes([c[0], c[1]]) as u32;
    }
    if let [last] = chunks.remainder() {
        acc += (*last as u32) << 8;
    }
    acc
}

fn fold(mut acc: u32) -> u16 {
    while acc >> 16 != 0 {
        acc = (acc & 0xFFFF) + (acc >> 16);
    }
    acc as u16
}

/// Checksum over the IPv4 pseudo-header + the given TCP bytes (checksum field must be zero
/// when generating; when verifying, a valid segment yields 0).
pub fn checksum(src: u32, dst: u32, tcp: &[u8]) -> u16 {
    let mut acc = 0u32;
    acc += (src >> 16) + (src & 0xFFFF);
    acc += (dst >> 16) + (dst & 0xFFFF);
    acc += 6; // protocol = TCP
    acc += tcp.len() as u32;
    acc = sum_words(acc, tcp);
    !fold(acc)
}

// ---- segment -------------------------------------------------------------------------------

#[derive(Clone, Debug, PartialEq, Eq, Default)]
pub struct Options {
    pub mss: Option<u16>,
    pub wscale: Option<u8>,
}

#[derive(Clone, Debug, PartialEq, Eq, Default)]
pub struct Segment {
    pub src_addr: u32,
    pub dst_addr: u32,
    pub src_port: u16,
    pub dst_port: u16,
    pub seq: u32,
    pub ack: u32,
    pub flags: u8,
    pub window: u16,
    pub opts: Options,
    pub payload: Vec<u8>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum DecodeError {
    TooShort,
    BadDataOffset,
    BadChecksum,
    BadOption,
}

impl std::fmt::Display for DecodeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let s = match self {
            DecodeError::TooShort => "segment shorter than 20-byte header",
            DecodeError::BadDataOffset => "invalid data offset",
            DecodeError::BadChecksum => "checksum mismatch",
            DecodeError::BadOption => "malformed option",
        };
        f.write_str(s)
    }
}

impl Segment {
    pub fn has(&self, flag: u8) -> bool {
        self.flags & flag != 0
    }

    /// Sequence space consumed: payload + SYN + FIN.
    pub fn seq_len(&self) -> u32 {
        self.payload.len() as u32 + self.has(SYN) as u32 + self.has(FIN) as u32
    }

    pub fn encode(&self) -> Vec<u8> {
        let mut opts = Vec::new();
        if let Some(m) = self.opts.mss {
            opts.extend_from_slice(&[OPT_MSS, 4]);
            opts.extend_from_slice(&m.to_be_bytes());
        }
        if let Some(w) = self.opts.wscale {
            opts.extend_from_slice(&[OPT_NOP, OPT_WSCALE, 3, w]);
        }
        while opts.len() % 4 != 0 {
            opts.push(OPT_EOL);
        }
        let hlen = HEADER_LEN + opts.len();
        let mut b = Vec::with_capacity(hlen + self.payload.len());
        b.extend_from_slice(&self.src_port.to_be_bytes());
        b.extend_from_slice(&self.dst_port.to_be_bytes());
        b.extend_from_slice(&self.seq.to_be_bytes());
        b.extend_from_slice(&self.ack.to_be_bytes());
        b.push(((hlen / 4) as u8) << 4);
        b.push(self.flags);
        b.extend_from_slice(&self.window.to_be_bytes());
        b.extend_from_slice(&[0, 0]); // checksum placeholder
        b.extend_from_slice(&[0, 0]); // urgent pointer (unused)
        b.extend_from_slice(&opts);
        b.extend_from_slice(&self.payload);
        let c = checksum(self.src_addr, self.dst_addr, &b);
        b[16..18].copy_from_slice(&c.to_be_bytes());
        b
    }

    pub fn decode(src_addr: u32, dst_addr: u32, b: &[u8]) -> Result<Segment, DecodeError> {
        if b.len() < HEADER_LEN {
            return Err(DecodeError::TooShort);
        }
        let hlen = ((b[12] >> 4) as usize) * 4;
        if hlen < HEADER_LEN || hlen > b.len() {
            return Err(DecodeError::BadDataOffset);
        }
        if checksum(src_addr, dst_addr, b) != 0 {
            return Err(DecodeError::BadChecksum);
        }
        let opts = parse_options(&b[HEADER_LEN..hlen])?;
        Ok(Segment {
            src_addr,
            dst_addr,
            src_port: u16::from_be_bytes([b[0], b[1]]),
            dst_port: u16::from_be_bytes([b[2], b[3]]),
            seq: u32::from_be_bytes([b[4], b[5], b[6], b[7]]),
            ack: u32::from_be_bytes([b[8], b[9], b[10], b[11]]),
            flags: b[13],
            window: u16::from_be_bytes([b[14], b[15]]),
            opts,
            payload: b[hlen..].to_vec(),
        })
    }

    /// tcpdump-flavoured one-liner.
    pub fn summary(&self) -> String {
        let mut f = String::new();
        for (bit, ch) in [(SYN, 'S'), (FIN, 'F'), (RST, 'R'), (PSH, 'P')] {
            if self.has(bit) {
                f.push(ch);
            }
        }
        if self.has(ACK) {
            f.push('.');
        }
        if f.is_empty() {
            f.push('-');
        }
        let mut s = format!("Flags [{}], seq {}", f, self.seq);
        if self.has(ACK) {
            s += &format!(", ack {}", self.ack);
        }
        s += &format!(", win {}", self.window);
        let mut o = Vec::new();
        if let Some(m) = self.opts.mss {
            o.push(format!("mss {m}"));
        }
        if let Some(w) = self.opts.wscale {
            o.push(format!("wscale {w}"));
        }
        if !o.is_empty() {
            s += &format!(", options [{}]", o.join(","));
        }
        s += &format!(", length {}", self.payload.len());
        s
    }
}

fn parse_options(mut o: &[u8]) -> Result<Options, DecodeError> {
    let mut out = Options::default();
    while let Some(&kind) = o.first() {
        match kind {
            OPT_EOL => break,
            OPT_NOP => o = &o[1..],
            _ => {
                let len = *o.get(1).ok_or(DecodeError::BadOption)? as usize;
                if len < 2 || len > o.len() {
                    return Err(DecodeError::BadOption);
                }
                match kind {
                    OPT_MSS => {
                        if len != 4 {
                            return Err(DecodeError::BadOption);
                        }
                        out.mss = Some(u16::from_be_bytes([o[2], o[3]]));
                    }
                    OPT_WSCALE => {
                        if len != 3 {
                            return Err(DecodeError::BadOption);
                        }
                        out.wscale = Some(o[2].min(14)); // RFC 7323: clamp to 14
                    }
                    _ => {} // unknown option: skip by length
                }
                o = &o[len..];
            }
        }
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample() -> Segment {
        Segment {
            src_addr: 0x0A00_0001,
            dst_addr: 0x0A00_0002,
            src_port: 4000,
            dst_port: 80,
            seq: 0xFFFF_FF00,
            ack: 77,
            flags: ACK | PSH,
            window: 4321,
            opts: Options::default(),
            payload: b"hello, tcp".to_vec(),
        }
    }

    #[test]
    fn roundtrip_plain() {
        let s = sample();
        let b = s.encode();
        assert_eq!(b.len(), 20 + 10);
        assert_eq!(Segment::decode(s.src_addr, s.dst_addr, &b).unwrap(), s);
    }

    #[test]
    fn roundtrip_options_and_odd_payload() {
        let mut s = sample();
        s.flags = SYN;
        s.opts = Options { mss: Some(1460), wscale: Some(7) };
        s.payload = vec![1, 2, 3];
        let b = s.encode();
        let d = Segment::decode(s.src_addr, s.dst_addr, &b).unwrap();
        assert_eq!(d, s);
        assert_eq!(b.len(), 31); // 28-byte header + 3 payload bytes: odd length exercises checksum padding
    }

    #[test]
    fn data_offset_matches_options() {
        let mut s = sample();
        s.opts = Options { mss: Some(1460), wscale: Some(7) };
        let b = s.encode();
        // mss(4) + nop(1) + wscale(3) = 8 bytes of options → header 28 bytes → offset 7
        assert_eq!(b[12] >> 4, 7);
        let d = Segment::decode(s.src_addr, s.dst_addr, &b).unwrap();
        assert_eq!(d.opts, s.opts);
        assert_eq!(d.payload, s.payload);
    }

    #[test]
    fn every_single_bit_flip_is_detected() {
        let s = sample();
        let b = s.encode();
        for i in 0..b.len() * 8 {
            let mut c = b.clone();
            c[i / 8] ^= 1 << (i % 8);
            assert!(
                Segment::decode(s.src_addr, s.dst_addr, &c).is_err(),
                "bit {i} flip went undetected"
            );
        }
    }

    #[test]
    fn wrong_pseudo_header_fails() {
        let s = sample();
        let b = s.encode();
        assert_eq!(Segment::decode(s.src_addr, s.dst_addr + 1, &b), Err(DecodeError::BadChecksum));
    }

    #[test]
    fn rejects_short_and_bad_offset() {
        assert_eq!(Segment::decode(1, 2, &[0; 19]), Err(DecodeError::TooShort));
        let mut s = sample();
        s.payload.clear();
        let mut b = s.encode();
        b[12] = 4 << 4; // header length 16 < 20
        assert_eq!(Segment::decode(s.src_addr, s.dst_addr, &b), Err(DecodeError::BadDataOffset));
        let mut b = s.encode();
        b[12] = 15 << 4; // claims 60-byte header in a 20-byte segment
        assert_eq!(Segment::decode(s.src_addr, s.dst_addr, &b), Err(DecodeError::BadDataOffset));
    }

    /// Build a checksum-valid segment with hand-crafted option bytes.
    fn with_raw_options(opts: &[u8]) -> Result<Segment, DecodeError> {
        let mut s = sample();
        s.payload.clear();
        let mut b = s.encode();
        let mut o = opts.to_vec();
        while o.len() % 4 != 0 {
            o.push(0);
        }
        let hlen = 20 + o.len();
        b.truncate(20);
        b.extend_from_slice(&o);
        b[12] = ((hlen / 4) as u8) << 4;
        b[16] = 0;
        b[17] = 0;
        let c = checksum(s.src_addr, s.dst_addr, &b);
        b[16..18].copy_from_slice(&c.to_be_bytes());
        Segment::decode(s.src_addr, s.dst_addr, &b)
    }

    #[test]
    fn malformed_options_rejected() {
        assert_eq!(with_raw_options(&[1, 2, 4, 5]), Err(DecodeError::BadOption)); // MSS option runs past the header
        assert_eq!(with_raw_options(&[2, 3, 5, 5]), Err(DecodeError::BadOption)); // wrong MSS len
        assert_eq!(with_raw_options(&[9, 1, 0, 0]), Err(DecodeError::BadOption)); // len < 2
        assert_eq!(with_raw_options(&[9]), Err(DecodeError::BadOption)); // no length byte
    }

    #[test]
    fn unknown_options_skipped_and_wscale_clamped() {
        let s = with_raw_options(&[99, 4, 0xAA, 0xBB, 3, 3, 40, 1]).unwrap();
        assert_eq!(s.opts.wscale, Some(14));
        assert_eq!(s.opts.mss, None);
    }

    #[test]
    fn sequence_arithmetic_wraps() {
        assert!(seq_lt(0xFFFF_FFF0, 5));
        assert!(seq_gt(5, 0xFFFF_FFF0));
        assert!(seq_leq(7, 7) && seq_geq(7, 7));
        assert!(!seq_lt(7, 7));
        assert!(seq_lt(0, 0x7FFF_FFFF));
    }

    #[test]
    fn seq_len_counts_syn_fin() {
        let mut s = sample();
        assert_eq!(s.seq_len(), 10);
        s.flags |= SYN | FIN;
        assert_eq!(s.seq_len(), 12);
    }

    #[test]
    fn summary_is_tcpdump_like() {
        let mut s = sample();
        s.flags = SYN | ACK;
        s.opts.mss = Some(1000);
        let t = s.summary();
        assert!(t.contains("Flags [S.]") && t.contains("mss 1000") && t.contains("length 10"), "{t}");
    }
}
