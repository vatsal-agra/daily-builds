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

/// ASCII -> codes, with ambiguity codes mapped to 0 (matches nothing). Used for reads and queries.
pub fn to_codes_n(s: &[u8]) -> Vec<u8> {
    s.iter().map(|&b| encode(b).unwrap_or(0)).collect()
}

/// ASCII -> codes. Non-ACGT bytes become 1 (A); returns the count of such bytes (reference building).
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
    let lines: Vec<&str> = text.lines().map(|l| l.trim_end_matches('\r')).collect();
    let mut out = Vec::new();
    let mut i = 0;
    while i < lines.len() {
        // blank lines are only tolerated between records: a zero-length read has a blank sequence line
        if lines[i].trim().is_empty() {
            i += 1;
            continue;
        }
        let name = lines[i]
            .strip_prefix('@')
            .ok_or_else(|| format!("line {}: expected '@' record header, got {:?}", i + 1, lines[i]))?
            .split_whitespace()
            .next()
            .unwrap_or("")
            .to_string();
        if i + 3 >= lines.len() {
            return Err(format!("line {}: truncated record {}", i + 1, name));
        }
        if !lines[i + 2].starts_with('+') {
            return Err(format!("line {}: expected '+' separator", i + 3));
        }
        let seq = lines[i + 1].to_ascii_uppercase().into_bytes();
        let qual = lines[i + 3].as_bytes().to_vec();
        if seq.len() != qual.len() {
            return Err(format!("line {}: read {} has {} bases but {} quality values", i + 1, name, seq.len(), qual.len()));
        }
        out.push(Fastq { name, seq, qual });
        i += 4;
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

fn hash64(mut x: u64) -> u64 {
    x = x.wrapping_add(0x9E37_79B9_7F4A_7C15);
    x = (x ^ (x >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    x = (x ^ (x >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    x ^ (x >> 31)
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
            if r.names.contains(&f.name) {
                return Err(format!("duplicate reference record name {:?}", f.name));
            }
            if f.seq.is_empty() {
                return Err(format!("reference record {} is empty", f.name));
            }
            // Ambiguous bases (N, IUPAC) become a deterministic pseudo-random base, as BWA does, so a
            // long run of N does not turn into a poly-A trap that attracts low-complexity reads.
            let base = r.codes.len();
            let (mut c, amb) = to_codes(&f.seq);
            if amb > 0 {
                for (i, &b) in f.seq.iter().enumerate() {
                    if encode(b).is_none() {
                        c[i] = 1 + (hash64((base + i) as u64) >> 33) as u8 % 4;
                    }
                }
            }
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
        // a zero-length read keeps its (blank) sequence and quality lines
        let r = parse_fastq("@e\n\n+\n\n@f\nAC\n+\nII\n").unwrap();
        assert_eq!(r.len(), 2);
        assert!(r[0].seq.is_empty());
        assert_eq!(r[1].seq, b"AC");
        assert!(parse_fastq("\n\n@a\nAC\n+\nII\n\n\n").unwrap().len() == 1);
    }

    #[test]
    fn n_runs_do_not_become_poly_a() {
        let f = parse_fasta(&format!(">a\nACGT{}ACGT\n", "N".repeat(200))).unwrap();
        let r = Reference::from_fasta(&f).unwrap();
        assert_eq!(r.ambiguous, 200);
        let a_count = r.codes[4..204].iter().filter(|&&c| c == 1).count();
        assert!(a_count > 20 && a_count < 90, "N run should be mixed bases, got {} A's", a_count);
        assert!(r.codes.iter().all(|&c| (1..=4).contains(&c)));
        // deterministic
        assert_eq!(r.codes, Reference::from_fasta(&f).unwrap().codes);
    }

    #[test]
    fn duplicate_reference_names_rejected() {
        let f = parse_fasta(">a\nACGT\n>a\nGGGG\n").unwrap();
        assert!(Reference::from_fasta(&f).is_err());
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
