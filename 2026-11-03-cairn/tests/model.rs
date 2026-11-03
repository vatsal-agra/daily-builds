//! Model-based property test: drive every collector directly through the `Gc` API with a random
//! operation stream while a plain-Rust shadow graph (no heap, no addresses) records what the heap
//! *should* contain. After every operation the heap's canonical snapshot must equal the model's.
mod common;
use cairn::heap::*;
use cairn::verify::{check_heap, snapshot, Cell, Node, Snapshot};
use cairn::*;

struct Rng(u64);
impl Rng {
    fn next(&mut self) -> u64 {
        let mut x = self.0;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        self.0 = x;
        x.wrapping_mul(0x2545F4914F6CDD1D) >> 11
    }
    fn below(&mut self, n: usize) -> usize {
        (self.next() % n as u64) as usize
    }
}

#[derive(Clone)]
enum M {
    Nil,
    Int(i64),
    Obj(usize),
}

struct ModelNode {
    kind: Kind,
    fields: Vec<M>,
    bytes: Vec<u8>,
}

struct Model {
    nodes: Vec<ModelNode>,
    roots: Vec<M>,
}

impl Model {
    fn snapshot(&self) -> Snapshot {
        let mut ids: std::collections::HashMap<usize, usize> = Default::default();
        let mut order: Vec<usize> = Vec::new();
        let cell = |m: &M, ids: &mut std::collections::HashMap<usize, usize>, order: &mut Vec<usize>| match m {
            M::Nil => Cell::Nil,
            M::Int(i) => Cell::Int(*i),
            M::Obj(o) => {
                let n = ids.len();
                Cell::Ref(*ids.entry(*o).or_insert_with(|| {
                    order.push(*o);
                    n
                }))
            }
        };
        let roots: Vec<Cell> = self.roots.iter().map(|m| cell(m, &mut ids, &mut order)).collect();
        let mut nodes = Vec::new();
        let mut i = 0;
        while i < order.len() {
            let n = &self.nodes[order[i]];
            let fields = n.fields.iter().map(|m| cell(m, &mut ids, &mut order)).collect();
            nodes.push(Node {
                kind: n.kind as u8,
                fields,
                bytes: n.bytes.clone(),
            });
            i += 1;
        }
        Snapshot { roots, nodes }
    }
}

/// Run one randomized session. Every heap object is addressed through a root slot so the model
/// can name it; "fields" always hold values copied from root slots.
fn session(gc_name: &str, seed: u64, ops: usize, check_every_op: bool) {
    let cfg = GcConfig {
        words: 5000,
        nursery: 500,
        barrier: true,
        trigger: 0.3,
        pace: 2,
    };
    let mut gc = make_gc(gc_name, &cfg).unwrap();
    const SLOTS: usize = 12;
    let mut roots: Vec<Value> = vec![Value::NIL; SLOTS];
    // model: roots[i] <-> model.roots[i]
    let mut model = Model {
        nodes: Vec::new(),
        roots: vec![M::Nil; SLOTS],
    };
    let mut rng = Rng(seed.wrapping_mul(0x9E3779B97F4A7C15) | 1);

    for step in 0..ops {
        let a = rng.below(SLOTS);
        let b = rng.below(SLOTS);
        match rng.below(10) {
            0 | 1 => {
                // new pair in slot a holding slot b and slot c
                let c = rng.below(SLOTS);
                let tmp = roots.len();
                roots.push(roots[b]);
                roots.push(roots[c]);
                let p = gc.alloc(Kind::Pair, 2, &mut roots).unwrap();
                let (vb, vc) = (roots[tmp], roots[tmp + 1]);
                gc.store(p, 0, vb);
                gc.store(p, 1, vc);
                roots.truncate(tmp);
                roots[a] = p;
                let node = ModelNode {
                    kind: Kind::Pair,
                    fields: vec![model.roots[b].clone(), model.roots[c].clone()],
                    bytes: vec![],
                };
                model.nodes.push(node);
                model.roots[a] = M::Obj(model.nodes.len() - 1);
            }
            2 => {
                let n = rng.below(40);
                let p = gc.alloc(Kind::Vec, n, &mut roots).unwrap();
                roots[a] = p;
                model.nodes.push(ModelNode {
                    kind: Kind::Vec,
                    fields: vec![M::Nil; n],
                    bytes: vec![],
                });
                model.roots[a] = M::Obj(model.nodes.len() - 1);
            }
            3 => {
                let len = rng.below(30);
                let bytes: Vec<u8> = (0..len).map(|_| rng.below(256) as u8).collect();
                let p = gc.alloc_str(&bytes, &mut roots).unwrap();
                roots[a] = p;
                model.nodes.push(ModelNode {
                    kind: Kind::Str,
                    fields: vec![],
                    bytes,
                });
                model.roots[a] = M::Obj(model.nodes.len() - 1);
            }
            4 | 5 => {
                // store slot b into a field of the object in slot a
                if let M::Obj(o) = model.roots[a] {
                    let nf = model.nodes[o].fields.len();
                    if nf > 0 && has_fields(model.nodes[o].kind) {
                        let i = rng.below(nf);
                        gc.store(roots[a], i, roots[b]);
                        let v = model.roots[b].clone();
                        model.nodes[o].fields[i] = v;
                    }
                }
            }
            6 => {
                // load a field into slot b
                if let M::Obj(o) = model.roots[a] {
                    let nf = model.nodes[o].fields.len();
                    if nf > 0 && has_fields(model.nodes[o].kind) {
                        let i = rng.below(nf);
                        roots[b] = gc.load(roots[a], i);
                        model.roots[b] = model.nodes[o].fields[i].clone();
                    }
                }
            }
            7 => {
                roots[a] = Value::NIL;
                model.roots[a] = M::Nil;
            }
            8 => {
                let n = rng.below(1000) as i64 - 300;
                roots[a] = Value::int(n);
                model.roots[a] = M::Int(n);
            }
            _ => {
                if rng.below(3) == 0 {
                    gc.collect(&mut roots, rng.below(2) == 0).unwrap();
                } else {
                    roots[a] = roots[b];
                    model.roots[a] = model.roots[b].clone();
                }
            }
        }
        if check_every_op || step % 50 == 49 {
            let errs = check_heap(gc.as_ref(), &roots);
            assert!(errs.is_empty(), "{gc_name} seed {seed} step {step}: {errs:?}");
            assert!(
                snapshot(gc.as_ref(), &roots) == model.snapshot(),
                "{gc_name} seed {seed} step {step}: heap diverged from model"
            );
        }
        // keep the model from growing without bound: forget unreachable nodes occasionally
        if model.nodes.len() > 20_000 {
            break;
        }
    }
    gc.finish(&mut roots).unwrap();
    gc.collect(&mut roots, true).unwrap();
    assert!(
        snapshot(gc.as_ref(), &roots) == model.snapshot(),
        "{gc_name} seed {seed}: final heap diverged from model"
    );
    let errs = check_heap(gc.as_ref(), &roots);
    assert!(errs.is_empty(), "{gc_name} seed {seed}: {errs:?}");
}

#[test]
fn heap_matches_shadow_model_after_every_operation() {
    for g in ALL_GCS {
        for seed in 1..=40 {
            session(g, seed, 600, true);
        }
    }
}

#[test]
fn long_sessions_stay_in_sync() {
    for g in ALL_GCS {
        for seed in 100..110 {
            session(g, seed, 6000, false);
        }
    }
}
