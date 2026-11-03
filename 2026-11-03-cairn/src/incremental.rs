//! Incremental tri-colour mark-sweep using a snapshot-at-the-beginning (Yuasa) deletion barrier.
//!
//! * White = MARK clear, grey = MARK set and on the mark stack, black = MARK set, scanned.
//! * A cycle begins with a short stop-the-world root scan (the snapshot), then the mutator runs
//!   while marking and sweeping proceed in small increments paid for by allocation.
//! * Deletion barrier: overwriting a pointer shades the *old* value, so nothing reachable at
//!   snapshot time can be lost, even if the mutator hides it from the collector.
//! * New objects are allocated black during marking (they can only be reached from roots or from
//!   objects the collector will never need to scan again).
//! * Sweeping is incremental too. The free list is emptied when sweeping begins and refilled
//!   behind the sweep pointer, so allocation only ever uses already-swept (white) blocks.
//!
//! `barrier` can be switched off to demonstrate the lost-object bug the barrier prevents.

use crate::heap::*;

#[derive(Copy, Clone, PartialEq, Eq, Debug)]
pub enum Phase {
    Idle,
    Marking,
    Sweeping,
}

pub struct Incremental {
    mem: Vec<u64>,
    free: FreeList,
    stats: Stats,
    stack: Vec<Addr>,
    phase: Phase,
    sweep_ptr: Addr,
    run: Option<(Addr, usize)>,
    pub barrier: bool,
    /// start a cycle when used/capacity reaches this fraction
    pub trigger: f64,
    /// units of collector work performed per allocated word
    pub pace: usize,
    torture: bool,
    cycle_work: u64,
    cycle_freed: u64,
    cycles: u64,
    live_after: usize,
    /// words allocated while marking (floating garbage upper bound)
    pub black_alloc: u64,
}

impl Incremental {
    pub fn new(words: usize) -> Incremental {
        let words = words.max(32);
        let mut mem = vec![0u64; words + 1];
        let mut free = FreeList::new();
        free.add(&mut mem, 1, words);
        Incremental {
            mem,
            free,
            stats: Stats::new(),
            stack: Vec::new(),
            phase: Phase::Idle,
            sweep_ptr: 1,
            run: None,
            barrier: true,
            trigger: 0.5,
            pace: 6,
            torture: false,
            cycle_work: 0,
            cycle_freed: 0,
            cycles: 0,
            live_after: 0,
            black_alloc: 0,
        }
    }

    /// Occupancy at which the next cycle starts: the configured fraction of the heap, but never
    /// closer to the last cycle's live size than half the remaining headroom (so a heap that is
    /// mostly live doesn't collect back-to-back).
    pub fn next_trigger(&self) -> usize {
        let cap = self.capacity_words();
        let fixed = (self.trigger * cap as f64) as usize;
        let adaptive = self.live_after + (cap.saturating_sub(self.live_after)) / 2;
        if self.trigger >= 1.0 {
            fixed
        } else {
            fixed.max(adaptive.min(cap))
        }
    }

    pub fn phase(&self) -> Phase {
        self.phase
    }
    pub fn cycles(&self) -> u64 {
        self.cycles
    }

    fn shade(&mut self, v: Value) {
        if v.is_ptr() {
            let a = v.addr();
            if self.mem[a] & MARK == 0 {
                self.mem[a] |= MARK;
                self.stack.push(a);
            }
        }
    }

    fn start_cycle(&mut self, roots: &[Value]) {
        let t = self.stats.now_ns();
        self.phase = Phase::Marking;
        self.stack.clear();
        for r in roots {
            self.shade(*r);
        }
        self.cycle_work = roots.len() as u64;
        self.cycle_freed = 0;
        let used = self.used_words();
        self.stats.record("root-scan", t, roots.len() as u64, used);
    }

    /// Scan up to `units` grey objects. Returns true when the mark stack drained.
    fn mark_step(&mut self, units: usize) -> usize {
        let mut done = 0;
        while done < units {
            let Some(a) = self.stack.pop() else { break };
            let h = self.mem[a];
            if has_fields(hdr_kind(h)) {
                for i in 0..hdr_len(h) {
                    let v = Value(self.mem[a + 1 + i]);
                    self.shade(v);
                }
            }
            done += 1;
        }
        done
    }

    fn begin_sweep(&mut self) {
        self.phase = Phase::Sweeping;
        self.free.clear();
        self.sweep_ptr = 1;
        self.run = None;
    }

    fn sweep_step(&mut self, units: usize) -> usize {
        let end = self.mem.len();
        let mut done = 0;
        while done < units && self.sweep_ptr < end {
            let a = self.sweep_ptr;
            let h = self.mem[a];
            let t = hdr_total(h);
            if hdr_kind(h) == Kind::Free || h & MARK == 0 {
                if hdr_kind(h) != Kind::Free {
                    self.cycle_freed += t as u64;
                }
                self.run = match self.run {
                    Some((s, l)) => Some((s, l + t)),
                    None => Some((a, t)),
                };
            } else {
                if let Some((s, l)) = self.run.take() {
                    self.free.add(&mut self.mem, s, l);
                }
                self.mem[a] &= !MARK;
            }
            self.sweep_ptr += t;
            done += 1;
        }
        if self.sweep_ptr >= end {
            if let Some((s, l)) = self.run.take() {
                self.free.add(&mut self.mem, s, l);
            }
            self.phase = Phase::Idle;
            self.cycles += 1;
            self.live_after = self.used_words();
            self.stats.collections += 1;
            self.stats.freed_words += self.cycle_freed;
        }
        done
    }

    /// Perform `units` of collector work in the current phase (recorded as one pause).
    fn step(&mut self, units: usize) {
        if self.phase == Phase::Idle {
            return;
        }
        let t = self.stats.now_ns();
        let mut work = 0usize;
        if self.phase == Phase::Marking {
            work += self.mark_step(units);
            if self.stack.is_empty() {
                self.begin_sweep();
            }
        }
        if self.phase == Phase::Sweeping && work < units {
            work += self.sweep_step(units - work);
        }
        let used = self.used_words();
        self.stats.record("increment", t, work as u64, used);
    }

    fn drive_to_idle(&mut self) {
        while self.phase != Phase::Idle {
            self.step(4096);
        }
    }

    fn try_alloc(&mut self, total: usize) -> Option<Addr> {
        self.free.alloc(&mut self.mem, total)
    }
}

impl Gc for Incremental {
    fn name(&self) -> &'static str {
        "incremental"
    }
    fn mem(&self) -> &[u64] {
        &self.mem
    }
    fn mem_mut(&mut self) -> &mut [u64] {
        &mut self.mem
    }
    fn stats(&self) -> &Stats {
        &self.stats
    }
    fn stats_mut(&mut self) -> &mut Stats {
        &mut self.stats
    }
    fn alloc(&mut self, kind: Kind, len: usize, roots: &mut Vec<Value>) -> Result<Value, OutOfMemory> {
        let total = total_for(len);
        if self.torture {
            self.drive_to_idle();
            self.start_cycle(roots);
            self.drive_to_idle();
        }
        if self.phase == Phase::Idle && self.used_words() >= self.next_trigger() {
            self.start_cycle(roots);
        }
        if self.phase != Phase::Idle {
            self.step(self.pace * total);
        }
        let mut got = self.try_alloc(total);
        // stalled: pay the debt in larger chunks until the current cycle finishes
        while got.is_none() && self.phase != Phase::Idle {
            self.step(256);
            got = self.try_alloc(total);
        }
        if got.is_none() {
            // a whole fresh cycle may reclaim objects allocated black in the previous one
            self.start_cycle(roots);
            self.drive_to_idle();
            got = self.try_alloc(total);
        }
        let Some(a) = got else {
            return Err(OutOfMemory {
                requested: total,
                detail: format!("{} free words, largest block {}", self.free.words, self.largest_free()),
            });
        };
        let black = if self.phase == Phase::Marking { MARK } else { 0 };
        if black != 0 {
            self.black_alloc += total as u64;
        }
        init_object(&mut self.mem, a, kind, len, black);
        self.stats.alloc_objects += 1;
        self.stats.alloc_words += total as u64;
        let u = self.used_words();
        self.stats.peak_used = self.stats.peak_used.max(u);
        Ok(Value::ptr(a))
    }
    fn collect(&mut self, roots: &mut Vec<Value>, _full: bool) -> Result<(), OutOfMemory> {
        // finish the in-flight cycle, then run one whole fresh cycle so garbage that was allocated
        // black (or was reachable at the previous snapshot) is reclaimed too
        self.drive_to_idle();
        self.start_cycle(roots);
        self.drive_to_idle();
        Ok(())
    }
    fn begin_cycle(&mut self, roots: &mut Vec<Value>) {
        if self.phase == Phase::Idle {
            self.start_cycle(roots);
        }
    }
    fn finish(&mut self, _roots: &mut Vec<Value>) -> Result<(), OutOfMemory> {
        self.drive_to_idle();
        Ok(())
    }
    fn write_barrier(&mut self, _obj: Addr, _slot: usize, old: Value, _new: Value) {
        self.stats.barrier_calls += 1;
        if self.barrier && self.phase == Phase::Marking && old.is_ptr() {
            let a = old.addr();
            if self.mem[a] & MARK == 0 {
                self.stats.barrier_hits += 1;
                self.shade(old);
            }
        }
    }
    fn used_words(&self) -> usize {
        self.mem.len() - 1 - self.free.words
    }
    fn capacity_words(&self) -> usize {
        self.mem.len() - 1
    }
    fn walk(&self) -> Vec<(Addr, usize, bool)> {
        let mut v = Vec::new();
        walk_range(&self.mem, 1, self.mem.len(), &mut v);
        v
    }
    fn check_invariants(&self, roots: &[Value]) -> Vec<String> {
        // Safety property: any object reachable from the roots must never be a FREE block, and
        // while sweeping, an unswept reachable object must be marked (else it is about to be freed).
        let mut errs = Vec::new();
        let mut seen = std::collections::HashSet::new();
        let mut q: Vec<Addr> = roots.iter().filter(|v| v.is_ptr()).map(|v| v.addr()).collect();
        while let Some(a) = q.pop() {
            if !seen.insert(a) {
                continue;
            }
            let h = self.mem[a];
            if hdr_kind(h) == Kind::Free {
                errs.push(format!("reachable object at {a} was freed (lost object)"));
                continue;
            }
            if self.phase == Phase::Sweeping && a >= self.sweep_ptr && h & MARK == 0 {
                errs.push(format!("reachable unswept object at {a} is white: it will be freed (lost object)"));
            }
            if self.phase == Phase::Marking && self.stack.is_empty() && h & MARK == 0 {
                errs.push(format!("marking finished but reachable object at {a} is white"));
            }
            if has_fields(hdr_kind(h)) {
                for i in 0..hdr_len(h) {
                    let v = Value(self.mem[a + 1 + i]);
                    if v.is_ptr() {
                        q.push(v.addr());
                    }
                }
            }
        }
        errs
    }
    fn set_torture(&mut self, on: bool) {
        self.torture = on;
    }
    fn largest_free(&self) -> usize {
        self.free.largest(&self.mem)
    }
}
