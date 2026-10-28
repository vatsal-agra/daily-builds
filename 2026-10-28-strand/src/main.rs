use std::collections::{HashMap, HashSet};
use std::io::Write;
use std::process::ExitCode;
use std::time::Instant;
use strand::align::{align, format_alignment, Mode, Scoring};
use strand::caller::{call_variants, CallParams};
use strand::fm::FmIndex;
use strand::mapper::{evaluate_sam, map_all, read_sam, write_sam, MapParams};
use strand::seq::{self, Reference};
use strand::sim::{simulate, SimParams};
use strand::vcf::{evaluate, read_vcf, write_vcf, Kind};

const HELP: &str = "\
strand — genomics toolkit: FM-index aligner, variant caller, assembler

USAGE: strand <command> [options]

  simulate  -o DIR [--length N --chroms N --seed S --coverage C --read-len L --ploidy 1|2
                    --snp-rate R --indel-rate R --het-frac F --error-scale X --repeat-frac F --gc F]
              write ref.fa, reads.fq, truth.vcf and sample.fa (true haplotypes) to DIR
  index     REF.fa [-o REF.fm] [--sa-rate N]        build and save an FM-index
  search    REF.(fa|fm) PATTERN [--both-strands] [--max-hits N]
              count and locate an exact pattern
  align     SEQ1 SEQ2 [--mode global|local|semi] [--match N --mismatch N --gap-open N --gap-ext N --band N]
              pairwise alignment; SEQ is a literal or a FASTA file
  map       REF.(fa|fm) READS.(fq|fa) -o OUT.sam [--threads N --min-seed N --band N --min-score N --no-sort]
              map reads, write SAM
  call      REF.fa ALN.sam -o OUT.vcf [--ploidy 1|2 --min-mapq N --min-baseq N --min-depth N
                    --min-alt N --min-qual Q --keep-filtered --sample NAME]
              call SNPs and indels
  eval-vcf  REF.fa TRUTH.vcf CALLS.vcf              precision / recall by class
  eval-map  ALN.sam [--tolerance N]                 mapping accuracy from simulated read names
  demo      [--length N --seed S --threads N]       run the whole pipeline on a fresh simulation
  help
";

fn main() -> ExitCode {
    let argv: Vec<String> = std::env::args().skip(1).collect();
    let Some(cmd) = argv.first().cloned() else {
        eprint!("{}", HELP);
        return ExitCode::from(2);
    };
    let rest = &argv[1..];
    let r = match cmd.as_str() {
        "help" | "-h" | "--help" => {
            print!("{}", HELP);
            Ok(())
        }
        "simulate" => cmd_simulate(rest),
        "index" => cmd_index(rest),
        "search" => cmd_search(rest),
        "align" => cmd_align(rest),
        "map" => cmd_map(rest),
        "call" => cmd_call(rest),
        "eval-vcf" => cmd_eval_vcf(rest),
        "eval-map" => cmd_eval_map(rest),
        "demo" => cmd_demo(rest),
        other => Err(CliError::Usage(format!("unknown command {:?} (try `strand help`)", other))),
    };
    match r {
        Ok(()) => ExitCode::SUCCESS,
        Err(CliError::Usage(m)) => {
            eprintln!("strand {}: usage error: {}", cmd, m);
            ExitCode::from(2)
        }
        Err(CliError::Run(m)) => {
            eprintln!("strand {}: error: {}", cmd, m);
            ExitCode::from(1)
        }
    }
}

enum CliError {
    Usage(String),
    Run(String),
}
impl From<String> for CliError {
    fn from(s: String) -> CliError {
        CliError::Run(s)
    }
}
type R = Result<(), CliError>;

struct Args {
    pos: Vec<String>,
    opts: HashMap<String, String>,
    flags: HashSet<String>,
}

fn parse_args(args: &[String], value_opts: &[&str], flag_opts: &[&str]) -> Result<Args, CliError> {
    let mut a = Args { pos: vec![], opts: HashMap::new(), flags: HashSet::new() };
    let mut i = 0;
    while i < args.len() {
        let s = &args[i];
        if let Some(name) = s.strip_prefix("--").or_else(|| if s.len() == 2 && s.starts_with('-') && !s[1..].chars().next().unwrap().is_ascii_digit() { Some(&s[1..]) } else { None }) {
            // allow --key=value
            let (key, inline) = match name.split_once('=') {
                Some((k, v)) => (k, Some(v.to_string())),
                None => (name, None),
            };
            if flag_opts.contains(&key) {
                if inline.is_some() {
                    return Err(CliError::Usage(format!("option --{} does not take a value", key)));
                }
                a.flags.insert(key.to_string());
            } else if value_opts.contains(&key) {
                let v = match inline {
                    Some(v) => v,
                    None => {
                        i += 1;
                        args.get(i).cloned().ok_or_else(|| CliError::Usage(format!("option --{} needs a value", key)))?
                    }
                };
                a.opts.insert(key.to_string(), v);
            } else {
                return Err(CliError::Usage(format!("unknown option {:?}", s)));
            }
        } else {
            a.pos.push(s.clone());
        }
        i += 1;
    }
    Ok(a)
}

impl Args {
    fn num<T: std::str::FromStr>(&self, key: &str, default: T) -> Result<T, CliError> {
        match self.opts.get(key) {
            None => Ok(default),
            Some(v) => v.parse::<T>().map_err(|_| CliError::Usage(format!("--{} expects a number, got {:?}", key, v))),
        }
    }
    fn need(&self, n: usize, what: &str) -> Result<(), CliError> {
        if self.pos.len() != n {
            return Err(CliError::Usage(format!("expected {} (got {} positional arguments)", what, self.pos.len())));
        }
        Ok(())
    }
}

fn create(path: &str) -> Result<std::io::BufWriter<std::fs::File>, CliError> {
    if let Some(parent) = std::path::Path::new(path).parent() {
        if !parent.as_os_str().is_empty() {
            std::fs::create_dir_all(parent).map_err(|e| CliError::Run(format!("{}: {}", parent.display(), e)))?;
        }
    }
    std::fs::File::create(path).map(std::io::BufWriter::new).map_err(|e| CliError::Run(format!("{}: {}", path, e)))
}

fn io<T>(r: std::io::Result<T>, path: &str) -> Result<T, CliError> {
    r.map_err(|e| CliError::Run(format!("{}: {}", path, e)))
}

/// Load an FM-index from a saved index, or build one on the fly from a FASTA file.
fn load_index(path: &str, sa_rate: usize) -> Result<FmIndex, CliError> {
    let head = std::fs::read(path).map_err(|e| CliError::Run(format!("{}: {}", path, e)))?;
    if head.starts_with(b"STRANDFM") {
        return Ok(FmIndex::load(path)?);
    }
    let text = String::from_utf8(head).map_err(|_| CliError::Run(format!("{}: neither a Strand index nor FASTA text", path)))?;
    let recs = seq::parse_fasta(&text).map_err(|e| CliError::Run(format!("{}: {}", path, e)))?;
    let r = Reference::from_fasta(&recs)?;
    if r.ambiguous > 0 {
        eprintln!("warning: {} ambiguous (non-ACGT) reference bases were replaced by pseudo-random bases", r.ambiguous);
    }
    Ok(FmIndex::build(r, sa_rate))
}

fn fasta_map(path: &str) -> Result<Vec<(String, Vec<u8>)>, CliError> {
    Ok(seq::read_fasta(path)?.into_iter().map(|f| (f.name, f.seq)).collect())
}

fn cmd_simulate(a: &[String]) -> R {
    let a = parse_args(a, &["o", "length", "chroms", "seed", "coverage", "read-len", "ploidy", "snp-rate", "indel-rate", "het-frac", "error-scale", "repeat-frac", "gc"], &[])?;
    let d = SimParams::default();
    let out = a.opts.get("o").ok_or_else(|| CliError::Usage("-o DIR is required".into()))?.clone();
    let p = SimParams {
        length: a.num("length", d.length)?,
        chroms: a.num("chroms", d.chroms)?,
        seed: a.num("seed", d.seed)?,
        coverage: a.num("coverage", d.coverage)?,
        read_len: a.num("read-len", d.read_len)?,
        ploidy: a.num("ploidy", d.ploidy)?,
        snp_rate: a.num("snp-rate", d.snp_rate)?,
        indel_rate: a.num("indel-rate", d.indel_rate)?,
        het_frac: a.num("het-frac", d.het_frac)?,
        error_scale: a.num("error-scale", d.error_scale)?,
        repeat_frac: a.num("repeat-frac", d.repeat_frac)?,
        gc: a.num("gc", d.gc)?,
    };
    let t = Instant::now();
    let sim = simulate(&p)?;
    simulate_write(&sim, &out, &p)?;
    eprintln!(
        "simulated {} chromosomes ({} bp), {} truth variants, {} reads in {:.2}s -> {}",
        sim.chroms.len(),
        p.length,
        sim.truth.len(),
        sim.reads.len(),
        t.elapsed().as_secs_f64(),
        out
    );
    Ok(())
}

fn simulate_write(sim: &strand::sim::SimOutput, dir: &str, p: &SimParams) -> R {
    io(std::fs::create_dir_all(dir), dir)?;
    let rp = format!("{}/ref.fa", dir);
    let mut w = create(&rp)?;
    for c in &sim.chroms {
        io(seq::write_fasta(&mut w, &c.name, &c.reference), &rp)?;
    }
    io(w.flush(), &rp)?;
    let sp = format!("{}/sample.fa", dir);
    let mut w = create(&sp)?;
    for c in &sim.chroms {
        for (h, hs) in c.haplotypes.iter().enumerate() {
            io(seq::write_fasta(&mut w, &format!("{}_hap{}", c.name, h + 1), hs), &sp)?;
        }
    }
    io(w.flush(), &sp)?;
    let fp = format!("{}/reads.fq", dir);
    let mut w = create(&fp)?;
    for r in &sim.reads {
        io(seq::write_fastq(&mut w, r), &fp)?;
    }
    io(w.flush(), &fp)?;
    let vp = format!("{}/truth.vcf", dir);
    let mut w = create(&vp)?;
    let contigs: Vec<(String, usize)> = sim.chroms.iter().map(|c| (c.name.clone(), c.reference.len())).collect();
    io(write_vcf(&mut w, &contigs, "SAMPLE", &sim.truth, &format!("strand simulate seed={} ploidy={}", p.seed, p.ploidy)), &vp)?;
    io(w.flush(), &vp)?;
    Ok(())
}

fn cmd_index(a: &[String]) -> R {
    let a = parse_args(a, &["o", "sa-rate"], &[])?;
    a.need(1, "REF.fa")?;
    let rate: usize = a.num("sa-rate", 8)?;
    if rate == 0 || rate > 1024 {
        return Err(CliError::Usage("--sa-rate must be within 1..=1024".into()));
    }
    let out = a.opts.get("o").cloned().unwrap_or_else(|| format!("{}.fm", a.pos[0]));
    let t = Instant::now();
    let fm = load_index(&a.pos[0], rate)?;
    fm.save(&out)?;
    let size = std::fs::metadata(&out).map(|m| m.len()).unwrap_or(0);
    eprintln!(
        "indexed {} contigs, {} bp in {:.2}s -> {} ({:.1} KB, {:.2} bytes/base)",
        fm.reference.names.len(),
        fm.text_len(),
        t.elapsed().as_secs_f64(),
        out,
        size as f64 / 1024.0,
        size as f64 / fm.text_len().max(1) as f64
    );
    Ok(())
}

fn cmd_search(a: &[String]) -> R {
    let a = parse_args(a, &["max-hits", "sa-rate"], &["both-strands"])?;
    a.need(2, "REF PATTERN")?;
    let fm = load_index(&a.pos[0], a.num("sa-rate", 8)?)?;
    let max_hits: usize = a.num("max-hits", 20)?;
    let pat = a.pos[1].to_ascii_uppercase();
    if pat.is_empty() || !pat.bytes().all(|b| matches!(b, b'A' | b'C' | b'G' | b'T')) {
        return Err(CliError::Usage("PATTERN must be a non-empty string over ACGT".into()));
    }
    let strands: Vec<(&str, Vec<u8>)> = if a.flags.contains("both-strands") {
        vec![("+", seq::to_codes(pat.as_bytes()).0), ("-", seq::revcomp_codes(&seq::to_codes(pat.as_bytes()).0))]
    } else {
        vec![("+", seq::to_codes(pat.as_bytes()).0)]
    };
    for (s, codes) in strands {
        let r = fm.search(&codes);
        if r.len() > 2_000_000 {
            println!("strand {}: {} occurrence(s) (too many to enumerate)", s, r.len());
            continue;
        }
        // drop hits that would straddle a boundary between two FASTA records
        let mut locs: Vec<(usize, usize)> = (r.lo..r.hi)
            .filter_map(|row| fm.reference.locate(fm.locate_row(row)))
            .filter(|&(rid, off)| off + codes.len() <= fm.reference.lens[rid])
            .collect();
        locs.sort_unstable();
        println!("strand {}: {} occurrence(s)", s, locs.len());
        for &(rid, off) in locs.iter().take(max_hits) {
            println!("  {}:{}", fm.reference.names[rid], off + 1);
        }
        if locs.len() > max_hits {
            println!("  ... {} more", locs.len() - max_hits);
        }
    }
    Ok(())
}

fn seq_arg(s: &str) -> Result<Vec<u8>, CliError> {
    if std::path::Path::new(s).is_file() {
        let recs = seq::read_fasta(s)?;
        check_nucleotides(&recs[0].seq, s)?;
        return Ok(recs[0].seq.clone());
    }
    check_nucleotides(s.as_bytes(), s)?;
    Ok(s.to_ascii_uppercase().into_bytes())
}

fn check_nucleotides(seq: &[u8], what: &str) -> Result<(), CliError> {
    if seq.is_empty() {
        return Err(CliError::Usage(format!("{:?} is neither an existing file nor a nucleotide string", what)));
    }
    if let Some((i, &b)) = seq.iter().enumerate().find(|(_, b)| !matches!(b.to_ascii_uppercase(), b'A' | b'C' | b'G' | b'T' | b'N')) {
        let hint = if b.to_ascii_uppercase() == b'U' { " (RNA? use T for U)" } else { "" };
        return Err(CliError::Usage(format!("invalid nucleotide {:?} at position {} of the sequence{}; allowed: A C G T N", b as char, i + 1, hint)));
    }
    Ok(())
}

fn cmd_align(a: &[String]) -> R {
    let a = parse_args(a, &["mode", "match", "mismatch", "gap-open", "gap-ext", "band"], &[])?;
    a.need(2, "SEQ1 SEQ2")?;
    let q = seq_arg(&a.pos[0])?;
    let t = seq_arg(&a.pos[1])?;
    let d = Scoring::default();
    let sc = Scoring { matched: a.num("match", d.matched)?, mismatch: a.num("mismatch", d.mismatch)?, gap_open: a.num("gap-open", d.gap_open)?, gap_ext: a.num("gap-ext", d.gap_ext)? };
    let mode = match a.opts.get("mode").map(|s| s.as_str()).unwrap_or("global") {
        "global" => Mode::Global,
        "local" => Mode::Local,
        "semi" | "semiglobal" => Mode::SemiGlobal,
        other => return Err(CliError::Usage(format!("unknown --mode {:?} (global|local|semi)", other))),
    };
    let band = match a.opts.get("band") {
        None => None,
        Some(_) => {
            let w: i64 = a.num("band", 0)?;
            let off = t.len() as i64 - q.len() as i64;
            Some((off.min(0) - w, off.max(0) + w))
        }
    };
    let qc = seq::to_codes_n(&q);
    let tc = seq::to_codes_n(&t);
    let aln = align(&qc, &tc, mode, &sc, band)?.ok_or_else(|| CliError::Run("no alignment exists within the given band".into()))?;
    println!("mode {:?}   score {}   identity {:.1}%   edit distance {}", mode, aln.score, aln.identity() * 100.0, aln.edit_distance());
    println!("query {}..{} of {}   target {}..{} of {}", aln.q_start + 1, aln.q_end, q.len(), aln.t_start + 1, aln.t_end, t.len());
    println!("CIGAR {}   ({})\n", aln.cigar(q.len()), aln.cigar_ext());
    print!("{}", format_alignment(&qc, &tc, &aln, 60));
    Ok(())
}

fn map_params(a: &Args) -> Result<MapParams, CliError> {
    let d = MapParams::default();
    let p = MapParams {
        min_seed: a.num("min-seed", d.min_seed)?,
        band: a.num("band", d.band)?,
        min_score: a.num("min-score", d.min_score)?,
        threads: a.num("threads", d.threads)?,
        ..d
    };
    p.validate().map_err(CliError::Usage)?;
    Ok(p)
}

fn print_map_summary(results: &[strand::mapper::MapResult], secs: f64) {
    let total = results.len();
    let mapped = results.iter().filter(|r| r.hit.is_some()).count();
    let q20 = results.iter().filter(|r| r.hit.as_ref().map_or(false, |h| h.mapq >= 20)).count();
    let pct = |n: usize| if total == 0 { 0.0 } else { 100.0 * n as f64 / total as f64 };
    eprintln!(
        "mapped {}/{} reads ({:.2}%), MAPQ>=20: {} ({:.2}%), {:.0} reads/s",
        mapped,
        total,
        pct(mapped),
        q20,
        pct(q20),
        total as f64 / secs.max(1e-9)
    );
}

fn cmd_map(a: &[String]) -> R {
    let argv = a.join(" ");
    let a = parse_args(a, &["o", "threads", "min-seed", "band", "min-score", "sa-rate"], &["no-sort"])?;
    a.need(2, "REF READS")?;
    let out = a.opts.get("o").ok_or_else(|| CliError::Usage("-o OUT.sam is required".into()))?.clone();
    let p = map_params(&a)?;
    let fm = load_index(&a.pos[0], a.num("sa-rate", 8)?)?;
    let reads = seq::read_reads(&a.pos[1])?;
    if reads.is_empty() {
        return Err(CliError::Run(format!("{}: no reads", a.pos[1])));
    }
    let t = Instant::now();
    let res = map_all(&fm, &p, &reads)?;
    let secs = t.elapsed().as_secs_f64();
    let mut w = create(&out)?;
    io(write_sam(&mut w, &fm, &res, !a.flags.contains("no-sort"), &format!("strand map {}", argv)), &out)?;
    io(w.flush(), &out)?;
    print_map_summary(&res, secs);
    Ok(())
}

fn call_params(a: &Args) -> Result<CallParams, CliError> {
    let d = CallParams::default();
    let p = CallParams {
        min_mapq: a.num("min-mapq", d.min_mapq)?,
        min_baseq: a.num("min-baseq", d.min_baseq)?,
        min_depth: a.num("min-depth", d.min_depth)?,
        min_alt: a.num("min-alt", d.min_alt)?,
        min_qual: a.num("min-qual", d.min_qual)?,
        ploidy: a.num("ploidy", d.ploidy)?,
        keep_filtered: a.flags.contains("keep-filtered"),
    };
    p.validate().map_err(CliError::Usage)?;
    Ok(p)
}

fn cmd_call(a: &[String]) -> R {
    let a = parse_args(a, &["o", "ploidy", "min-mapq", "min-baseq", "min-depth", "min-alt", "min-qual", "sample"], &["keep-filtered"])?;
    a.need(2, "REF.fa ALN.sam")?;
    let out = a.opts.get("o").ok_or_else(|| CliError::Usage("-o OUT.vcf is required".into()))?.clone();
    let p = call_params(&a)?;
    let refs = fasta_map(&a.pos[0])?;
    let sam = read_sam(&a.pos[1])?;
    let t = Instant::now();
    let r = call_variants(&refs, &sam, &p)?;
    let contigs: Vec<(String, usize)> = refs.iter().map(|(n, s)| (n.clone(), s.len())).collect();
    let mut w = create(&out)?;
    let sample = a.opts.get("sample").cloned().unwrap_or_else(|| "SAMPLE".into());
    io(write_vcf(&mut w, &contigs, &sample, &r.variants, "strand call"), &out)?;
    io(w.flush(), &out)?;
    let snps = r.variants.iter().filter(|v| v.kind() == Kind::Snp).count();
    let het = r.variants.iter().filter(|v| v.is_het()).count();
    let total_cov: u64 = r.coverage.iter().flatten().map(|&x| x as u64).sum();
    let total_len: usize = r.coverage.iter().map(|c| c.len()).sum();
    eprintln!(
        "{} reads used of {} ({} unmapped, {} low MAPQ); mean depth {:.1}x; {} variants ({} SNP, {} indel; {} het), {} filtered, {:.2}s -> {}",
        r.stats.reads_used,
        r.stats.reads_total,
        r.stats.reads_unmapped,
        r.stats.reads_low_mapq,
        total_cov as f64 / total_len.max(1) as f64,
        r.variants.len(),
        snps,
        r.variants.len() - snps,
        het,
        r.stats.filtered,
        t.elapsed().as_secs_f64(),
        out
    );
    Ok(())
}

fn print_eval(ev: &strand::vcf::Evaluation) {
    println!("{:<7} {:>6} {:>6} {:>6} {:>10} {:>8} {:>8} {:>8}", "class", "TP", "FP", "FN", "precision", "recall", "F1", "GT-conc");
    for (n, c) in [("SNP", &ev.snp), ("indel", &ev.indel)] {
        let gt = if c.tp == 0 { format!("{:>8}", "-") } else { format!("{:>8.4}", c.gt_concordance()) };
        println!("{:<7} {:>6} {:>6} {:>6} {:>10.4} {:>8.4} {:>8.4} {}", n, c.tp, c.fp, c.fn_, c.precision(), c.recall(), c.f1(), gt);
    }
}

fn cmd_eval_vcf(a: &[String]) -> R {
    let a = parse_args(a, &["show"], &[])?;
    a.need(3, "REF.fa TRUTH.vcf CALLS.vcf")?;
    let refs: HashMap<String, Vec<u8>> = fasta_map(&a.pos[0])?.into_iter().collect();
    let truth = read_vcf(&a.pos[1])?;
    let calls = read_vcf(&a.pos[2])?;
    for v in truth.iter().chain(calls.iter()) {
        match refs.get(&v.chrom) {
            None => return Err(CliError::Run(format!("variant on unknown contig {}", v.chrom))),
            Some(s) => {
                let end = v.pos + v.ref_a.len();
                if end > s.len() {
                    return Err(CliError::Run(format!("variant {}:{} lies outside the contig", v.chrom, v.pos + 1)));
                }
                if s[v.pos..end] != v.ref_a[..] {
                    return Err(CliError::Run(format!("variant {}:{} REF allele does not match the FASTA — wrong reference?", v.chrom, v.pos + 1)));
                }
            }
        }
    }
    let ev = evaluate(&refs, &truth, &calls);
    print_eval(&ev);
    let show: usize = a.num("show", 0)?;
    for (title, list) in [("missed", &ev.missed), ("false calls", &ev.false_calls)] {
        if show > 0 && !list.is_empty() {
            println!("\n{} (first {}):", title, show);
            for v in list.iter().take(show) {
                println!("  {}:{} {} -> {}  {}", v.chrom, v.pos + 1, String::from_utf8_lossy(&v.ref_a), String::from_utf8_lossy(&v.alt), v.gt_string());
            }
        }
    }
    Ok(())
}

fn cmd_eval_map(a: &[String]) -> R {
    let a = parse_args(a, &["tolerance"], &[])?;
    a.need(1, "ALN.sam")?;
    let sam = read_sam(&a.pos[0])?;
    let ev = evaluate_sam(&sam, a.num("tolerance", 20)?);
    if ev.unparseable == ev.total {
        return Err(CliError::Run("read names are not in simulator format chr:pos:strand:id — nothing to evaluate".into()));
    }
    println!("reads {}  mapped {} ({:.2}%)  correct {} ({:.2}% of mapped)", ev.total, ev.mapped, 100.0 * ev.mapped as f64 / ev.total.max(1) as f64, ev.correct, 100.0 * ev.correct as f64 / ev.mapped.max(1) as f64);
    println!("{:>8} {:>9} {:>9} {:>9}", "MAPQ>=", "mapped", "correct", "accuracy");
    for (q, m, c) in ev.by_mapq {
        println!("{:>8} {:>9} {:>9} {:>8.3}%", q, m, c, if m == 0 { 100.0 } else { 100.0 * c as f64 / m as f64 });
    }
    Ok(())
}

fn cmd_demo(a: &[String]) -> R {
    let a = parse_args(a, &["length", "seed", "threads", "o"], &[])?;
    let dir = a.opts.get("o").cloned().unwrap_or_else(|| format!("{}/strand-demo-{}", std::env::temp_dir().display(), std::process::id()));
    let p = SimParams { length: a.num("length", 200_000)?, seed: a.num("seed", 1)?, ..SimParams::default() };
    let threads: usize = a.num("threads", 4)?;
    println!("== 1. simulate: {} bp, {} chromosomes, {}x diploid, {}-bp reads ==", p.length, p.chroms, p.coverage, p.read_len);
    let sim = simulate(&p)?;
    simulate_write(&sim, &dir, &p)?;
    println!("   {} true variants, {} reads -> {}", sim.truth.len(), sim.reads.len(), dir);

    println!("== 2. index ==");
    let t = Instant::now();
    let fm = load_index(&format!("{}/ref.fa", dir), 8)?;
    println!("   FM-index of {} bp in {:.2}s", fm.text_len(), t.elapsed().as_secs_f64());

    println!("== 3. map ==");
    let mp = MapParams { threads, ..MapParams::default() };
    let t = Instant::now();
    let res = map_all(&fm, &mp, &sim.reads)?;
    let secs = t.elapsed().as_secs_f64();
    let sam_path = format!("{}/aln.sam", dir);
    let mut w = create(&sam_path)?;
    io(write_sam(&mut w, &fm, &res, true, "strand demo"), &sam_path)?;
    io(w.flush(), &sam_path)?;
    print_map_summary(&res, secs);
    let sam = read_sam(&sam_path)?;
    let me = evaluate_sam(&sam, 20);
    println!("   accuracy {:.3}% of mapped reads at the true locus (MAPQ>=20: {:.3}%)", 100.0 * me.correct as f64 / me.mapped.max(1) as f64, {
        let r = me.by_mapq.iter().find(|r| r.0 == 20).unwrap();
        100.0 * r.2 as f64 / r.1.max(1) as f64
    });

    println!("== 4. call variants ==");
    let refs = fasta_map(&format!("{}/ref.fa", dir))?;
    let cr = call_variants(&refs, &sam, &CallParams::default())?;
    let contigs: Vec<(String, usize)> = refs.iter().map(|(n, s)| (n.clone(), s.len())).collect();
    let vp = format!("{}/calls.vcf", dir);
    let mut w = create(&vp)?;
    io(write_vcf(&mut w, &contigs, "SAMPLE", &cr.variants, "strand demo"), &vp)?;
    io(w.flush(), &vp)?;
    let refmap: HashMap<String, Vec<u8>> = refs.into_iter().collect();
    let ev = evaluate(&refmap, &sim.truth, &cr.variants);
    print_eval(&ev);
    println!("   outputs in {}", dir);
    Ok(())
}
