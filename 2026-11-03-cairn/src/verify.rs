//! The oracle: a collector-independent view of the heap.
//!
//! `snapshot` walks everything reachable from the roots in a canonical order (BFS, fields in
//! order) and numbers objects by discovery. Two heaps holding the "same" data — whatever their
//! addresses, whichever collector moved things around — produce equal snapshots.

use crate::heap::*;
use std::collections::{HashMap, HashSet};

#[derive(Clone, Copy, PartialEq, Eq, Debug, Hash)]
pub enum Cell {
    Nil,
    Int(i64),
    Ref(usize),
}

#[derive(Clone, PartialEq, Eq, Debug, Hash)]
pub struct Node {
    pub kind: u8,
    pub fields: Vec<Cell>,
    pub bytes: Vec<u8>,
}

#[derive(Clone, PartialEq, Eq, Debug, Hash)]
pub struct Snapshot {
    pub roots: Vec<Cell>,
    pub nodes: Vec<Node>,
}

impl Snapshot {
    /// FNV-1a over the canonical form, folded to a non-negative 62-bit integer.
    pub fn digest(&self) -> i64 {
        let mut h: u64 = 0xcbf29ce484222325;
        let mut eat = |x: u64| {
            for b in x.to_le_bytes() {
                h ^= b as u64;
                h = h.wrapping_mul(0x100000001b3);
            }
        };
        let cell = |c: &Cell| match c {
            Cell::Nil => 0u64,
            Cell::Int(i) => (*i as u64).wrapping_mul(3) ^ 1,
            Cell::Ref(r) => ((*r as u64) << 2) | 2,
        };
        for r in &self.roots {
            eat(cell(r));
        }
        for n in &self.nodes {
            eat(n.kind as u64);
            eat(n.fields.len() as u64);
            for f in &n.fields {
                eat(cell(f));
            }
            eat(n.bytes.len() as u64);
            for b in &n.bytes {
                eat(*b as u64);
            }
        }
        (h >> 2) as i64
    }
}

pub fn snapshot(gc: &dyn Gc, roots: &[Value]) -> Snapshot {
    let mut ids: HashMap<Addr, usize> = HashMap::new();
    let mut order: Vec<Addr> = Vec::new();
    let cell_of = |v: Value, ids: &mut HashMap<Addr, usize>, order: &mut Vec<Addr>| -> Cell {
        if v.is_nil() {
            Cell::Nil
        } else if v.is_int() {
            Cell::Int(v.as_int())
        } else {
            let next = ids.len();
            let id = *ids.entry(v.addr()).or_insert_with(|| {
                order.push(v.addr());
                next
            });
            Cell::Ref(id)
        }
    };
    let rcells: Vec<Cell> = roots.iter().map(|r| cell_of(*r, &mut ids, &mut order)).collect();
    let mut nodes = Vec::new();
    let mut i = 0;
    while i < order.len() {
        let a = order[i];
        let v = Value::ptr(a);
        let k = gc.kind(v);
        let mut fields = Vec::new();
        let mut bytes = Vec::new();
        match k {
            Kind::Pair | Kind::Vec => {
                for j in 0..gc.len(v) {
                    fields.push(cell_of(gc.load(v, j), &mut ids, &mut order));
                }
            }
            Kind::Str => bytes = gc.str_bytes(v),
            Kind::Free => bytes = b"<FREE>".to_vec(),
        }
        nodes.push(Node {
            kind: k as u8,
            fields,
            bytes,
        });
        i += 1;
    }
    Snapshot { roots: rcells, nodes }
}

/// Structural health check; returns human-readable violations (empty = healthy).
pub fn check_heap(gc: &dyn Gc, roots: &[Value]) -> Vec<String> {
    let mut errs = Vec::new();
    let blocks = gc.walk();
    let starts: HashSet<Addr> = blocks.iter().filter(|b| !b.2).map(|b| b.0).collect();
    let mem = gc.mem();
    let incremental = gc.name() == "incremental";
    for &(a, t, free) in &blocks {
        let h = mem[a];
        if h & (FWD | GREY) != 0 {
            errs.push(format!("block {a}: stray FWD/GREY flag in header {h:#x}"));
        }
        if !incremental && !free && h & MARK != 0 {
            errs.push(format!("block {a}: MARK bit left set outside a collection"));
        }
        if !free && hdr_kind(h) == Kind::Str {
            let n = mem[a + 1] as usize;
            if str_words(n) > hdr_len(h) {
                errs.push(format!("string {a}: byte length {n} exceeds payload"));
            }
        }
        if t == 0 {
            errs.push(format!("block {a}: zero size"));
        }
    }
    // Pointers are only required to be valid on objects the program can still reach: unreachable
    // garbage may legitimately point into memory that has already been reclaimed.
    let mut seen: HashSet<Addr> = HashSet::new();
    let mut q: Vec<(Addr, String)> = Vec::new();
    for (i, r) in roots.iter().enumerate() {
        if r.is_ptr() {
            q.push((r.addr(), format!("root {i}")));
        }
    }
    while let Some((a, from)) = q.pop() {
        if !starts.contains(&a) {
            errs.push(format!("{from}: dangling pointer {a}"));
            continue;
        }
        if !seen.insert(a) {
            continue;
        }
        let h = mem[a];
        if has_fields(hdr_kind(h)) {
            for i in 0..hdr_len(h) {
                let v = Value(mem[a + 1 + i]);
                if v.is_ptr() {
                    q.push((v.addr(), format!("object {a} field {i}")));
                }
            }
        }
    }
    errs.extend(gc.check_invariants(roots));
    errs
}
