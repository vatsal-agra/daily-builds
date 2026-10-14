//! Workload generation, differential fuzzing against the model, and the crash-consistency fuzzer.
use crate::dev::{BlockDev, Event, MemDev};
use crate::error::Result;
use crate::fs::{Fs, MkfsOpts};
use crate::journal::Bug;
use crate::layout::*;
use crate::model::Model;
use crate::rng::Rng;
use crate::vfs::{Dump, Vfs};

#[derive(Clone, Debug)]
pub enum Op {
    Mkdir(String),
    Create(String),
    Write { path: String, off: u64, len: usize, seed: u64 },
    Truncate(String, u64),
    Unlink(String),
    Rmdir(String),
    Rename(String, String),
    Link(String, String),
    Symlink(String, String),
    Chmod(String, u16),
}

impl Op {
    pub fn describe(&self) -> String {
        match self {
            Op::Mkdir(p) => format!("mkdir {p}"),
            Op::Create(p) => format!("create {p}"),
            Op::Write { path, off, len, .. } => format!("write {path} off={off} len={len}"),
            Op::Truncate(p, s) => format!("truncate {p} {s}"),
            Op::Unlink(p) => format!("unlink {p}"),
            Op::Rmdir(p) => format!("rmdir {p}"),
            Op::Rename(a, b) => format!("rename {a} -> {b}"),
            Op::Link(a, b) => format!("link {a} {b}"),
            Op::Symlink(t, p) => format!("symlink {p} -> {t}"),
            Op::Chmod(p, m) => format!("chmod {m:o} {p}"),
        }
    }
}

pub fn apply<V: Vfs + ?Sized>(v: &mut V, op: &Op) -> Result<()> {
    match op {
        Op::Mkdir(p) => v.mkdir(p),
        Op::Create(p) => v.create(p),
        Op::Write { path, off, len, seed } => v.write(path, *off, &Rng::new(*seed).bytes(*len)),
        Op::Truncate(p, s) => v.truncate(p, *s),
        Op::Unlink(p) => v.unlink(p),
        Op::Rmdir(p) => v.rmdir(p),
        Op::Rename(a, b) => v.rename(a, b),
        Op::Link(a, b) => v.link(a, b),
        Op::Symlink(t, p) => v.symlink(t, p),
        Op::Chmod(p, m) => v.chmod(p, *m),
    }
}

#[derive(Clone, Debug)]
pub struct GenCfg {
    /// Largest single write, in bytes.
    pub max_write: usize,
    /// Largest offset a sparse write may start at.
    pub max_off: u64,
}

const NAMES: [&str; 8] = ["a", "b", "c", "d", "e", "f", "g", "h"];

fn join(dir: &str, n: &str) -> String {
    if dir == "/" {
        format!("/{n}")
    } else {
        format!("{dir}/{n}")
    }
}

pub fn gen_op(rng: &mut Rng, model: &Model, cfg: &GenCfg) -> Op {
    let list = model.listing();
    let dirs: Vec<&String> = list.iter().filter(|e| e.1 == Kind::Dir).map(|e| &e.0).collect();
    let files: Vec<&(String, Kind, u64)> = list.iter().filter(|e| e.1 == Kind::File || (e.1 == Kind::Symlink && rng.chance(40))).collect();
    let non_root: Vec<&(String, Kind, u64)> = list.iter().filter(|e| e.0 != "/").collect();
    let fresh = |rng: &mut Rng| -> String {
        let d = if rng.chance(90) { (*rng.pick(&dirs)).clone() } else { rng.pick(&list).0.clone() };
        join(&d, rng.pick(&NAMES))
    };
    let existing_or_fresh = |rng: &mut Rng, pool: &[&(String, Kind, u64)]| -> String {
        if !pool.is_empty() && rng.chance(75) {
            rng.pick(pool).0.clone()
        } else {
            fresh(rng)
        }
    };
    let roll = rng.below(100);
    match roll {
        0..=9 => Op::Mkdir(fresh(rng)),
        10..=22 => Op::Create(fresh(rng)),
        23..=52 => {
            let target = existing_or_fresh(rng, &files);
            let size = list.iter().find(|e| e.0 == target).map(|e| e.2).unwrap_or(0);
            let off = match rng.below(10) {
                0..=3 => 0,
                4..=6 => size,
                7..=8 => rng.below(size + 2 * BS as u64 + 1),
                _ => rng.below(cfg.max_off + 1),
            };
            let len = match rng.below(20) {
                0 => 0,
                1..=9 => rng.range(1, 60) as usize,
                10..=12 => *rng.pick(&[BS - 1, BS, BS + 1, 2 * BS, 3 * BS + 17]),
                13..=17 => rng.range(60, 3 * BS as u64) as usize,
                _ => rng.range(1, cfg.max_write as u64) as usize,
            };
            Op::Write { path: target, off, len: len.min(cfg.max_write), seed: rng.next() }
        }
        53..=59 => {
            let t = existing_or_fresh(rng, &files);
            let size = match rng.below(4) {
                0 => 0,
                1 => rng.below(BS as u64 * 2),
                2 => rng.below(cfg.max_off + 1),
                _ => list.iter().find(|e| e.0 == t).map(|e| e.2 / 2).unwrap_or(0),
            };
            Op::Truncate(t, size)
        }
        60..=69 => Op::Unlink(existing_or_fresh(rng, &non_root)),
        70..=73 => Op::Rmdir(existing_or_fresh(rng, &non_root)),
        74..=83 => {
            let a = existing_or_fresh(rng, &non_root);
            let b = if rng.chance(50) { existing_or_fresh(rng, &non_root) } else { fresh(rng) };
            Op::Rename(a, b)
        }
        84..=89 => {
            let a = existing_or_fresh(rng, &non_root);
            Op::Link(a, fresh(rng))
        }
        90..=96 => {
            let target = match rng.below(5) {
                0 => "/nowhere".to_string(),
                1 => "..".to_string(),
                2 => "a".to_string(),
                3 => rng.pick(&list).0.clone(),
                _ => format!("../{}", rng.pick(&NAMES)),
            };
            Op::Symlink(target, fresh(rng))
        }
        _ => Op::Chmod(existing_or_fresh(rng, &non_root), rng.below(0o10000) as u16),
    }
}

fn dump_diff(a: &Dump, b: &Dump) -> String {
    for (k, v) in a {
        match b.get(k) {
            None => return format!("'{k}' present in left, missing in right"),
            Some(w) if w != v => {
                return format!(
                    "'{k}' differs: left kind={:?} perm={:o} nlink={} size={} group={} / right kind={:?} perm={:o} nlink={} size={} group={} (data equal: {})",
                    v.kind, v.perm, v.nlink, v.size, v.group, w.kind, w.perm, w.nlink, w.size, w.group, v.data == w.data
                )
            }
            _ => {}
        }
    }
    for k in b.keys() {
        if !a.contains_key(k) {
            return format!("'{k}' missing in left, present in right");
        }
    }
    "identical".into()
}

pub struct DiffReport {
    pub ops: usize,
    pub ok_ops: usize,
    pub failed_ops: usize,
    pub remounts: usize,
}

/// Run `nops` random operations against both the real filesystem and the model; every result and
/// (periodically) the complete tree must agree. Also remounts and runs fsck along the way.
pub fn diff_fuzz(seed: u64, nops: usize, nblocks: u32, cfg: &GenCfg) -> std::result::Result<DiffReport, String> {
    let dev = MemDev::new(nblocks);
    let mut fs = Fs::mkfs(dev, &MkfsOpts { ninodes: 512, journal_len: 128 }).map_err(|e| e.to_string())?;
    let mut model = Model::new();
    let mut rng = Rng::new(seed);
    let mut rep = DiffReport { ops: 0, ok_ops: 0, failed_ops: 0, remounts: 0 };
    for i in 0..nops {
        let op = gen_op(&mut rng, &model, cfg);
        let r_fs = apply(&mut fs, &op);
        let r_m = apply(&mut model, &op);
        rep.ops += 1;
        match (&r_fs, &r_m) {
            (Ok(()), Ok(())) => rep.ok_ops += 1,
            (Err(a), Err(b)) if a.kind() == b.kind() => rep.failed_ops += 1,
            _ => {
                return Err(format!(
                    "seed {seed} op #{i} [{}]: fs -> {:?}, model -> {:?}",
                    op.describe(),
                    r_fs.map_err(|e| format!("{} ({e})", e.kind())),
                    r_m.map_err(|e| format!("{} ({e})", e.kind()))
                ))
            }
        }
        if i % 7 == 0 || i + 1 == nops {
            let (a, b) = (fs.dump().map_err(|e| e.to_string())?, model.dump().unwrap());
            if a != b {
                return Err(format!("seed {seed} after op #{i} [{}]: trees diverge: {}", op.describe(), dump_diff(&a, &b)));
            }
        }
        if i % 60 == 59 {
            let rep_fsck = crate::fsck::analyze(&mut fs.dev);
            if !rep_fsck.issues.is_empty() {
                return Err(format!("seed {seed} after op #{i}: fsck: {}", rep_fsck.issues[0]));
            }
            let dev = fs.into_dev();
            fs = Fs::mount(dev).map_err(|e| format!("remount failed: {e}"))?;
            rep.remounts += 1;
            let (a, b) = (fs.dump().map_err(|e| e.to_string())?, model.dump().unwrap());
            if a != b {
                return Err(format!("seed {seed} after remount at op #{i}: trees diverge: {}", dump_diff(&a, &b)));
            }
        }
    }
    let r = crate::fsck::analyze(&mut fs.dev);
    if !r.issues.is_empty() {
        return Err(format!("seed {seed}: final fsck: {} (+{} more)", r.issues[0], r.issues.len() - 1));
    }
    Ok(rep)
}

// ------------------------------------------------------------------------------------------
// Crash-consistency fuzzer
// ------------------------------------------------------------------------------------------

#[derive(Clone, Debug)]
pub struct CrashOpts {
    pub seed: u64,
    pub ops: usize,
    /// Random persistence subsets tried at every crash point (in addition to none/all/torn).
    pub variants: usize,
    pub nblocks: u32,
    pub journal_len: u32,
    pub bug: Bug,
    /// Also crash *during recovery* (double fault) for every 7th of the replayed states.
    pub nested: bool,
    /// Stop after this many failures (0 = collect all).
    pub max_failures: usize,
}

impl Default for CrashOpts {
    fn default() -> Self {
        CrashOpts { seed: 1, ops: 40, variants: 4, nblocks: 1024, journal_len: 64, bug: Bug::None, nested: true, max_failures: 5 }
    }
}

#[derive(Debug, Clone)]
pub struct CrashFailure {
    pub event: usize,
    pub ops_done: usize,
    pub variant: String,
    pub what: String,
    /// The crashed disk image (kept so a failure can be reproduced with `plinth fsck`).
    pub image: Vec<u8>,
}

#[derive(Debug, Default)]
pub struct CrashReport {
    pub events: usize,
    pub writes: usize,
    pub flushes: usize,
    pub states_checked: usize,
    pub replays: usize,
    pub nested_states: usize,
    pub torn_states: usize,
    pub failures: Vec<CrashFailure>,
    pub workload_errors: Vec<String>,
    /// Compact event trace (`W<blk>`, `F` = flush, `M` = op boundary) for diagnosing failures.
    pub trace: Vec<String>,
}

/// Enumerate every disk state reachable by crashing before event `idx` (for every idx): the durable
/// image plus none / all / random subsets (shuffled order) of the writes still in flight, plus one
/// variant where a random in-flight write is torn at sector granularity.
fn explore<F: FnMut(usize, &str, Vec<u8>) -> bool>(
    base: &[u8],
    events: &[Event],
    variants: usize,
    rng: &mut Rng,
    mut visit: F,
) {
    let mut durable = base.to_vec();
    let mut pending: Vec<(u32, &Block)> = Vec::new();
    for idx in 0..=events.len() {
        let n = pending.len();
        let mut plans: Vec<(String, Vec<usize>, Option<usize>)> = vec![("none-persisted".into(), vec![], None)];
        if n > 0 {
            plans.push(("all-persisted".into(), (0..n).collect(), None));
            for v in 0..variants {
                let mut sel: Vec<usize> = (0..n).filter(|_| rng.chance(50)).collect();
                rng.shuffle(&mut sel);
                plans.push((format!("random-subset#{v}"), sel, None));
            }
            let mut sel: Vec<usize> = (0..n).filter(|_| rng.chance(60)).collect();
            if sel.is_empty() {
                sel.push(rng.below(n as u64) as usize);
            }
            rng.shuffle(&mut sel);
            let torn = rng.below(sel.len() as u64) as usize;
            plans.push(("torn-write".into(), sel, Some(torn)));
        }
        for (name, sel, torn) in plans {
            let mut img = durable.clone();
            for (k, &pi) in sel.iter().enumerate() {
                let (b, data) = pending[pi];
                let o = b as usize * BS;
                if torn == Some(k) {
                    img[o..o + 512].copy_from_slice(&data[..512]);
                } else {
                    img[o..o + BS].copy_from_slice(&data[..]);
                }
            }
            if !visit(idx, &name, img) {
                return;
            }
        }
        if idx == events.len() {
            break;
        }
        match &events[idx] {
            Event::Write(b, d) => pending.push((*b, d)),
            Event::Flush => {
                for (b, d) in pending.drain(..) {
                    let o = b as usize * BS;
                    durable[o..o + BS].copy_from_slice(&d[..]);
                }
            }
            Event::Mark => {}
        }
    }
}

struct Verdict {
    replayed: bool,
    /// crash states explored inside recovery itself
    nested: usize,
}

/// Mount a crashed image and verify it. With `nested`, additionally crash *during recovery* at every
/// point and verify the double-crashed image recovers to an allowed state too.
fn check_crash_image(
    image: Vec<u8>,
    bug: Bug,
    allowed: &[&Dump],
    probe: Option<u64>,
    nested: Option<&mut Rng>,
) -> std::result::Result<Verdict, String> {
    let mut rec = MemDev::from_bytes(image.clone());
    rec.start_recording();
    let mut fs = Fs::mount_with(rec, bug).map_err(|e| format!("mount failed: {e}"))?;
    let recovery_events = fs.dev.log.take().unwrap_or_default();
    let replayed = fs.replayed.is_some();
    let rep = crate::fsck::analyze(&mut fs.dev);
    if let Some(i) = rep.issues.first() {
        return Err(format!("fsck after recovery: {} (+{} more)", i, rep.issues.len() - 1));
    }
    let got = fs.dump().map_err(|e| format!("walking recovered tree: {e}"))?;
    if !allowed.iter().any(|a| **a == got) {
        let d = dump_diff(&got, allowed[0]);
        let d2 = allowed.get(1).map(|a| dump_diff(&got, a)).unwrap_or_default();
        return Err(format!(
            "recovered state matches neither allowed state; vs before: {d}{}",
            if d2.is_empty() { String::new() } else { format!("; vs after: {d2}") }
        ));
    }
    if let Some(sd) = probe {
        // the recovered filesystem must remain fully usable
        let name = format!("/probe{sd}");
        fs.create(&name).map_err(|e| format!("post-recovery create failed: {e}"))?;
        fs.write(&name, 0, &Rng::new(sd).bytes(3000)).map_err(|e| format!("post-recovery write failed: {e}"))?;
        let rep = crate::fsck::analyze(&mut fs.dev);
        if let Some(i) = rep.issues.first() {
            return Err(format!("fsck after post-recovery writes: {i}"));
        }
    }
    let mut nested_n = 0;
    if let Some(rng) = nested {
        if replayed {
            let mut err: Option<String> = None;
            explore(&image, &recovery_events, 2, rng, |idx, name, img2| {
                nested_n += 1;
                match check_crash_image(img2, bug, allowed, None, None) {
                    Ok(_) => true,
                    Err(e) => {
                        err = Some(format!("crash during recovery (before recovery event {idx}, {name}): {e}"));
                        false
                    }
                }
            });
            if let Some(e) = err {
                return Err(e);
            }
        }
    }
    Ok(Verdict { replayed, nested: nested_n })
}

pub fn crash_fuzz(o: &CrashOpts) -> CrashReport {
    let mut rep = CrashReport::default();
    let dev = MemDev::new(o.nblocks);
    let mut fs = match Fs::mkfs(dev, &MkfsOpts { ninodes: 256, journal_len: o.journal_len }) {
        Ok(f) => f,
        Err(e) => {
            rep.workload_errors.push(format!("mkfs: {e}"));
            return rep;
        }
    };
    fs.bug = o.bug;
    let base = fs.dev.data.clone();
    fs.dev.start_recording();
    let mut model = Model::new();
    let mut states: Vec<Dump> = vec![model.dump().unwrap()];
    let mut rng = Rng::new(o.seed);
    let cfg = GenCfg { max_write: 30 * BS, max_off: 40 * BS as u64 };
    for i in 0..o.ops {
        let op = gen_op(&mut rng, &model, &cfg);
        let r_fs = apply(&mut fs, &op);
        let r_m = apply(&mut model, &op);
        match (&r_fs, &r_m) {
            (Ok(()), Ok(())) => {}
            (Err(a), Err(b)) if a.kind() == b.kind() => {}
            _ => {
                rep.workload_errors.push(format!("op #{i} [{}]: fs {:?} vs model {:?}", op.describe(), r_fs.err().map(|e| e.kind()), r_m.err().map(|e| e.kind())));
                return rep;
            }
        }
        fs.dev.mark();
        states.push(model.dump().unwrap());
    }
    let events = fs.dev.log.take().unwrap();
    rep.events = events.len();
    rep.writes = events.iter().filter(|e| matches!(e, Event::Write(..))).count();
    rep.flushes = events.iter().filter(|e| matches!(e, Event::Flush)).count();
    rep.trace = events
        .iter()
        .map(|e| match e {
            Event::Write(b, _) => format!("W{b}"),
            Event::Flush => "F".into(),
            Event::Mark => "M".into(),
        })
        .collect();
    // ops completed before each event
    let mut done_at = Vec::with_capacity(events.len() + 1);
    let mut done = 0usize;
    for e in &events {
        done_at.push(done);
        if matches!(e, Event::Mark) {
            done += 1;
        }
    }
    done_at.push(done);

    let mut crng = Rng::new(o.seed ^ 0xC4A5);
    let mut nrng = Rng::new(o.seed ^ 0x9E57);
    let mut count = 0usize;
    explore(&base, &events, o.variants, &mut crng, |idx, name, img| {
        let done = done_at[idx];
        let allowed: Vec<&Dump> = if done + 1 < states.len() { vec![&states[done], &states[done + 1]] } else { vec![&states[done]] };
        count += 1;
        rep.states_checked += 1;
        if name == "torn-write" {
            rep.torn_states += 1;
        }
        let probe = if count % 16 == 0 { Some(idx as u64) } else { None };
        let want_nested = o.nested && count % 7 == 0;
        let keep = if rep.failures.len() < 3 { Some(img.clone()) } else { None };
        match check_crash_image(img, o.bug, &allowed, probe, if want_nested { Some(&mut nrng) } else { None }) {
            Ok(v) => {
                if v.replayed {
                    rep.replays += 1;
                }
                rep.nested_states += v.nested;
            }
            Err(what) => rep.failures.push(CrashFailure { event: idx, ops_done: done, variant: name.to_string(), what, image: keep.unwrap_or_default() }),
        }
        !(o.max_failures > 0 && rep.failures.len() >= o.max_failures)
    });
    rep
}

#[allow(dead_code)]
fn _assert_dev<D: BlockDev>() {}
