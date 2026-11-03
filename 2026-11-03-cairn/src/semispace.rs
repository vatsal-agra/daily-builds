//! Cheney's two-space copying collector. Allocation is a pointer bump; collection copies live
//! objects breadth-first into the other half and leaves forwarding pointers behind.

use crate::heap::*;

pub struct Semispace {
    mem: Vec<u64>,
    half: usize,
    /// first address of the active (from) space
    base: Addr,
    top: Addr,
    stats: Stats,
    torture: bool,
}

impl Semispace {
    /// `words` is the total budget; each semispace gets half of it.
    pub fn new(words: usize) -> Semispace {
        let half = (words / 2).max(8);
        Semispace { mem: vec![0u64; 1 + 2 * half], half, base: 1, top: 1, stats: Stats::new(), torture: false }
    }

    fn limit(&self) -> Addr {
        self.base + self.half
    }

    fn evacuate(&mut self, v: Value, free: &mut Addr) -> Value {
        if !v.is_ptr() {
            return v;
        }
        let a = v.addr();
        let h = self.mem[a];
        if h & FWD != 0 {
            return Value(self.mem[a + 1]);
        }
        let t = hdr_total(h);
        let n = *free;
        self.mem.copy_within(a..a + t, n);
        self.mem[n] &= !FLAGS;
        *free += t;
        self.mem[a] |= FWD;
        self.mem[a + 1] = Value::ptr(n).0;
        self.stats.copied_words += t as u64;
        Value::ptr(n)
    }

    fn cycle(&mut self, roots: &mut [Value]) {
        let t = self.stats.now_ns();
        let freed_before = self.top - self.base;
        let to = if self.base == 1 { 1 + self.half } else { 1 };
        let mut free = to;
        for r in roots.iter_mut() {
            *r = self.evacuate(*r, &mut free);
        }
        let mut scan = to;
        while scan < free {
            let h = self.mem[scan];
            let tot = hdr_total(h);
            if has_fields(hdr_kind(h)) {
                for i in 0..hdr_len(h) {
                    let v = Value(self.mem[scan + 1 + i]);
                    let nv = self.evacuate(v, &mut free);
                    self.mem[scan + 1 + i] = nv.0;
                }
            }
            scan += tot;
        }
        let live = free - to;
        self.base = to;
        self.top = free;
        self.stats.collections += 1;
        self.stats.freed_words += (freed_before - live) as u64;
        let used = self.used_words();
        self.stats.record("full", t, live as u64, used);
    }
}

impl Gc for Semispace {
    fn name(&self) -> &'static str {
        "semispace"
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
            self.cycle(roots);
        }
        if self.top + total > self.limit() {
            self.cycle(roots);
            if self.top + total > self.limit() {
                return Err(OutOfMemory {
                    requested: total,
                    detail: format!("live data {} of {} words per semispace", self.top - self.base, self.half),
                });
            }
        }
        let a = self.top;
        self.top += total;
        init_object(&mut self.mem, a, kind, len, 0);
        self.stats.alloc_objects += 1;
        self.stats.alloc_words += total as u64;
        let u = self.used_words();
        self.stats.peak_used = self.stats.peak_used.max(u);
        Ok(Value::ptr(a))
    }
    fn collect(&mut self, roots: &mut Vec<Value>, _full: bool) -> Result<(), OutOfMemory> {
        self.cycle(roots);
        Ok(())
    }
    fn used_words(&self) -> usize {
        self.top - self.base
    }
    fn capacity_words(&self) -> usize {
        self.half
    }
    fn walk(&self) -> Vec<(Addr, usize, bool)> {
        let mut v = Vec::new();
        walk_range(&self.mem, self.base, self.top, &mut v);
        v
    }
    fn set_torture(&mut self, on: bool) {
        self.torture = on;
    }
    fn largest_free(&self) -> usize {
        self.limit() - self.top
    }
}
