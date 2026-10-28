//! DNA encoding, reverse complement and FASTA / FASTQ I/O.
//!
//! Codes: A=1 C=2 G=3 T=4 (0 is reserved for the index sentinel), so the
//! complement of code c is 5-c.

use std::io::Write;

pub fn encode(b: u8) -> Option<u8> {
    match b {
        b'A' | b'a' => Some(1),
        b'C' | b'c' => Some(2),
        b'G' | b'g' => Some(3),
        b'T' | b't' => Some(4),
        _ => None,
    }
}

pub fn decode(c: u8) -> u8 {
    b"NACGT"[c as usize]
}

pub fn comp_ascii(b: u8) -> u8 {
    match b.to_ascii_uppercase() {
        b'A' => b'T',
        b'C' => b'G',
        b'G' => b'C',
        b'T' => b'A',
        b'R' => b'Y',
        b'Y' => b'R',
        b'K' => b'M',
        b'M' => b'K',
        b'B' => b'V',
        b'V' => b'B',
        b'D' => b'H',
        b'H' => b'D',
        x => x,
    }
}

pub fn revcomp_ascii(s: &[u8]) -> Vec<u8> {
    s.iter().rev().map(|&b| comp_ascii(b)).collect()
}

pub fn revcomp_codes(s: &[u8]) -> Vec<u8> {
    s.iter().rev().map(|&c| 5 - c).collect()
}

/// ASCII -> codes. Non-ACGT bytes become 1 (A); returns the count of such bytes.
pub fn to_codes(s: &[u8]) -> (Vec<u8>, usize) {
    let mut amb = 0;
    let v = s
        .iter()
        .map(|&b| match encode(b) {
            Some(c) => c,
            None => {
                amb += 1;
                1
            }
        })
        .collect();
    (v, amb)
}

pub fn from_codes(c: &[u8]) -> Vec<u8> {
    c.iter().map(|&x| decode(x)).collect()
}

#[derive(Clone, Debug, PartialEq)]
pub struct Fasta {
    pub name: String,
    pub seq: Vec<u8>, // upper-case ASCII
}

#[derive(Clone, Debug, PartialEq)]
pub struct Fastq {
    pub name: String,
    pub seq: Vec<u8>,
    pub qual: Vec<u8>, // Phred+33 ASCII
}

pub fn parse_fasta(text: &str) -> Result<Vec<Fasta>, String> {
    let mut out: Vec<Fasta> = Vec::new();
    for (ln, line) in text.lines().enumerate() {
        let line = line.trim_end_matches('\r');
        if line.is_empty() {
            continue;
        }
        if let Some(h) = line.strip_prefix('>') {
            let name = h.split_whitespace().next().unwrap_or("").to_string();
            if name.is_empty() {
                return Err(format!("line {}: FASTA header with no name", ln + 1));
            }
            out.push(Fasta { name, seq: Vec::new() });
        } else {
            let rec = out
                .last_mut()
                .ok_or_else(|| format!("line {}: sequence data before first '>' header", ln + 1))?;
            for b in line.bytes() {
                if b.is_ascii_whitespace() {
                    continue;
                }
                if !b.is_ascii_alphabetic() && b != b'-' && b != b'*' {
                    return Err(format!("line {}: invalid character {:?} in sequence", ln + 1, b as char));
                }
                rec.seq.push(b.to_ascii_uppercase());
            }
        }
    }
    if out.is_empty() {
        return Err("no FASTA records found".into());
    }
    Ok(out)
}

pub fn read_fasta(path: &str) -> Result<Vec<Fasta>, String> {
    let text = std::fs::read_to_string(path).map_err(|e| format!("{}: {}", path, e))?;
    parse_fasta(&text).map_err(|e| format!("{}: {}", path, e))
}

pub fn write_fasta<W: Write>(w: &mut W, name: &str, seq: &[u8]) -> std::io::Result<()> {
    writeln!(w, ">{}", name)?;
    for ch in seq.chunks(70) {
        w.write_all(ch)?;
        w.write_all(b"\n")?;
    }
    Ok(())
}

pub fn parse_fastq(text: &str) -> Result<Vec<Fastq>, String> {
    let mut out = Vec::new();
    let mut lines = text.lines().enumerate().filter(|(_, l)| !l.trim().is_empty());
    while let Some((ln, h)) = lines.next() {
        let h = h.trim_end_matches('\r');
        let name = h
            .strip_prefix('@')
            .ok_or_else(|| format!("line {}: expected '@' record header, got {:?}", ln + 1, h))?
            .split_whitespace()
            .next()
            .unwrap_or("")
            .to_string();
        let (_, seq) = lines.next().ok_or_else(|| format!("line {}: truncated record", ln + 1))?;
        let (_, plus) = lines.next().ok_or_else(|| format!("line {}: truncated record", ln + 1))?;
        let (_, qual) = lines.next().ok_or_else(|| format!("line {}: truncated record (no quality line)", ln + 1))?;
        if !plus.starts_with('+') {
            return Err(format!("line {}: expected '+' separator", ln + 3));
        }
        let seq = seq.trim_end_matches('\r').to_ascii_uppercase().into_bytes();
        let qual = qual.trim_end_matches('\r').as_bytes().to_vec();
        if seq.len() != qual.len() {
            return Err(format!("line {}: read {} has {} bases but {} quality values", ln + 1, name, seq.len(), qual.len()));
        }
        out.push(Fastq { name, seq, qual });
    }
    Ok(out)
}

pub fn read_fastq(path: &str) -> Result<Vec<Fastq>, String> {
    let text = std::fs::read_to_string(path).map_err(|e| format!("{}: {}", path, e))?;
    parse_fastq(&text).map_err(|e| format!("{}: {}", path, e))
}

/// Read reads from FASTQ or FASTA (qualities default to 'I') by sniffing the first byte.
pub fn read_reads(path: &str) -> Result<Vec<Fastq>, String> {
    let text = std::fs::read_to_string(path).map_err(|e| format!("{}: {}", path, e))?;
    let first = text.trim_start().as_bytes().first().copied();
    match first {
        Some(b'@') => parse_fastq(&text).map_err(|e| format!("{}: {}", path, e)),
        Some(b'>') => Ok(parse_fasta(&text)
            .map_err(|e| format!("{}: {}", path, e))?
            .into_iter()
            .map(|f| {
                let q = vec![b'I'; f.seq.len()];
                Fastq { name: f.name, seq: f.seq, qual: q }
            })
            .collect()),
        _ => Err(format!("{}: not FASTQ or FASTA (empty file?)", path)),
    }
}

pub fn write_fastq<W: Write>(w: &mut W, r: &Fastq) -> std::io::Result<()> {
    writeln!(w, "@{}", r.name)?;
    w.write_all(&r.seq)?;
    w.write_all(b"\n+\n")?;
    w.write_all(&r.qual)?;
    w.write_all(b"\n")
}

/// Concatenated multi-record reference in code space.
#[derive(Clone, Debug)]
pub struct Reference {
    pub names: Vec<String>,
    pub offsets: Vec<usize>, // start of each record in `codes`
    pub lens: Vec<usize>,
    pub codes: Vec<u8>,
    pub ambiguous: usize,
}

impl Reference {
    pub fn from_fasta(recs: &[Fasta]) -> Result<Reference, String> {
        if recs.is_empty() {
            return Err("reference has no records".into());
        }
        let mut r = Reference { names: vec![], offsets: vec![], lens: vec![], codes: vec![], ambiguous: 0 };
        for f in recs {
            if f.seq.is_empty() {
                return Err(format!("reference record {} is empty", f.name));
            }
            let (c, amb) = to_codes(&f.seq);
            r.ambiguous += amb;
            r.names.push(f.name.clone());
            r.offsets.push(r.codes.len());
            r.lens.push(c.len());
            r.codes.extend(c);
        }
        Ok(r)
    }

    /// Map a global coordinate to (record index, local offset).
    pub fn locate(&self, g: usize) -> Option<(usize, usize)> {
        if g >= self.codes.len() {
            return None;
        }
        let i = match self.offsets.binary_search(&g) {
            Ok(i) => i,
            Err(i) => i - 1,
        };
        Some((i, g - self.offsets[i]))
    }

    pub fn index_of(&self, name: &str) -> Option<usize> {
        self.names.iter().position(|n| n == name)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn revcomp_roundtrip() {
        let s = b"ACGTTGCAAC";
        assert_eq!(revcomp_ascii(&revcomp_ascii(s)), s.to_vec());
        assert_eq!(revcomp_ascii(b"AACG"), b"CGTT".to_vec());
        let (c, _) = to_codes(s);
        assert_eq!(from_codes(&revcomp_codes(&c)), revcomp_ascii(s));
    }

    #[test]
    fn fasta_parse_and_errors() {
        let r = parse_fasta(">a desc\nACGT\nac\n\n>b\nGG\n").unwrap();
        assert_eq!(r.len(), 2);
        assert_eq!(r[0].name, "a");
        assert_eq!(r[0].seq, b"ACGTAC");
        assert!(parse_fasta("ACGT\n").is_err());
        assert!(parse_fasta("").is_err());
        assert!(parse_fasta(">x\nAC1T\n").is_err());
        assert!(parse_fasta(">\nACGT\n").is_err());
    }

    #[test]
    fn fastq_parse_and_errors() {
        let r = parse_fastq("@r1 x\nACGT\n+\nIIII\n@r2\nGG\n+r2\n!!\n").unwrap();
        assert_eq!(r.len(), 2);
        assert_eq!(r[1].qual, b"!!");
        assert!(parse_fastq("@r\nACGT\n+\nIII\n").is_err());
        assert!(parse_fastq("@r\nACGT\n").is_err());
        assert!(parse_fastq("r\nACGT\n+\nIIII\n").is_err());
    }

    #[test]
    fn reference_locate() {
        let f = parse_fasta(">a\nACGT\n>b\nGGGGG\n").unwrap();
        let r = Reference::from_fasta(&f).unwrap();
        assert_eq!(r.locate(0), Some((0, 0)));
        assert_eq!(r.locate(3), Some((0, 3)));
        assert_eq!(r.locate(4), Some((1, 0)));
        assert_eq!(r.locate(8), Some((1, 4)));
        assert_eq!(r.locate(9), None);
    }
}
