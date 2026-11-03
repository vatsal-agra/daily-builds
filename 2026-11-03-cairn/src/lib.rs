//! Cairn: a garbage-collector laboratory.
pub mod bench;
pub mod compact;
pub mod demo;
pub mod fuzz;
pub mod generational;
pub mod heap;
pub mod incremental;
pub mod lang;
pub mod marksweep;
pub mod report;
pub mod semispace;
pub mod verify;
pub mod vm;

use heap::Gc;

/// All collector names, in the order reports list them.
pub const ALL_GCS: [&str; 5] = ["marksweep", "semispace", "generational", "incremental", "compact"];

/// Tunables shared by the CLI, benches and tests.
#[derive(Clone, Debug)]
pub struct GcConfig {
    /// total heap budget in 8-byte words
    pub words: usize,
    /// generational: nursery size in words
    pub nursery: usize,
    /// write barrier on/off (generational remembered set / incremental deletion barrier)
    pub barrier: bool,
    /// incremental: start-cycle occupancy fraction
    pub trigger: f64,
    /// incremental: collector work units per allocated word
    pub pace: usize,
}

impl Default for GcConfig {
    fn default() -> Self {
        GcConfig { words: 1 << 20, nursery: 1 << 15, barrier: true, trigger: 0.5, pace: 6 }
    }
}

pub fn make_gc(name: &str, cfg: &GcConfig) -> Result<Box<dyn Gc>, String> {
    Ok(match name {
        "marksweep" | "ms" => Box::new(marksweep::MarkSweep::new(cfg.words)),
        "semispace" | "semi" => Box::new(semispace::Semispace::new(cfg.words)),
        "generational" | "gen" => {
            let mut g = generational::Generational::new(cfg.words, cfg.nursery);
            g.barrier = cfg.barrier;
            Box::new(g)
        }
        "incremental" | "inc" => {
            let mut g = incremental::Incremental::new(cfg.words);
            g.barrier = cfg.barrier;
            g.trigger = cfg.trigger;
            g.pace = cfg.pace.max(1);
            Box::new(g)
        }
        "compact" => Box::new(compact::Compact::new(cfg.words)),
        other => return Err(format!("unknown collector '{other}' (try: {})", ALL_GCS.join(", "))),
    })
}
