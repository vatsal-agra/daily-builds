//! End-to-end checks: simulate -> index -> map -> call -> score against the truth.

use std::collections::HashMap;
use strand::caller::{call_variants, CallParams};
use strand::fm::FmIndex;
use strand::mapper::{evaluate_sam, map_all, parse_sam, write_sam, MapParams};
use strand::seq::{Fasta, Reference};
use strand::sim::{simulate, SimParams};
use strand::vcf::evaluate;

struct Run {
    ev: strand::vcf::Evaluation,
    map_eval: strand::mapper::MapEval,
}

fn run(p: &SimParams, ploidy: u8) -> Run {
    let sim = simulate(p).unwrap();
    let fasta: Vec<Fasta> = sim.chroms.iter().map(|c| Fasta { name: c.name.clone(), seq: c.reference.clone() }).collect();
    let fm = FmIndex::build(Reference::from_fasta(&fasta).unwrap(), 8);
    let res = map_all(&fm, &MapParams { threads: 4, ..MapParams::default() }, &sim.reads).unwrap();
    let mut buf = Vec::new();
    write_sam(&mut buf, &fm, &res, true, "test").unwrap();
    let sam = parse_sam(&String::from_utf8(buf).unwrap()).unwrap();
    let map_eval = evaluate_sam(&sam, 20);
    let refs: Vec<(String, Vec<u8>)> = sim.chroms.iter().map(|c| (c.name.clone(), c.reference.clone())).collect();
    let calls = call_variants(&refs, &sam, &CallParams { ploidy, ..CallParams::default() }).unwrap();
    let refmap: HashMap<String, Vec<u8>> = refs.into_iter().collect();
    Run { ev: evaluate(&refmap, &sim.truth, &calls.variants), map_eval }
}

#[test]
fn diploid_100kb_pipeline_meets_accuracy_floor() {
    let p = SimParams { length: 100_000, seed: 11, ..SimParams::default() };
    let r = run(&p, 2);
    let m = &r.map_eval;
    assert!(m.mapped as f64 / m.total as f64 > 0.99);
    assert!(m.correct as f64 / m.mapped as f64 > 0.995, "mapping accuracy {}/{}", m.correct, m.mapped);
    let q20 = m.by_mapq.iter().find(|r| r.0 == 20).unwrap();
    assert!(q20.2 as f64 / q20.1 as f64 > 0.9995, "MAPQ>=20 must be essentially error-free");
    let (s, i) = (&r.ev.snp, &r.ev.indel);
    assert!(s.precision() > 0.99 && s.recall() > 0.93, "SNP p={} r={}", s.precision(), s.recall());
    assert!(i.precision() > 0.9 && i.recall() > 0.8, "indel p={} r={}", i.precision(), i.recall());
    // regression: homozygous indels used to be called heterozygous (clipped reads counted as reference)
    assert!(s.gt_concordance() > 0.97, "SNP genotype concordance {}", s.gt_concordance());
    assert!(i.gt_concordance() > 0.93, "indel genotype concordance {}", i.gt_concordance());
}

#[test]
fn haploid_pipeline_is_near_perfect_on_unique_sequence() {
    let p = SimParams { length: 60_000, seed: 3, ploidy: 1, repeat_frac: 0.0, chroms: 1, ..SimParams::default() };
    let r = run(&p, 1);
    assert!(r.ev.snp.recall() > 0.97 && r.ev.snp.precision() > 0.99, "{:?}", r.ev.snp);
    assert!(r.ev.indel.recall() > 0.85, "{:?}", r.ev.indel);
    assert!(r.ev.snp.gt_concordance() > 0.99);
}

#[test]
fn noisy_reads_still_map_and_call_without_false_positives() {
    let p = SimParams { length: 60_000, seed: 8, error_scale: 6.0, ..SimParams::default() };
    let r = run(&p, 2);
    assert!(r.map_eval.correct as f64 / r.map_eval.mapped as f64 > 0.99);
    assert!(r.ev.snp.precision() > 0.98, "{:?}", r.ev.snp);
}

#[test]
fn low_coverage_degrades_recall_not_precision() {
    let p = SimParams { length: 60_000, seed: 5, coverage: 8.0, ..SimParams::default() };
    let r = run(&p, 2);
    assert!(r.ev.snp.precision() > 0.97, "{:?}", r.ev.snp);
    assert!(r.ev.snp.recall() < 0.95, "8x should miss some variants");
}
