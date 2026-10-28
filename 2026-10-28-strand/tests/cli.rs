//! CLI contract tests: every command, its outputs, and its error behaviour.

use std::path::PathBuf;
use std::process::{Command, Output};

fn bin() -> Command {
    Command::new(env!("CARGO_BIN_EXE_strand"))
}

fn run(args: &[&str]) -> Output {
    bin().args(args).output().unwrap()
}

fn ok(args: &[&str]) -> String {
    let o = run(args);
    assert!(o.status.success(), "{:?} failed: {}", args, String::from_utf8_lossy(&o.stderr));
    format!("{}{}", String::from_utf8_lossy(&o.stdout), String::from_utf8_lossy(&o.stderr))
}

fn fail(args: &[&str], code: i32, needle: &str) {
    let o = run(args);
    assert_eq!(o.status.code(), Some(code), "{:?}: {}", args, String::from_utf8_lossy(&o.stderr));
    let e = String::from_utf8_lossy(&o.stderr);
    assert!(e.contains(needle), "{:?}: stderr {:?} lacks {:?}", args, e, needle);
}

fn tmp(name: &str) -> PathBuf {
    let d = std::env::temp_dir().join(format!("strand_cli_{}_{}", std::process::id(), name));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d
}

fn s(p: &PathBuf, f: &str) -> String {
    p.join(f).to_string_lossy().to_string()
}

#[test]
fn full_diploid_workflow() {
    let d = tmp("wf");
    let dir = d.to_string_lossy().to_string();
    ok(&["simulate", "-o", &dir, "--length", "80000", "--seed", "21", "--coverage", "30"]);
    for f in ["ref.fa", "reads.fq", "truth.vcf", "sample.fa"] {
        assert!(d.join(f).exists(), "{} missing", f);
    }
    // index + search
    let idx = s(&d, "ref.fm");
    let out = ok(&["index", &s(&d, "ref.fa"), "-o", &idx]);
    assert!(out.contains("indexed 2 contigs, 80000 bp"));
    let refseq: String = std::fs::read_to_string(s(&d, "ref.fa")).unwrap().lines().skip(1).take(3).collect();
    let pat = &refseq[40..70];
    let out = ok(&["search", &idx, pat, "--both-strands"]);
    assert!(out.contains("strand +: 1 occurrence(s)") && out.contains("chr1:41"), "{}", out);
    let rc = String::from_utf8(strand::seq::revcomp_ascii(pat.as_bytes())).unwrap();
    assert!(ok(&["search", &idx, &rc, "--both-strands"]).contains("strand -: 1 occurrence(s)"));
    assert!(ok(&["search", &idx, "ACGTACGTACGTACGTACGTACGTAAAAAAAAAGGGGGG"]).contains("0 occurrence(s)"));
    // map using the saved index
    let sam = s(&d, "aln.sam");
    let out = ok(&["map", &idx, &s(&d, "reads.fq"), "-o", &sam, "--threads", "3"]);
    assert!(out.contains("mapped") && out.contains("MAPQ>=20"));
    let ev = ok(&["eval-map", &sam]);
    assert!(ev.contains("correct"), "{}", ev);
    // call + evaluate
    let vcf = s(&d, "calls.vcf");
    ok(&["call", &s(&d, "ref.fa"), &sam, "-o", &vcf]);
    let table = ok(&["eval-vcf", &s(&d, "ref.fa"), &s(&d, "truth.vcf"), &vcf]);
    let snp_line = table.lines().find(|l| l.starts_with("SNP")).unwrap();
    let nums: Vec<f64> = snp_line.split_whitespace().skip(1).map(|x| x.parse().unwrap_or(f64::NAN)).collect();
    assert!(nums[3] > 0.98 && nums[4] > 0.9, "SNP precision/recall: {}", snp_line);
    // report
    let rep = s(&d, "report.html");
    ok(&["report", "--ref", &s(&d, "ref.fa"), "--sam", &sam, "--calls", &vcf, "--truth", &s(&d, "truth.vcf"), "-o", &rep]);
    let html = std::fs::read_to_string(&rep).unwrap();
    assert!(html.contains("Coverage and variants") && html.contains("SNP F1") && html.matches("<svg").count() >= 2);
    std::fs::remove_dir_all(&d).ok();
}

#[test]
fn haploid_assembly_workflow() {
    let d = tmp("asm");
    let dir = d.to_string_lossy().to_string();
    ok(&["simulate", "-o", &dir, "--length", "60000", "--chroms", "1", "--ploidy", "1", "--coverage", "40", "--seed", "5", "--repeat-frac", "0"]);
    let contigs = s(&d, "contigs.fa");
    let out = ok(&["assemble", &s(&d, "reads.fq"), "-o", &contigs, "--spectrum"]);
    assert!(out.contains("k-mer spectrum") && out.contains("contigs"));
    let ev = ok(&["eval-asm", &s(&d, "sample.fa"), &contigs]);
    assert!(ev.contains("misassemblies 0"), "{}", ev);
    let gf: f64 = ev.split("genome fraction ").nth(1).unwrap().split('%').next().unwrap().parse().unwrap();
    assert!(gf > 85.0, "genome fraction {}", gf);
    // the assembler's output is valid FASTA with coverage annotations
    let fa = std::fs::read_to_string(&contigs).unwrap();
    assert!(fa.starts_with(">contig_1 len=") && fa.contains("cov="));
    std::fs::remove_dir_all(&d).ok();
}

#[test]
fn align_modes() {
    let o = ok(&["align", "GATTACAGATTACA", "GATTACAGGATTACA"]);
    assert!(o.contains("CIGAR 7M1D7M"), "{}", o);
    let o = ok(&["align", "TTTTTACGTACGTAC", "GGGACGTACGTACCC", "--mode", "local"]);
    assert!(o.contains("5S10M"), "{}", o);
    let o = ok(&["align", "ACGTACGT", "TTTTACGTACGTTTTT", "--mode", "semi"]);
    assert!(o.contains("score 8") && o.contains("8M"), "{}", o);
    let o = ok(&["align", "ACGTACGTAC", "ACGTACGTAC", "--band", "3"]);
    assert!(o.contains("identity 100.0%"));
}

#[test]
fn mash_matrix_and_tree() {
    let d = tmp("mash");
    let mut rng = strand::rng::Rng::new(9);
    let base: Vec<u8> = (0..60_000).map(|_| b"ACGT"[rng.below(4)]).collect();
    let mutate = |rng: &mut strand::rng::Rng, g: &[u8], r: f64| -> Vec<u8> { g.iter().map(|&b| if rng.chance(r) { b"ACGT"[rng.below(4)] } else { b }).collect() };
    let near = mutate(&mut rng, &base, 0.01);
    let far: Vec<u8> = (0..60_000).map(|_| b"ACGT"[rng.below(4)]).collect();
    for (n, g) in [("base", &base), ("near", &near), ("far", &far)] {
        let mut w = std::fs::File::create(d.join(format!("{}.fa", n))).unwrap();
        strand::seq::write_fasta(&mut w, n, g).unwrap();
    }
    let o = ok(&["mash", &s(&d, "base.fa"), &s(&d, "near.fa"), &s(&d, "far.fa")]);
    assert!(o.contains("base") && o.trim_end().ends_with(';'), "{}", o);
    assert!(o.contains("(base:") && o.contains("near:") || o.contains("(near:"), "{}", o);
    fail(&["mash", &s(&d, "base.fa")], 2, "at least two");
    std::fs::remove_dir_all(&d).ok();
}

#[test]
fn error_contracts() {
    fail(&[], 2, "");
    let o = bin().arg("help").output().unwrap();
    assert!(o.status.success() && String::from_utf8_lossy(&o.stdout).contains("USAGE"));
    fail(&["nonsense"], 2, "unknown command");
    fail(&["simulate"], 2, "-o DIR is required");
    fail(&["simulate", "-o", "x", "--length", "abc"], 2, "expects a number");
    fail(&["simulate", "-o", "x", "--ploidy", "3"], 1, "ploidy");
    fail(&["simulate", "-o", "x", "--bogus", "1"], 2, "unknown option");
    fail(&["index", "/no/such/file.fa"], 1, "/no/such/file.fa");
    fail(&["index"], 2, "REF.fa");
    fail(&["align", "ACGU", "ACGT"], 2, "RNA");
    fail(&["align", "ACGT", "ACGT", "--mode", "weird"], 2, "unknown --mode");
    fail(&["align", "ACGT", "ACGT", "--match", "0"], 1, "match score");
    fail(&["map", "a", "b"], 2, "-o OUT.sam");
    fail(&["call", "a.fa"], 2, "REF.fa ALN.sam");
    fail(&["assemble", "x.fq", "-o", "y.fa", "-k", "30"], 2, "odd");
    fail(&["report", "-o", "x.html"], 2, "--ref is required");
    let d = tmp("err");
    let empty = s(&d, "empty.fa");
    std::fs::write(&empty, "").unwrap();
    fail(&["index", &empty], 1, "no FASTA records");
    let badfq = s(&d, "bad.fq");
    std::fs::write(&badfq, "@r\nACGT\n+\nII\n").unwrap();
    fail(&["assemble", &badfq, "-o", &s(&d, "o.fa")], 1, "quality values");
    let dup = s(&d, "dup.fa");
    std::fs::write(&dup, ">a\nACGTACGTAC\n>a\nGGGGGGGGGG\n").unwrap();
    fail(&["index", &dup], 1, "duplicate");
    // wrong-reference detection in the caller
    let r1 = s(&d, "r1.fa");
    std::fs::write(&r1, format!(">c\n{}\n", "ACGGTCATTAGCAGGCTA".repeat(20))).unwrap();
    let reads = s(&d, "reads.fa");
    std::fs::write(&reads, format!(">q\n{}\n", "ACGGTCATTAGCAGGCTAACGGTCATTAGCAGGCTAACGG")).unwrap();
    let sam = s(&d, "a.sam");
    ok(&["map", &r1, &reads, "-o", &sam]);
    let r2 = s(&d, "r2.fa");
    std::fs::write(&r2, format!(">c\n{}\n", "ACGGTCATTAGCAGGCTA".repeat(5))).unwrap();
    fail(&["call", &r2, &sam, "-o", &s(&d, "o.vcf")], 1, "wrong reference");
    std::fs::remove_dir_all(&d).ok();
}

#[test]
fn demo_runs_end_to_end() {
    let d = tmp("demo");
    let o = ok(&["demo", "--length", "60000", "--o", &d.to_string_lossy()]);
    for step in ["1. simulate", "2. index", "3. map", "4. call variants", "5. assemble", "6. report"] {
        assert!(o.contains(step), "demo output lacks step {}", step);
    }
    assert!(d.join("report.html").exists());
    std::fs::remove_dir_all(&d).ok();
}
