//! Sliding mark-compact (Lisp2-style): mark, compute forwarding addresses in a side table,
//! rewrite every reference, then slide survivors down preserving allocation order.
//! Allocation is a pointer bump; there is no fragmentation.

use crate::heap::*;

pub struct Compact {
    mem: Vec<u64>,
    top: Addr,
    stats: Stats,
    stack: Vec<Addr>,
    fwd: Vec<u32>,
    torture: bool,
}

impl Compact {
    pub fn new(words: usize) -> Compact {
        let words = words.max(16);
        assert!(words < u32::MAX as usize, "compact heap limited to 4G words");
        Compact {
            mem: vec![0u64; words + 1],
            top: 1,
            stats: Stats::new(),
            stack: Vec::new(),
            fwd: Vec::new(),
            torture: false,
        }
    }

    fn cycle(&mut self, roots: &mut [Value]) {
        let t = self.stats.now_ns();
        let before = self.top - 1;
        let marked = mark_all(&mut self.mem, roots, &mut self.stack);
        // phase 2: forwarding addresses
        if self.fwd.len() < self.mem.len() {
            self.fwd.resize(self.mem.len(), 0);
        }
        let mut dest = 1usize;
        let mut a = 1usize;
        while a < self.top {
            let h = self.mem[a];
            let tot = hdr_total(h);
            if h & MARK != 0 {
                self.fwd[a] = dest as u32;
                dest += tot;
            }
            a += tot;
        }
        // phase 3: rewrite roots and the fields of every live object
        for r in roots.iter_mut() {
            if r.is_ptr() {
                *r = Value::ptr(self.fwd[r.addr()] as usize);
            }
        }
        a = 1;
        while a < self.top {
            let h = self.mem[a];
            let tot = hdr_total(h);
            if h & MARK != 0 && has_fields(hdr_kind(h)) {
                for i in 0..hdr_len(h) {
                    let v = Value(self.mem[a + 1 + i]);
                    if v.is_ptr() {
                        self.mem[a + 1 + i] = Value::ptr(self.fwd[v.addr()] as usize).0;
                    }
                }
            }
            a += tot;
        }
        // phase 4: slide
        a = 1;
        while a < self.top {
            let h = self.mem[a];
            let tot = hdr_total(h);
            if h & MARK != 0 {
                let d = self.fwd[a] as usize;
                if d != a {
                    self.mem.copy_within(a..a + tot, d);
                }
                self.mem[d] &= !MARK;
                self.stats.copied_words += (tot as u64) * (d != a) as u64;
            }
            a += tot;
        }
        self.top = dest;
        self.stats.collections += 1;
        self.stats.freed_words += (before - (dest - 1)) as u64;
        let used = self.used_words();
        self.stats.record("full", t, marked * 3, used);
    }
}

impl Gc for Compact {
    fn name(&self) -> &'static str {
        "compact"
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
        if self.top + total > self.mem.len() {
            self.cycle(roots);
            if self.top + total > self.mem.len() {
                return Err(OutOfMemory {
                    requested: total,
                    detail: format!("live data {} of {} words", self.top - 1, self.mem.len() - 1),
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
        self.top - 1
    }
    fn capacity_words(&self) -> usize {
        self.mem.len() - 1
    }
    fn walk(&self) -> Vec<(Addr, usize, bool)> {
        let mut v = Vec::new();
        walk_range(&self.mem, 1, self.top, &mut v);
        v
    }
    fn set_torture(&mut self, on: bool) {
        self.torture = on;
    }
    fn largest_free(&self) -> usize {
        self.mem.len() - self.top
    }
}
