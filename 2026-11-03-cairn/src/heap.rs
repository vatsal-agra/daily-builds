//! Value tagging, object layout, the `Gc` trait and the shared free-list.
//!
//! Heap memory is a `Vec<u64>`; an *address* is a word index. Address 0 is never an object, so
//! `Value(0)` is `nil`. Integers are 63-bit with the low tag bit set; pointers are `addr << 1`.
//!
//! Object layout: `[header][payload...]`.
//! header bits: 0-2 kind | 3 FWD | 4 MARK | 5 GREY | 6 REM | 7-8 age | 16.. len
//! `len` is the number of payload words for FREE/STR, field count for PAIR/VEC. Every non-FREE
//! object occupies `1 + max(len,1)` words so a forwarding pointer always fits in payload[0].

use std::time::Instant;

pub type Addr = usize;

#[derive(Copy, Clone, PartialEq, Eq, Debug, Hash)]
pub struct Value(pub u64);

impl Value {
    pub const NIL: Value = Value(0);
    #[inline]
    pub fn int(i: i64) -> Value {
        Value(((i as u64) << 1) | 1)
    }
    #[inline]
    pub fn ptr(a: Addr) -> Value {
        debug_assert!(a != 0);
        Value((a as u64) << 1)
    }
    #[inline]
    pub fn is_int(self) -> bool {
        self.0 & 1 == 1
    }
    #[inline]
    pub fn is_nil(self) -> bool {
        self.0 == 0
    }
    #[inline]
    pub fn is_ptr(self) -> bool {
        self.0 != 0 && self.0 & 1 == 0
    }
    #[inline]
    pub fn as_int(self) -> i64 {
        (self.0 as i64) >> 1
    }
    #[inline]
    pub fn addr(self) -> Addr {
        (self.0 >> 1) as Addr
    }
}

#[derive(Copy, Clone, PartialEq, Eq, Debug)]
#[repr(u8)]
pub enum Kind {
    Free = 0,
    Pair = 1,
    Vec = 2,
    Str = 3,
}

pub const FWD: u64 = 1 << 3;
pub const MARK: u64 = 1 << 4;
pub const GREY: u64 = 1 << 5;
pub const REM: u64 = 1 << 6;
pub const FLAGS: u64 = FWD | MARK | GREY | REM;
const LEN_SHIFT: u32 = 16;

#[inline]
pub fn make_header(kind: Kind, len: usize) -> u64 {
    (kind as u64) | ((len as u64) << LEN_SHIFT)
}
#[inline]
pub fn hdr_kind(h: u64) -> Kind {
    match h & 7 {
        0 => Kind::Free,
        1 => Kind::Pair,
        2 => Kind::Vec,
        3 => Kind::Str,
        k => panic!("corrupt header kind {k} (header {h:#x})"),
    }
}
#[inline]
pub fn hdr_len(h: u64) -> usize {
    (h >> LEN_SHIFT) as usize
}
/// Total words an object with this header occupies, header included.
#[inline]
pub fn hdr_total(h: u64) -> usize {
    let len = hdr_len(h);
    if h & 7 == 0 {
        1 + len
    } else {
        1 + len.max(1)
    }
}
/// Total words needed for a fresh object of `kind` with `len`.
#[inline]
pub fn total_for(len: usize) -> usize {
    1 + len.max(1)
}
/// Number of payload words for a string of `bytes` bytes (1 length word + packed bytes).
pub fn str_words(bytes: usize) -> usize {
    1 + bytes.div_ceil(8)
}
/// Does this kind hold scanned Value fields?
#[inline]
pub fn has_fields(k: Kind) -> bool {
    matches!(k, Kind::Pair | Kind::Vec)
}

#[derive(Debug, Clone)]
pub struct OutOfMemory {
    pub requested: usize,
    pub detail: String,
}
impl std::fmt::Display for OutOfMemory {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "out of memory allocating {} words ({})", self.requested, self.detail)
    }
}
impl std::error::Error for OutOfMemory {}

/// One recorded GC pause.
#[derive(Debug, Clone)]
pub struct Pause {
    /// ns since heap creation at which the pause began
    pub start_ns: u64,
    pub dur_ns: u64,
    pub kind: &'static str,
    /// deterministic work measure: words scanned/copied/swept
    pub work: u64,
}

#[derive(Debug, Clone)]
pub struct Stats {
    pub t0: Instant,
    pub pauses: Vec<Pause>,
    pub alloc_objects: u64,
    pub alloc_words: u64,
    pub collections: u64,
    pub minor_collections: u64,
    pub freed_words: u64,
    pub promoted_words: u64,
    pub copied_words: u64,
    pub barrier_calls: u64,
    pub barrier_hits: u64,
    pub peak_used: usize,
    pub timeline: Vec<Sample>,
    /// pauses beyond `PAUSE_LOG_CAP` are only aggregated
    pub overflow: Overflow,
}

/// Aggregate of pauses that no longer fit in the detailed log.
#[derive(Debug, Clone, Copy, Default)]
pub struct Overflow {
    pub count: u64,
    pub total_ns: u64,
    pub max_ns: u64,
    pub total_work: u64,
    pub max_work: u64,
}

/// Detailed pauses kept per heap (incremental collectors produce one per allocation).
pub const PAUSE_LOG_CAP: usize = 200_000;

/// Heap occupancy sample taken at the end of every pause (for the HTML report).
#[derive(Debug, Clone, Copy)]
pub struct Sample {
    pub t_ns: u64,
    pub used: usize,
}

impl Default for Stats {
    fn default() -> Self {
        Self::new()
    }
}

impl Stats {
    pub fn new() -> Stats {
        Stats {
            t0: Instant::now(),
            pauses: Vec::new(),
            alloc_objects: 0,
            alloc_words: 0,
            collections: 0,
            minor_collections: 0,
            freed_words: 0,
            promoted_words: 0,
            copied_words: 0,
            barrier_calls: 0,
            barrier_hits: 0,
            peak_used: 0,
            timeline: Vec::new(),
            overflow: Overflow::default(),
        }
    }
    pub fn now_ns(&self) -> u64 {
        self.t0.elapsed().as_nanos() as u64
    }
    pub fn record(&mut self, kind: &'static str, start_ns: u64, work: u64, used: usize) {
        let end = self.now_ns();
        let dur = end.saturating_sub(start_ns);
        if self.pauses.len() < PAUSE_LOG_CAP {
            self.pauses.push(Pause {
                start_ns,
                dur_ns: dur,
                kind,
                work,
            });
            self.timeline.push(Sample { t_ns: end, used });
        } else {
            let o = &mut self.overflow;
            o.count += 1;
            o.total_ns += dur;
            o.max_ns = o.max_ns.max(dur);
            o.total_work += work;
            o.max_work = o.max_work.max(work);
        }
    }
    pub fn pause_count(&self) -> u64 {
        self.pauses.len() as u64 + self.overflow.count
    }
    pub fn total_pause_ns(&self) -> u64 {
        self.pauses.iter().map(|p| p.dur_ns).sum::<u64>() + self.overflow.total_ns
    }
    pub fn max_pause_ns(&self) -> u64 {
        self.pauses.iter().map(|p| p.dur_ns).max().unwrap_or(0).max(self.overflow.max_ns)
    }
    pub fn max_pause_work(&self) -> u64 {
        self.pauses.iter().map(|p| p.work).max().unwrap_or(0).max(self.overflow.max_work)
    }
    pub fn total_work(&self) -> u64 {
        self.pauses.iter().map(|p| p.work).sum::<u64>() + self.overflow.total_work
    }
}

/// A precise tracing collector plus the heap it manages.
pub trait Gc {
    fn name(&self) -> &'static str;
    fn mem(&self) -> &[u64];
    fn mem_mut(&mut self) -> &mut [u64];
    fn stats(&self) -> &Stats;
    fn stats_mut(&mut self) -> &mut Stats;
    /// Allocate a zero-initialised object. `roots` is the complete root set; a moving collector
    /// updates it in place, so callers must re-read any Value they need from `roots` afterwards.
    fn alloc(&mut self, kind: Kind, len: usize, roots: &mut Vec<Value>) -> Result<Value, OutOfMemory>;
    /// Force a collection. `full` requests a major/complete cycle.
    fn collect(&mut self, roots: &mut Vec<Value>, full: bool) -> Result<(), OutOfMemory>;
    /// Called by `store` before the write lands. Default: no barrier.
    fn write_barrier(&mut self, _obj: Addr, _slot: usize, _old: Value, _new: Value) {}
    fn used_words(&self) -> usize;
    fn capacity_words(&self) -> usize;
    /// Every block in address order: (addr, total words, is_free).
    fn walk(&self) -> Vec<(Addr, usize, bool)>;
    /// Begin a collection cycle without finishing it (only meaningful for incremental collectors).
    fn begin_cycle(&mut self, _roots: &mut Vec<Value>) {}
    /// Complete any in-progress incremental work so the heap is quiescent.
    fn finish(&mut self, _roots: &mut Vec<Value>) -> Result<(), OutOfMemory> {
        Ok(())
    }
    /// Collector-specific invariant violations (empty = healthy).
    fn check_invariants(&self, _roots: &[Value]) -> Vec<String> {
        Vec::new()
    }
    fn set_torture(&mut self, on: bool);
    /// Largest contiguous free block, for fragmentation reporting.
    fn largest_free(&self) -> usize;

    // ---- provided object access ----
    #[inline]
    fn header(&self, a: Addr) -> u64 {
        self.mem()[a]
    }
    fn kind(&self, v: Value) -> Kind {
        hdr_kind(self.mem()[v.addr()])
    }
    fn len(&self, v: Value) -> usize {
        hdr_len(self.mem()[v.addr()])
    }
    #[inline]
    fn load(&self, obj: Value, i: usize) -> Value {
        debug_assert!(has_fields(self.kind(obj)) && i < self.len(obj));
        Value(self.mem()[obj.addr() + 1 + i])
    }
    #[inline]
    fn store(&mut self, obj: Value, i: usize, v: Value) {
        let a = obj.addr();
        debug_assert!(has_fields(hdr_kind(self.mem()[a])) && i < hdr_len(self.mem()[a]));
        let old = Value(self.mem()[a + 1 + i]);
        self.write_barrier(a, i, old, v);
        self.mem_mut()[a + 1 + i] = v.0;
    }
    /// Bytes of a string object.
    fn str_bytes(&self, v: Value) -> Vec<u8> {
        let a = v.addr();
        let n = self.mem()[a + 1] as usize;
        let mut out = Vec::with_capacity(n);
        for i in 0..n {
            let w = self.mem()[a + 2 + i / 8];
            out.push((w >> ((i % 8) * 8)) as u8);
        }
        out
    }
    /// Allocate a string holding `bytes`. `roots` as in `alloc`.
    fn alloc_str(&mut self, bytes: &[u8], roots: &mut Vec<Value>) -> Result<Value, OutOfMemory> {
        let v = self.alloc(Kind::Str, str_words(bytes.len()), roots)?;
        let a = v.addr();
        let m = self.mem_mut();
        m[a + 1] = bytes.len() as u64;
        for (i, b) in bytes.iter().enumerate() {
            m[a + 2 + i / 8] |= (*b as u64) << ((i % 8) * 8);
        }
        Ok(v)
    }
}

/// Write a fresh zeroed object at `a` (header + zeroed payload).
pub fn init_object(mem: &mut [u64], a: Addr, kind: Kind, len: usize, extra_flags: u64) {
    mem[a] = make_header(kind, len) | extra_flags;
    for w in &mut mem[a + 1..a + total_for(len)] {
        *w = 0;
    }
}

/// Mark everything reachable from `roots` (sets MARK, uses an explicit stack). Returns words marked.
pub fn mark_all(mem: &mut [u64], roots: &[Value], stack: &mut Vec<Addr>) -> u64 {
    let mut words = 0u64;
    let shade = |mem: &mut [u64], v: Value, stack: &mut Vec<Addr>| {
        if v.is_ptr() {
            let a = v.addr();
            if mem[a] & MARK == 0 {
                mem[a] |= MARK;
                stack.push(a);
            }
        }
    };
    for r in roots {
        shade(mem, *r, stack);
    }
    while let Some(a) = stack.pop() {
        let h = mem[a];
        words += hdr_total(h) as u64;
        if has_fields(hdr_kind(h)) {
            for i in 0..hdr_len(h) {
                let v = Value(mem[a + 1 + i]);
                shade(mem, v, stack);
            }
        }
    }
    words
}

const BINS: usize = 65;

/// Size-binned free list over blocks that carry FREE headers in memory. Bins hold block addresses
/// (exact sizes 2..=64 words) and a `large` list for the rest. Rebuilt wholesale by every sweep.
#[derive(Debug, Default, Clone)]
pub struct FreeList {
    bins: Vec<Vec<Addr>>,
    large: Vec<Addr>,
    pub words: usize,
}

impl FreeList {
    pub fn new() -> FreeList {
        FreeList {
            bins: vec![Vec::new(); BINS],
            large: Vec::new(),
            words: 0,
        }
    }
    pub fn clear(&mut self) {
        for b in &mut self.bins {
            b.clear();
        }
        self.large.clear();
        self.words = 0;
    }
    /// Turn `[addr, addr+total)` into a free block. A single word becomes an unlisted filler.
    pub fn add(&mut self, mem: &mut [u64], addr: Addr, total: usize) {
        mem[addr] = make_header(Kind::Free, total - 1);
        if total < 2 {
            return;
        }
        self.words += total;
        if total < BINS {
            self.bins[total].push(addr);
        } else {
            self.large.push(addr);
        }
    }
    /// Carve `total` words; the caller must initialise the returned object.
    pub fn alloc(&mut self, mem: &mut [u64], total: usize) -> Option<Addr> {
        // exact fit, then any larger bin, then the large list (first fit)
        let mut found: Option<(Addr, usize)> = None;
        if total < BINS {
            for s in total..BINS {
                if let Some(a) = self.bins[s].pop() {
                    found = Some((a, s));
                    break;
                }
            }
        }
        if found.is_none() {
            let idx = self.large.iter().position(|&a| hdr_total(mem[a]) >= total);
            if let Some(i) = idx {
                let a = self.large.swap_remove(i);
                found = Some((a, hdr_total(mem[a])));
            }
        }
        let (a, s) = found?;
        self.words -= s;
        let rest = s - total;
        if rest > 0 {
            self.add(mem, a + total, rest);
        }
        Some(a)
    }
    pub fn largest(&self, mem: &[u64]) -> usize {
        let l = self.large.iter().map(|&a| hdr_total(mem[a])).max().unwrap_or(0);
        if l > 0 {
            return l;
        }
        (2..BINS).rev().find(|&s| !self.bins[s].is_empty()).unwrap_or(0)
    }
}

/// Sweep `[from, to)` rebuilding `free`: unmarked and FREE blocks coalesce into runs; MARK is
/// cleared on survivors. `on_live` sees each survivor. Returns (live_words, freed_words).
pub fn sweep_range(mem: &mut [u64], from: Addr, to: Addr, free: &mut FreeList, mut on_live: impl FnMut(&mut [u64], Addr)) -> (u64, u64) {
    let (mut live, mut freed) = (0u64, 0u64);
    let mut a = from;
    let mut run: Option<(Addr, usize)> = None;
    while a < to {
        let h = mem[a];
        let t = hdr_total(h);
        if hdr_kind(h) == Kind::Free || h & MARK == 0 {
            if hdr_kind(h) != Kind::Free {
                freed += t as u64;
            }
            run = match run {
                Some((s, l)) => Some((s, l + t)),
                None => Some((a, t)),
            };
        } else {
            if let Some((s, l)) = run.take() {
                free.add(mem, s, l);
            }
            mem[a] &= !MARK;
            live += t as u64;
            on_live(mem, a);
        }
        a += t;
    }
    if let Some((s, l)) = run.take() {
        free.add(mem, s, l);
    }
    (live, freed)
}

/// Linear walk of `[from, to)`.
pub fn walk_range(mem: &[u64], from: Addr, to: Addr, out: &mut Vec<(Addr, usize, bool)>) {
    let mut a = from;
    while a < to {
        let h = mem[a];
        let t = hdr_total(h);
        out.push((a, t, hdr_kind(h) == Kind::Free));
        a += t;
    }
}
