#![allow(dead_code)]
use cairn::vm::*;
use cairn::*;

#[derive(Debug, Clone)]
pub struct Summary {
    pub out: String,
    pub collections: u64,
    pub minor: u64,
    pub promoted: u64,
    pub barrier_hits: u64,
    pub used: usize,
    pub pauses: usize,
    pub max_pause_work: u64,
    pub checks: u64,
    pub alloc_objects: u64,
}

pub fn big<T: Send + 'static>(f: impl FnOnce() -> T + Send + 'static) -> T {
    std::thread::Builder::new().stack_size(512 << 20).spawn(f).unwrap().join().unwrap()
}

pub fn run_with(src: &str, gc: &str, cfg: GcConfig, opts: VmOptions) -> Result<Summary, String> {
    let (src, gc) = (src.to_string(), gc.to_string());
    big(move || {
        let (out, vm) = run_source(&src, &gc, &cfg, opts)?;
        let st = vm.gc.stats();
        Ok(Summary {
            out,
            collections: st.collections,
            minor: st.minor_collections,
            promoted: st.promoted_words,
            barrier_hits: st.barrier_hits,
            used: vm.gc.used_words(),
            pauses: st.pauses.len(),
            max_pause_work: st.max_pause_work(),
            checks: vm.verify_checks,
            alloc_objects: st.alloc_objects,
        })
    })
}

pub fn small_cfg() -> GcConfig {
    GcConfig { words: 6000, nursery: 600, barrier: true, trigger: 0.4, pace: 4 }
}

pub fn run(src: &str, gc: &str) -> Result<Summary, String> {
    run_with(src, gc, small_cfg(), VmOptions::default())
}

pub fn run_verified(src: &str, gc: &str) -> Result<Summary, String> {
    run_with(src, gc, small_cfg(), VmOptions { verify: true, ..Default::default() })
}

pub fn run_torture(src: &str, gc: &str) -> Result<Summary, String> {
    run_with(src, gc, small_cfg(), VmOptions { verify: true, torture: true, ..Default::default() })
}
