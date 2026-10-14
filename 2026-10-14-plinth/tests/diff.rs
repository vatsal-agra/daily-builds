use plinth::fuzz::*;

fn run(seed: u64, ops: usize) {
    let cfg = GenCfg { max_write: 40 * 1024, max_off: 400 * 1024 };
    match diff_fuzz(seed, ops, 4096, &cfg) {
        Ok(r) => eprintln!("seed {seed}: {} ops ({} ok, {} rejected), {} remounts", r.ops, r.ok_ops, r.failed_ops, r.remounts),
        Err(e) => panic!("{e}"),
    }
}

#[test]
fn differential_vs_model_seeds_1_to_8() {
    for s in 1..=8 {
        run(s, 600);
    }
}
