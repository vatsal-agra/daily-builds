//! Minimal VCF 4.2 model: write, parse, left-normalisation and truth-set comparison.

use std::collections::HashMap;
use std::io::Write;

#[derive(Clone, Debug, PartialEq)]
pub struct Variant {
    pub chrom: String,
    pub pos: usize, // 0-based
    pub ref_a: Vec<u8>,
    pub alt: Vec<u8>,
    pub qual: f64,
    pub filter: String,
    /// genotype alleles (0 = ref, 1 = alt); None when unknown
    pub gt: Option<(u8, u8)>,
    pub phased: bool,
    pub depth: u32,
    pub ad: (u32, u32), // (ref, alt) supporting reads
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    Snp,
    Ins,
    Del,
    Other,
}

impl Variant {
    pub fn new(chrom: &str, pos: usize, ref_a: &[u8], alt: &[u8]) -> Variant {
        Variant {
            chrom: chrom.to_string(),
            pos,
            ref_a: ref_a.to_vec(),
            alt: alt.to_vec(),
            qual: 0.0,
            filter: ".".into(),
            gt: None,
            phased: false,
            depth: 0,
            ad: (0, 0),
        }
    }

    pub fn kind(&self) -> Kind {
        match (self.ref_a.len(), self.alt.len()) {
            (1, 1) => Kind::Snp,
            (r, a) if r == 1 && a > 1 => Kind::Ins,
            (r, a) if r > 1 && a == 1 => Kind::Del,
            _ => Kind::Other,
        }
    }

    pub fn key(&self) -> (String, usize, Vec<u8>, Vec<u8>) {
        (self.chrom.clone(), self.pos, self.ref_a.clone(), self.alt.clone())
    }

    pub fn gt_string(&self) -> String {
        match self.gt {
            None => "./.".into(),
            Some((a, b)) => format!("{}{}{}", a, if self.phased { '|' } else { '/' }, b),
        }
    }

    pub fn is_het(&self) -> bool {
        matches!(self.gt, Some((a, b)) if a != b)
    }
}

/// Left-align and minimally represent a variant against the reference `refseq`
/// (ASCII, upper-case) of its chromosome. SNPs are returned unchanged.
pub fn normalize(refseq: &[u8], mut pos: usize, mut r: Vec<u8>, mut a: Vec<u8>) -> (usize, Vec<u8>, Vec<u8>) {
    // right-trim common suffix, extending left whenever an allele empties
    loop {
        if r.is_empty() || a.is_empty() {
            if pos == 0 {
                break;
            }
            pos -= 1;
            r.insert(0, refseq[pos]);
            a.insert(0, refseq[pos]);
        }
        if r.last() == a.last() && (r.len() > 1 || a.len() > 1) {
            r.pop();
            a.pop();
        } else {
            break;
        }
    }
    // left-trim common prefix, keeping one anchor base
    while r.len() > 1 && a.len() > 1 && r[0] == a[0] {
        r.remove(0);
        a.remove(0);
        pos += 1;
    }
    (pos, r, a)
}

pub fn write_vcf<W: Write>(w: &mut W, contigs: &[(String, usize)], sample: &str, vars: &[Variant], source: &str) -> std::io::Result<()> {
    writeln!(w, "##fileformat=VCFv4.2")?;
    writeln!(w, "##source={}", source)?;
    for (n, l) in contigs {
        writeln!(w, "##contig=<ID={},length={}>", n, l)?;
    }
    writeln!(w, "##INFO=<ID=DP,Number=1,Type=Integer,Description=\"Read depth at site\">")?;
    writeln!(w, "##FORMAT=<ID=GT,Number=1,Type=String,Description=\"Genotype\">")?;
    writeln!(w, "##FORMAT=<ID=AD,Number=R,Type=Integer,Description=\"Allele depths\">")?;
    writeln!(w, "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t{}", sample)?;
    for v in vars {
        writeln!(
            w,
            "{}\t{}\t.\t{}\t{}\t{}\t{}\tDP={}\tGT:AD\t{}:{},{}",
            v.chrom,
            v.pos + 1,
            String::from_utf8_lossy(&v.ref_a),
            String::from_utf8_lossy(&v.alt),
            if v.qual == 0.0 && v.depth == 0 { ".".to_string() } else { format!("{:.1}", v.qual) },
            v.filter,
            v.depth,
            v.gt_string(),
            v.ad.0,
            v.ad.1
        )?;
    }
    Ok(())
}

pub fn parse_vcf(text: &str) -> Result<Vec<Variant>, String> {
    let mut out = Vec::new();
    for (ln, line) in text.lines().enumerate() {
        let line = line.trim_end_matches('\r');
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let f: Vec<&str> = line.split('\t').collect();
        if f.len() < 8 {
            return Err(format!("line {}: expected at least 8 tab-separated VCF columns, got {}", ln + 1, f.len()));
        }
        let pos: usize = f[1].parse().map_err(|_| format!("line {}: bad POS {:?}", ln + 1, f[1]))?;
        if pos == 0 {
            return Err(format!("line {}: POS must be >= 1", ln + 1));
        }
        if f[4].contains(',') {
            return Err(format!("line {}: multi-allelic ALT {:?} is not supported", ln + 1, f[4]));
        }
        if f[4].starts_with('<') || f[4] == "." || f[4] == "*" {
            continue; // symbolic / missing alleles are ignored
        }
        let mut v = Variant::new(f[0], pos - 1, f[3].to_ascii_uppercase().as_bytes(), f[4].to_ascii_uppercase().as_bytes());
        v.qual = f[5].parse().unwrap_or(0.0);
        v.filter = f[6].to_string();
        for kv in f[7].split(';') {
            if let Some(d) = kv.strip_prefix("DP=") {
                v.depth = d.parse().unwrap_or(0);
            }
        }
        if f.len() >= 10 {
            let keys: Vec<&str> = f[8].split(':').collect();
            let vals: Vec<&str> = f[9].split(':').collect();
            for (k, val) in keys.iter().zip(vals.iter()) {
                if *k == "GT" {
                    let phased = val.contains('|');
                    let parts: Vec<&str> = val.split(|c| c == '/' || c == '|').collect();
                    let al = |s: &str| s.parse::<u8>().ok();
                    v.gt = match parts.as_slice() {
                        [a] => al(a).map(|a| (a, a)),
                        [a, b] => match (al(a), al(b)) {
                            (Some(a), Some(b)) => Some((a.min(1), b.min(1))),
                            _ => None,
                        },
                        _ => None,
                    };
                    v.phased = phased;
                } else if *k == "AD" {
                    let p: Vec<u32> = val.split(',').filter_map(|x| x.parse().ok()).collect();
                    if p.len() == 2 {
                        v.ad = (p[0], p[1]);
                    }
                }
            }
        }
        out.push(v);
    }
    Ok(out)
}

pub fn read_vcf(path: &str) -> Result<Vec<Variant>, String> {
    let t = std::fs::read_to_string(path).map_err(|e| format!("{}: {}", path, e))?;
    parse_vcf(&t).map_err(|e| format!("{}: {}", path, e))
}

#[derive(Default, Clone, Debug)]
pub struct ClassStats {
    pub tp: usize,
    pub fp: usize,
    pub fn_: usize,
    pub gt_match: usize,
}

impl ClassStats {
    pub fn precision(&self) -> f64 {
        if self.tp + self.fp == 0 {
            1.0
        } else {
            self.tp as f64 / (self.tp + self.fp) as f64
        }
    }
    pub fn recall(&self) -> f64 {
        if self.tp + self.fn_ == 0 {
            1.0
        } else {
            self.tp as f64 / (self.tp + self.fn_) as f64
        }
    }
    pub fn f1(&self) -> f64 {
        let (p, r) = (self.precision(), self.recall());
        if p + r == 0.0 {
            0.0
        } else {
            2.0 * p * r / (p + r)
        }
    }
    pub fn gt_concordance(&self) -> f64 {
        if self.tp == 0 {
            0.0
        } else {
            self.gt_match as f64 / self.tp as f64
        }
    }
}

#[derive(Debug, Clone, Default)]
pub struct Evaluation {
    pub snp: ClassStats,
    pub indel: ClassStats,
    pub matched: Vec<Variant>,
    /// per input call, in input order: None = not PASS (ignored), Some(true) = true positive, Some(false) = false positive
    pub call_class: Vec<Option<bool>>,
    pub missed: Vec<Variant>,
    pub false_calls: Vec<Variant>,
}

/// Compare calls with truth after left-normalising both against `refs` (name -> sequence).
/// Only calls with FILTER of "." or "PASS" are counted.
pub fn evaluate(refs: &HashMap<String, Vec<u8>>, truth: &[Variant], calls: &[Variant]) -> Evaluation {
    let norm = |v: &Variant| -> Variant {
        let mut o = v.clone();
        if let Some(s) = refs.get(&v.chrom) {
            if v.pos < s.len() {
                let (p, r, a) = normalize(s, v.pos, v.ref_a.clone(), v.alt.clone());
                o.pos = p;
                o.ref_a = r;
                o.alt = a;
            }
        }
        o
    };
    let truth: Vec<Variant> = truth.iter().map(norm).collect();
    let passing: Vec<bool> = calls.iter().map(|c| c.filter == "." || c.filter == "PASS").collect();
    let calls_n: Vec<Variant> = calls.iter().filter(|c| c.filter == "." || c.filter == "PASS").map(norm).collect();
    let calls = calls_n;
    let tmap: HashMap<_, _> = truth.iter().map(|v| (v.key(), v)).collect();
    let cmap: HashMap<_, _> = calls.iter().map(|v| (v.key(), v)).collect();
    let mut ev = Evaluation::default();
    {
        let mut it = calls.iter();
        for &p in &passing {
            ev.call_class.push(if p { Some(tmap.contains_key(&it.next().unwrap().key())) } else { None });
        }
    }
    for t in &truth {
        let cs = if t.kind() == Kind::Snp { &mut ev.snp } else { &mut ev.indel };
        match cmap.get(&t.key()) {
            Some(c) => {
                cs.tp += 1;
                ev.matched.push((*c).clone());
                let canon = |g: Option<(u8, u8)>| g.map(|(a, b)| (a.min(b), a.max(b)));
                if canon(c.gt) == canon(t.gt) {
                    cs.gt_match += 1;
                }
            }
            None => {
                cs.fn_ += 1;
                ev.missed.push(t.clone());
            }
        }
    }
    for c in &calls {
        if !tmap.contains_key(&c.key()) {
            let cs = if c.kind() == Kind::Snp { &mut ev.snp } else { &mut ev.indel };
            cs.fp += 1;
            ev.false_calls.push(c.clone());
        }
    }
    ev
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalize_left_aligns_homopolymer_deletion() {
        // ref: G A A A A T ; deleting one A at any position normalises to the same record
        let r = b"GAAAAT";
        let a = normalize(r, 3, b"AA".to_vec(), b"A".to_vec());
        let b = normalize(r, 2, b"AA".to_vec(), b"A".to_vec());
        assert_eq!(a, (0, b"GA".to_vec(), b"G".to_vec()));
        assert_eq!(a, b);
    }

    #[test]
    fn normalize_insertion_in_repeat() {
        // ref: C A C A C A T ; insert "CA" anywhere in the CA repeat
        let r = b"CACACAT";
        let x = normalize(r, 3, b"A".to_vec(), b"ACA".to_vec());
        let y = normalize(r, 1, b"A".to_vec(), b"ACA".to_vec());
        assert_eq!(x, y);
        assert_eq!(x.0, 0);
    }

    #[test]
    fn normalize_leaves_snps_and_unique_indels() {
        assert_eq!(normalize(b"ACGT", 2, b"G".to_vec(), b"T".to_vec()), (2, b"G".to_vec(), b"T".to_vec()));
        assert_eq!(normalize(b"ACGT", 1, b"C".to_vec(), b"CTT".to_vec()), (1, b"C".to_vec(), b"CTT".to_vec()));
        // anchor-less representation at position 0 can't shift further
        assert_eq!(normalize(b"AAAT", 0, b"AA".to_vec(), b"A".to_vec()).0, 0);
    }

    #[test]
    fn vcf_roundtrip() {
        let mut v = Variant::new("chr1", 99, b"A", b"G");
        v.gt = Some((0, 1));
        v.phased = true;
        v.qual = 55.5;
        v.depth = 30;
        v.ad = (14, 16);
        let mut buf = Vec::new();
        write_vcf(&mut buf, &[("chr1".into(), 1000)], "S", &[v.clone()], "test").unwrap();
        let back = parse_vcf(&String::from_utf8(buf).unwrap()).unwrap();
        assert_eq!(back.len(), 1);
        assert_eq!(back[0].pos, 99);
        assert_eq!(back[0].gt, Some((0, 1)));
        assert!(back[0].phased);
        assert_eq!(back[0].ad, (14, 16));
        assert_eq!(back[0].depth, 30);
    }

    #[test]
    fn vcf_errors() {
        assert!(parse_vcf("chr1\t5\t.\tA\n").is_err());
        assert!(parse_vcf("chr1\tx\t.\tA\tG\t.\t.\t.\n").is_err());
        assert!(parse_vcf("chr1\t0\t.\tA\tG\t.\t.\t.\n").is_err());
        assert!(parse_vcf("chr1\t5\t.\tA\tG,T\t.\t.\t.\n").is_err());
        assert_eq!(parse_vcf("chr1\t5\t.\tA\t<DEL>\t.\t.\t.\n").unwrap().len(), 0);
    }

    #[test]
    fn evaluate_counts_and_normalises() {
        let mut refs = HashMap::new();
        refs.insert("c".to_string(), b"GAAAAT".to_vec());
        let mut t1 = Variant::new("c", 3, b"AA", b"A");
        t1.gt = Some((1, 1));
        let t2 = Variant::new("c", 5, b"T", b"C");
        let mut c1 = Variant::new("c", 0, b"GA", b"G");
        c1.gt = Some((1, 1));
        let c2 = Variant::new("c", 0, b"G", b"A"); // false positive
        let ev = evaluate(&refs, &[t1, t2], &[c1, c2]);
        assert_eq!((ev.indel.tp, ev.indel.fp, ev.indel.fn_), (1, 0, 0));
        assert_eq!(ev.indel.gt_match, 1);
        assert_eq!((ev.snp.tp, ev.snp.fp, ev.snp.fn_), (0, 1, 1));
        assert_eq!(ev.missed.len(), 1);
    }
}
