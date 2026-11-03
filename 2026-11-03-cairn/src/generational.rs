//! Generational collector: a bump-allocated nursery in front of a mark-sweep old generation.
//!
//! * Address space: `[1, 1+N)` nursery, `[1+N, 1+N+M)` old generation.
//! * Minor GC: copy (promote) everything reachable from roots + the remembered set out of the
//!   nursery into the old generation. Survivors are promoted on first survival.
//! * Write barrier: storing a nursery pointer into an old object records that object in the
//!   remembered set (once, tracked by the REM header bit).
//! * Major GC: mark the whole heap, sweep the old generation, rebuild the remembered set.
//! * Large objects (more than half the nursery) are allocated directly in the old generation.

use crate::heap::*;

pub struct Generational {
    mem: Vec<u64>,
    nbase: Addr,
    nend: Addr,
    ntop: Addr,
    obase: Addr,
    oend: Addr,
    free: FreeList,
    remset: Vec<Addr>,
    stack: Vec<Addr>,
    stats: Stats,
    torture: bool,
    /// remembered-set write barrier on/off (off = the classic old-to-young bug, for demos)
    pub barrier: bool,
}

impl Generational {
    /// `words` total budget, `nursery` words reserved for the young generation.
    pub fn new(words: usize, nursery: usize) -> Generational {
        let nursery = nursery.min(words / 4).clamp(16, words.saturating_sub(64).max(16));
        let old = words.saturating_sub(nursery).max(32);
        let mut mem = vec![0u64; 1 + nursery + old];
        let obase = 1 + nursery;
        let mut free = FreeList::new();
        free.add(&mut mem, obase, old);
        Generational {
            mem,
            nbase: 1,
            nend: obase,
            ntop: 1,
            obase,
            oend: obase + old,
            free,
            remset: Vec::new(),
            stack: Vec::new(),
            stats: Stats::new(),
            torture: false,
            barrier: true,
        }
    }

    #[inline]
    fn is_young(&self, a: Addr) -> bool {
        a < self.obase
    }

    fn evacuate(&mut self, v: Value, work: &mut Vec<Addr>) -> Result<Value, OutOfMemory> {
        if !v.is_ptr() || !self.is_young(v.addr()) {
            return Ok(v);
        }
        let a = v.addr();
        let h = self.mem[a];
        if h & FWD != 0 {
            return Ok(Value(self.mem[a + 1]));
        }
        let t = hdr_total(h);
        let Some(n) = self.free.alloc(&mut self.mem, t) else {
            return Err(OutOfMemory {
                requested: t,
                detail: "promotion failure: old generation exhausted or too fragmented".into(),
            });
        };
        self.mem.copy_within(a..a + t, n);
        self.mem[n] &= !FLAGS;
        self.mem[a] |= FWD;
        self.mem[a + 1] = Value::ptr(n).0;
        self.stats.promoted_words += t as u64;
        work.push(n);
        Ok(Value::ptr(n))
    }

    fn minor(&mut self, roots: &mut [Value]) -> Result<(), OutOfMemory> {
        let t = self.stats.now_ns();
        let used_young = self.ntop - self.nbase;
        let mut work: Vec<Addr> = Vec::new();
        let mut words = 0u64;
        for r in roots.iter_mut() {
            *r = self.evacuate(*r, &mut work)?;
        }
        let rem = std::mem::take(&mut self.remset);
        for a in rem {
            self.mem[a] &= !REM;
            let h = self.mem[a];
            if has_fields(hdr_kind(h)) {
                for i in 0..hdr_len(h) {
                    let nv = self.evacuate(Value(self.mem[a + 1 + i]), &mut work)?;
                    self.mem[a + 1 + i] = nv.0;
                }
            }
        }
        while let Some(a) = work.pop() {
            let h = self.mem[a];
            words += hdr_total(h) as u64;
            if has_fields(hdr_kind(h)) {
                for i in 0..hdr_len(h) {
                    let nv = self.evacuate(Value(self.mem[a + 1 + i]), &mut work)?;
                    self.mem[a + 1 + i] = nv.0;
                }
            }
        }
        self.ntop = self.nbase;
        self.stats.collections += 1;
        self.stats.minor_collections += 1;
        self.stats.freed_words += (used_young as u64).saturating_sub(words);
        let used = self.used_words();
        self.stats.record("minor", t, words + roots.len() as u64, used);
        Ok(())
    }

    fn major(&mut self, roots: &[Value]) {
        let t = self.stats.now_ns();
        let live = mark_all(&mut self.mem, roots, &mut self.stack);
        // clear marks left on nursery objects (they're contiguous)
        let mut a = self.nbase;
        while a < self.ntop {
            self.mem[a] &= !MARK;
            a += hdr_total(self.mem[a]);
        }
        self.free.clear();
        let obase = self.obase;
        let mut newrem: Vec<Addr> = Vec::new();
        let (_l, freed) = sweep_range(&mut self.mem, self.obase, self.oend, &mut self.free, |mem, a| {
            let h = mem[a];
            let mut young = false;
            if has_fields(hdr_kind(h)) {
                for i in 0..hdr_len(h) {
                    let v = Value(mem[a + 1 + i]);
                    if v.is_ptr() && v.addr() < obase {
                        young = true;
                    }
                }
            }
            if young {
                mem[a] |= REM;
                newrem.push(a);
            } else {
                mem[a] &= !REM;
            }
        });
        self.remset = newrem;
        self.stats.collections += 1;
        self.stats.freed_words += freed;
        let used = self.used_words();
        self.stats.record("major", t, live + freed, used);
    }

    fn minor_with_headroom(&mut self, roots: &mut [Value]) -> Result<(), OutOfMemory> {
        let young = self.ntop - self.nbase;
        // A minor GC can promote everything in the nursery, so the old generation needs that many
        // free words *and* a block big enough for the largest nursery object.
        let biggest = young.min((self.nend - self.nbase) / 2);
        let fits = |g: &Self| g.free.words >= young && g.free.largest(&g.mem) >= biggest;
        if !fits(self) {
            self.major(roots);
            if !fits(self) {
                return Err(OutOfMemory {
                    requested: young,
                    detail: format!(
                        "old generation has {} free words (largest block {}) but a minor GC may promote up to {} (fragmentation or exhaustion)",
                        self.free.words, self.free.largest(&self.mem), young
                    ),
                });
            }
        }
        self.minor(roots)
    }
}

impl Gc for Generational {
    fn name(&self) -> &'static str {
        "generational"
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
            self.minor_with_headroom(roots)?;
            self.major(roots);
        }
        let nursery = self.nend - self.nbase;
        let a = if total > nursery / 2 {
            // large object: straight to the old generation
            let mut got = self.free.alloc(&mut self.mem, total);
            if got.is_none() {
                self.minor_with_headroom(roots)?;
                self.major(roots);
                got = self.free.alloc(&mut self.mem, total);
            }
            got.ok_or_else(|| OutOfMemory {
                requested: total,
                detail: format!(
                    "{} free words in old generation, largest block {}",
                    self.free.words,
                    self.largest_free()
                ),
            })?
        } else {
            if self.ntop + total > self.nend {
                self.minor_with_headroom(roots)?;
            }
            let a = self.ntop;
            self.ntop += total;
            a
        };
        init_object(&mut self.mem, a, kind, len, 0);
        self.stats.alloc_objects += 1;
        self.stats.alloc_words += total as u64;
        let u = self.used_words();
        self.stats.peak_used = self.stats.peak_used.max(u);
        Ok(Value::ptr(a))
    }
    fn collect(&mut self, roots: &mut Vec<Value>, full: bool) -> Result<(), OutOfMemory> {
        self.minor_with_headroom(roots)?;
        if full {
            self.major(roots);
        }
        Ok(())
    }
    fn write_barrier(&mut self, obj: Addr, _slot: usize, _old: Value, new: Value) {
        self.stats.barrier_calls += 1;
        if self.barrier && obj >= self.obase && new.is_ptr() && new.addr() < self.obase && self.mem[obj] & REM == 0 {
            self.mem[obj] |= REM;
            self.remset.push(obj);
            self.stats.barrier_hits += 1;
        }
    }
    fn used_words(&self) -> usize {
        (self.ntop - self.nbase) + (self.oend - self.obase - self.free.words)
    }
    fn capacity_words(&self) -> usize {
        (self.nend - self.nbase) + (self.oend - self.obase)
    }
    fn walk(&self) -> Vec<(Addr, usize, bool)> {
        let mut v = Vec::new();
        walk_range(&self.mem, self.nbase, self.ntop, &mut v);
        walk_range(&self.mem, self.obase, self.oend, &mut v);
        v
    }
    fn check_invariants(&self, _roots: &[Value]) -> Vec<String> {
        // every old object holding a young pointer must be in the remembered set
        let mut errs = Vec::new();
        let remembered: std::collections::HashSet<Addr> = self.remset.iter().copied().collect();
        let mut a = self.obase;
        while a < self.oend {
            let h = self.mem[a];
            if has_fields(hdr_kind(h)) {
                for i in 0..hdr_len(h) {
                    let v = Value(self.mem[a + 1 + i]);
                    if v.is_ptr() && self.is_young(v.addr()) && (h & REM == 0 || !remembered.contains(&a)) {
                        errs.push(format!(
                            "old object {a} slot {i} points to young {} but is not remembered",
                            v.addr()
                        ));
                    }
                }
            }
            a += hdr_total(h);
        }
        errs
    }
    fn set_torture(&mut self, on: bool) {
        self.torture = on;
    }
    fn largest_free(&self) -> usize {
        self.free.largest(&self.mem).max(self.nend - self.ntop)
    }
}
