//! Stop-the-world, non-moving mark-sweep over a size-binned free list.

use crate::heap::*;

pub struct MarkSweep {
    mem: Vec<u64>,
    free: FreeList,
    stats: Stats,
    stack: Vec<Addr>,
    torture: bool,
}

impl MarkSweep {
    pub fn new(words: usize) -> MarkSweep {
        let words = words.max(16);
        let mut mem = vec![0u64; words + 1];
        let mut free = FreeList::new();
        free.add(&mut mem, 1, words);
        MarkSweep {
            mem,
            free,
            stats: Stats::new(),
            stack: Vec::new(),
            torture: false,
        }
    }

    fn cycle(&mut self, roots: &[Value]) {
        let t = self.stats.now_ns();
        let live = mark_all(&mut self.mem, roots, &mut self.stack);
        self.free.clear();
        let end = self.mem.len();
        let (_l, freed) = sweep_range(&mut self.mem, 1, end, &mut self.free, |_, _| {});
        self.stats.collections += 1;
        self.stats.freed_words += freed;
        let used = self.used_words();
        self.stats.record("full", t, live + freed, used);
    }
}

impl Gc for MarkSweep {
    fn name(&self) -> &'static str {
        "marksweep"
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
        let mut got = self.free.alloc(&mut self.mem, total);
        if got.is_none() {
            self.cycle(roots);
            got = self.free.alloc(&mut self.mem, total);
        }
        let Some(a) = got else {
            return Err(OutOfMemory {
                requested: total,
                detail: format!("{} free words, largest block {}", self.free.words, self.largest_free()),
            });
        };
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
    fn set_torture(&mut self, on: bool) {
        self.torture = on;
    }
    fn largest_free(&self) -> usize {
        self.free.largest(&self.mem)
    }
}
