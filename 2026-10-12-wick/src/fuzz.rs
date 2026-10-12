//! Type-directed random WebAssembly program generator + case runner.
//!
//! Every generated module is valid *by construction* (expression generators are indexed by the
//! type they must leave on the stack), terminates (acyclic call graph, counted loops, no calls
//! inside loops) and avoids spec-nondeterminism (float results are NaN-canonicalised), so any
//! behavioural difference between Wick and another engine is a real bug in one of them.
use crate::ast::*;
use crate::interp::{Imports, Instance, Value};
use crate::num;
use crate::trap::Trap;
use std::fmt::Write;

pub struct Rng(pub u64);
impl Rng {
    pub fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }
    pub fn below(&mut self, n: u64) -> u64 {
        if n == 0 { 0 } else { self.next() % n }
    }
    pub fn chance(&mut self, pct: u64) -> bool {
        self.below(100) < pct
    }
    pub fn pick<'a, T>(&mut self, xs: &'a [T]) -> &'a T {
        &xs[self.below(xs.len() as u64) as usize]
    }
}

const I32_POOL: &[i32] = &[1, 1, -1, 2, 3, 7, 8, 16, 31, 32, 33, 63, 64, 100, 255, 256, 1000, 65535, 65536, 0x7fff_ffff, i32::MIN, 0x5555_5555, -2, 12345];
const I64_POOL: &[i64] = &[0, 1, -1, 2, 7, 63, 64, 255, 65536, 0xffff_ffff, 0x1_0000_0000, i64::MAX, i64::MIN, 0x5555_5555_5555_5555, -2, 1_000_000_007];
const F32_POOL: &[f32] = &[0.0, -0.0, 1.0, -1.0, 0.5, -0.5, 1.5, 2.5, -2.5, 3.5, 100.25, 1e10, -1e10, 4294967296.0, 2147483648.0, 16777216.0, f32::INFINITY, f32::NEG_INFINITY, f32::MAX, f32::MIN_POSITIVE, 1e-40, 0.1, 255.5];
const F64_POOL: &[f64] = &[0.0, -0.0, 1.0, -1.0, 0.5, -0.5, 1.5, 2.5, -2.5, 3.5, 100.25, 1e10, -1e10, 4294967296.0, 2147483648.0, 9.2e18, 1.8e19, 9007199254740993.0, f64::INFINITY, f64::NEG_INFINITY, f64::MAX, f64::MIN_POSITIVE, 5e-324, 0.1, 255.5];

pub fn rand_value(r: &mut Rng, t: ValType) -> Value {
    match t {
        ValType::I32 => Value::I32(if r.chance(55) { *r.pick(I32_POOL) } else { r.next() as i32 }),
        ValType::I64 => Value::I64(if r.chance(70) { *r.pick(I64_POOL) } else { r.next() as i64 }),
        ValType::F32 => Value::F32(if r.chance(80) { *r.pick(F32_POOL) } else { (r.next() as i64 % 100_000) as f32 / 16.0 }),
        ValType::F64 => Value::F64(if r.chance(80) { *r.pick(F64_POOL) } else { (r.next() as i64 % 1_000_000) as f64 / 64.0 }),
    }
}

fn rand_type(r: &mut Rng) -> ValType {
    *r.pick(&[ValType::I32, ValType::I32, ValType::I64, ValType::F32, ValType::F64])
}

#[derive(Clone)]
struct Lbl {
    results: Vec<ValType>,
    is_loop: bool,
}

struct Shared {
    types: Vec<FuncType>,
    sigs: Vec<FuncType>,
    globals: Vec<GlobalType>,
    table: Vec<Option<u32>>,
}

impl Shared {
    fn type_idx(&mut self, ft: &FuncType) -> u32 {
        if let Some(i) = self.types.iter().position(|t| t == ft) {
            return i as u32;
        }
        self.types.push(ft.clone());
        (self.types.len() - 1) as u32
    }
}

struct FnGen<'a> {
    r: &'a mut Rng,
    s: &'a mut Shared,
    fidx: u32,
    results: Vec<ValType>,
    locals: Vec<ValType>, // all (params first)
    pool: Vec<u32>,       // locals random code may read/write
    nparams: usize,
    scratch_f32: u32,
    scratch_f64: u32,
    labels: Vec<Lbl>,
    in_loop: u32,
    calls_left: i32,
    out: Vec<Instr>,
    new_locals: u32,
}

impl<'a> FnGen<'a> {
    fn emit(&mut self, i: Instr) {
        self.out.push(i);
    }
    fn fresh_local(&mut self, t: ValType) -> Option<u32> {
        if self.new_locals >= 60 {
            return None;
        }
        self.new_locals += 1;
        self.locals.push(t);
        Some((self.locals.len() - 1) as u32)
    }
    fn const_of(&mut self, t: ValType) {
        let v = rand_value(self.r, t);
        self.emit(match v {
            Value::I32(x) => Instr::I32Const(x),
            Value::I64(x) => Instr::I64Const(x),
            Value::F32(x) => Instr::F32Const(x.to_bits()),
            Value::F64(x) => Instr::F64Const(x.to_bits()),
        });
    }

    fn leaf(&mut self, t: ValType) {
        let locals: Vec<u32> = self.pool.iter().copied().filter(|&i| self.locals[i as usize] == t).collect();
        let globals: Vec<u32> = (0..self.s.globals.len() as u32).filter(|&i| self.s.globals[i as usize].ty == t).collect();
        let k = self.r.below(10);
        if k < 3 && !locals.is_empty() {
            let l = *self.r.pick(&locals);
            self.emit(Instr::LocalGet(l));
        } else if k < 5 && !globals.is_empty() {
            let g = *self.r.pick(&globals);
            self.emit(Instr::GlobalGet(g));
        } else {
            self.const_of(t);
        }
    }

    /// Wrap the float on top of the stack so NaNs become the canonical quiet NaN.
    fn canon(&mut self, t: ValType) {
        let (scratch, nan, ne) = match t {
            ValType::F32 => (self.scratch_f32, Instr::F32Const(0x7fc0_0000), 0x5C),
            _ => (self.scratch_f64, Instr::F64Const(0x7ff8_0000_0000_0000), 0x62),
        };
        self.emit(Instr::LocalSet(scratch));
        self.emit(nan);
        self.emit(Instr::LocalGet(scratch));
        self.emit(Instr::LocalGet(scratch));
        self.emit(Instr::LocalGet(scratch));
        self.emit(Instr::Num(ne));
        self.emit(Instr::Select);
    }

    fn address(&mut self, d: u32) {
        // mostly in-bounds addresses; sometimes wild ones to exercise bounds-check traps
        self.expr(ValType::I32, d.saturating_sub(1));
        let wild = self.r.chance(2);
        let mask = if wild { -1 } else { match self.r.below(20) {
            0..=17 => 0xFF,
            18 => 0xFFFF,
            _ => 0x7FFF,
        } };
        if mask != -1 {
            self.emit(Instr::I32Const(mask));
            self.emit(Instr::Num(0x71));
        }
    }

    fn mem_op_for(&mut self, t: ValType, store: bool) -> (u8, u32) {
        let c: Vec<_> = num::MEM_OPS.iter().filter(|m| m.2 == t && (num::is_store(m.0) == store)).collect();
        let m = c[self.r.below(c.len() as u64) as usize];
        (m.0, m.3)
    }

    fn memarg(&mut self, width: u32) -> (u32, u32) {
        let nat = width.trailing_zeros();
        let align = if self.r.chance(70) { nat } else { self.r.below(nat as u64 + 1) as u32 };
        let offset = if self.r.chance(60) { 0 } else { self.r.below(300) as u32 };
        (align, offset)
    }

    fn expr(&mut self, t: ValType, d: u32) {
        if d == 0 {
            return self.leaf(t);
        }
        let k = self.r.below(100);
        match k {
            0..=14 => self.leaf(t),
            15..=54 => self.numeric(t, d),
            55..=62 => {
                let (op, w) = self.mem_op_for(t, false);
                self.address(d);
                let (align, offset) = self.memarg(w);
                self.emit(Instr::Mem { op, align, offset });
                if matches!(t, ValType::F32 | ValType::F64) && self.r.chance(50) {
                    self.canon(t);
                }
            }
            63..=68 => {
                self.expr(t, d - 1);
                self.expr(t, d - 1);
                self.expr(ValType::I32, d - 1);
                self.emit(Instr::Select);
            }
            69..=74 => {
                self.expr(ValType::I32, d - 1);
                self.emit(Instr::If(BlockType::Val(t)));
                self.labels.push(Lbl { results: vec![t], is_loop: false });
                self.expr(t, d - 1);
                self.emit(Instr::Else);
                self.expr(t, d - 1);
                self.labels.pop();
                self.emit(Instr::End);
            }
            75..=80 => {
                // block with a value-carrying early exit
                self.emit(Instr::Block(BlockType::Val(t)));
                self.labels.push(Lbl { results: vec![t], is_loop: false });
                self.expr(t, d - 1);
                self.expr(ValType::I32, d - 1);
                self.emit(Instr::BrIf(0));
                self.emit(Instr::Drop);
                self.expr(t, d - 1);
                self.labels.pop();
                self.emit(Instr::End);
            }
            81..=85 => {
                let np = self.r.below(3) as usize;
                let params: Vec<ValType> = (0..np).map(|_| rand_type(self.r)).collect();
                self.block_with_sig(params, vec![t], d - 1);
            }
            86..=90 => self.call_expr(t, d),
            91..=93 => self.call_indirect_expr(t, d),
            94..=95 => {
                let (a, b) = (self.r.chance(50), t);
                if b == ValType::I32 {
                    if a {
                        self.emit(Instr::MemorySize);
                    } else {
                        self.expr(ValType::I32, d - 1);
                        self.emit(Instr::I32Const(1));
                        self.emit(Instr::Num(0x71));
                        self.emit(Instr::MemoryGrow);
                    }
                } else {
                    self.leaf(t)
                }
            }
            _ => {
                // local.tee
                let locals: Vec<u32> = self.pool.iter().copied().filter(|&i| self.locals[i as usize] == t).collect();
                if locals.is_empty() {
                    self.leaf(t)
                } else {
                    self.expr(t, d - 1);
                    let l = *self.r.pick(&locals);
                    self.emit(Instr::LocalTee(l));
                }
            }
        }
    }

    fn numeric(&mut self, t: ValType, d: u32) {
        let cands: Vec<&'static num::NumOp> = num::all().iter().filter(|o| o.result == t).collect();
        let mut op = *self.r.pick(&cands);
        // non-saturating truncations trap very often on random data; thin them out
        for _ in 0..2 {
            if op.name.contains("trunc_f") && !op.name.contains("sat") && self.r.chance(70) {
                op = *self.r.pick(&cands);
            }
        }
        let int_div = op.name.contains(".div_") && !op.name.starts_with('f') || op.name.contains(".rem_");
        for p in op.params {
            self.expr(*p, d - 1);
        }
        if int_div && self.r.chance(88) {
            // force a non-zero divisor most of the time so division-heavy code gets past it
            let (one, or) = if t == ValType::I32 { (Instr::I32Const(1), 0x72) } else { (Instr::I64Const(1), 0x84) };
            self.emit(one);
            self.emit(Instr::Num(or));
        }
        self.emit(Instr::Num(op.code));
        if matches!(t, ValType::F32 | ValType::F64) && !op.name.contains("reinterpret") {
            self.canon(t);
        }
    }

    fn values(&mut self, ts: &[ValType], d: u32) {
        if ts.len() >= 2 && d > 0 && self.r.chance(35) {
            return self.block_with_sig(vec![], ts.to_vec(), d - 1);
        }
        for t in ts {
            self.expr(*t, d);
        }
    }

    fn bt_for(&mut self, params: &[ValType], results: &[ValType]) -> BlockType {
        if params.is_empty() && results.is_empty() {
            BlockType::Empty
        } else if params.is_empty() && results.len() == 1 {
            BlockType::Val(results[0])
        } else {
            BlockType::Type(self.s.type_idx(&FuncType { params: params.to_vec(), results: results.to_vec() }))
        }
    }

    fn block_with_sig(&mut self, params: Vec<ValType>, results: Vec<ValType>, d: u32) {
        self.values(&params, d);
        let bt = self.bt_for(&params, &results);
        self.emit(Instr::Block(bt));
        self.labels.push(Lbl { results: results.clone(), is_loop: false });
        // stash block parameters into scratch locals (consumes them)
        let mut stash = vec![];
        let mut ok = true;
        for p in &params {
            match self.fresh_local(*p) {
                Some(l) => stash.push(l),
                None => ok = false,
            }
        }
        if !ok {
            // could not allocate; just drop the params (types still consume correctly)
            for _ in &params {
                self.emit(Instr::Drop);
            }
        } else {
            for l in stash.iter().rev() {
                self.emit(Instr::LocalSet(*l));
            }
            // make the stash readable by later code in this block only: add to pool
            for l in &stash {
                self.pool.push(*l);
            }
        }
        if d > 0 && self.r.chance(60) {
            self.stmt(d - 1);
        }
        self.values(&results, d);
        self.labels.pop();
        self.emit(Instr::End);
    }

    fn call_expr(&mut self, t: ValType, d: u32) {
        if self.in_loop > 0 || self.calls_left <= 0 {
            return self.leaf(t);
        }
        let cands: Vec<u32> = ((self.fidx + 1)..self.s.sigs.len() as u32).filter(|&j| self.s.sigs[j as usize].results.contains(&t)).collect();
        if cands.is_empty() {
            return self.leaf(t);
        }
        let j = *self.r.pick(&cands);
        let sig = self.s.sigs[j as usize].clone();
        // multi-result calls need scratch locals to pick one result out
        if sig.results.len() > 1 && self.new_locals + sig.results.len() as u32 > 60 {
            return self.leaf(t);
        }
        self.calls_left -= 1;
        self.values(&sig.params, d.saturating_sub(1));
        self.emit(Instr::Call(j));
        self.pick_result(&sig.results, t);
    }

    /// With `results` on the stack, leave exactly one value of type `t`.
    fn pick_result(&mut self, results: &[ValType], t: ValType) {
        if results.len() == 1 {
            return;
        }
        let mut slots = vec![];
        for r in results {
            slots.push(self.fresh_local(*r).unwrap());
        }
        for l in slots.iter().rev() {
            self.emit(Instr::LocalSet(*l));
        }
        let choices: Vec<usize> = (0..results.len()).filter(|&i| results[i] == t).collect();
        let c = *self.r.pick(&choices);
        self.emit(Instr::LocalGet(slots[c]));
    }

    fn call_indirect_expr(&mut self, t: ValType, d: u32) {
        if self.in_loop > 0 || self.calls_left <= 0 {
            return self.leaf(t);
        }
        // normal: a slot holding a later function whose result list contains t
        let normal: Vec<(u32, u32)> = self.s.table.iter().enumerate().filter_map(|(s, f)| f.map(|f| (s as u32, f))).filter(|&(_, f)| f > self.fidx && self.s.sigs[f as usize].results.contains(&t)).collect();
        let fail = self.r.chance(8);
        if !fail && normal.is_empty() {
            return self.leaf(t);
        }
        if !fail {
            let (slot, f) = *self.r.pick(&normal);
            let sig = self.s.sigs[f as usize].clone();
            if sig.results.len() > 1 && self.new_locals + sig.results.len() as u32 > 60 {
                return self.leaf(t);
            }
            self.calls_left -= 1;
            self.values(&sig.params, d.saturating_sub(1));
            self.emit(Instr::I32Const(slot as i32));
            let ti = self.s.type_idx(&sig);
            self.emit(Instr::CallIndirect(ti, 0));
            self.pick_result(&sig.results, t);
            return;
        }
        // failing variants: signature mismatch on a later function, empty slot, or out-of-range slot
        let ft = FuncType { params: vec![], results: vec![t] };
        let later: Vec<u32> = self.s.table.iter().enumerate().filter_map(|(s, f)| f.filter(|&f| f > self.fidx && self.s.sigs[f as usize] != ft).map(|_| s as u32)).collect();
        let empty: Vec<u32> = self.s.table.iter().enumerate().filter(|(_, f)| f.is_none()).map(|(s, _)| s as u32).collect();
        let slot = match self.r.below(3) {
            0 if !later.is_empty() => *self.r.pick(&later),
            1 if !empty.is_empty() => *self.r.pick(&empty),
            _ => self.s.table.len() as u32 + self.r.below(5) as u32,
        };
        self.calls_left -= 1;
        self.emit(Instr::I32Const(slot as i32));
        let ti = self.s.type_idx(&ft);
        self.emit(Instr::CallIndirect(ti, 0));
    }

    fn stmt(&mut self, d: u32) {
        let k = self.r.below(100);
        match k {
            0..=19 => {
                // local.set
                if self.pool.is_empty() {
                    return self.emit(Instr::Nop);
                }
                let l = *self.r.pick(&self.pool.clone());
                let t = self.locals[l as usize];
                self.expr(t, d);
                self.emit(Instr::LocalSet(l));
            }
            20..=29 => {
                let muts: Vec<u32> = (0..self.s.globals.len() as u32).filter(|&i| self.s.globals[i as usize].mutable).collect();
                let g = *self.r.pick(&muts);
                let t = self.s.globals[g as usize].ty;
                self.expr(t, d);
                self.emit(Instr::GlobalSet(g));
            }
            30..=44 => {
                let t = rand_type(self.r);
                let (op, w) = self.mem_op_for(t, true);
                self.address(d);
                self.expr(t, d.saturating_sub(1));
                let (align, offset) = self.memarg(w);
                self.emit(Instr::Mem { op, align, offset });
            }
            45..=49 => {
                let t = rand_type(self.r);
                self.expr(t, d);
                self.emit(Instr::Drop);
            }
            50..=58 if d > 0 => {
                self.expr(ValType::I32, d - 1);
                self.emit(Instr::If(BlockType::Empty));
                self.labels.push(Lbl { results: vec![], is_loop: false });
                let n = 1 + self.r.below(2) as u32;
                self.stmts(n, d - 1);
                if self.r.chance(50) {
                    self.emit(Instr::Else);
                    let n = 1 + self.r.below(2) as u32;
                self.stmts(n, d - 1);
                }
                self.labels.pop();
                self.emit(Instr::End);
            }
            59..=64 if d > 0 => {
                self.emit(Instr::Block(BlockType::Empty));
                self.labels.push(Lbl { results: vec![], is_loop: false });
                let n = 1 + self.r.below(3) as u32;
                self.stmts(n, d - 1);
                self.labels.pop();
                self.emit(Instr::End);
            }
            65..=71 if d > 0 && self.new_locals < 58 => self.counted_loop(d),
            72..=76 if d > 0 => self.switch(d),
            77..=82 => self.branch_stmt(d),
            83..=87 => {
                // call as a statement
                if self.in_loop > 0 || self.calls_left <= 0 || self.fidx + 1 >= self.s.sigs.len() as u32 {
                    return self.emit(Instr::Nop);
                }
                let j = self.fidx + 1 + self.r.below((self.s.sigs.len() as u32 - self.fidx - 1) as u64) as u32;
                let sig = self.s.sigs[j as usize].clone();
                self.calls_left -= 1;
                self.values(&sig.params, d.saturating_sub(1));
                self.emit(Instr::Call(j));
                for _ in &sig.results {
                    self.emit(Instr::Drop);
                }
            }
            88..=90 => {
                // bulk memory with small masked operands
                for _ in 0..2 {
                    self.address(d);
                }
                if matches!(self.r.below(2), 0) {
                    // fill: dest, value, len
                    self.expr(ValType::I32, d.saturating_sub(1));
                    self.emit(Instr::I32Const(0x3F));
                    self.emit(Instr::Num(0x71));
                    self.emit(Instr::MemoryFill);
                } else {
                    self.expr(ValType::I32, d.saturating_sub(1));
                    self.emit(Instr::I32Const(0x3F));
                    self.emit(Instr::Num(0x71));
                    self.emit(Instr::MemoryCopy);
                }
            }
            91 => {
                if self.r.chance(25) {
                    self.emit(Instr::Unreachable)
                } else {
                    self.emit(Instr::Nop)
                }
            }
            92..=93 => {
                // conditional trap-or-continue
                self.expr(ValType::I32, d.saturating_sub(1));
                self.emit(Instr::I32Const(31));
                self.emit(Instr::Num(0x71));
                self.emit(Instr::Num(0x45));
                self.emit(Instr::If(BlockType::Empty));
                self.emit(Instr::Unreachable);
                self.emit(Instr::End);
            }
            _ => self.emit(Instr::Nop),
        }
    }

    fn stmts(&mut self, n: u32, d: u32) {
        for _ in 0..n {
            self.stmt(d);
        }
    }

    fn counted_loop(&mut self, d: u32) {
        let c = self.fresh_local(ValType::I32).unwrap();
        let n = 1 + self.r.below(6) as i32;
        self.emit(Instr::I32Const(n));
        self.emit(Instr::LocalSet(c));
        self.emit(Instr::Loop(BlockType::Empty));
        self.labels.push(Lbl { results: vec![], is_loop: true });
        self.in_loop += 1;
        let n = 1 + self.r.below(3) as u32;
                self.stmts(n, d - 1);
        self.in_loop -= 1;
        self.emit(Instr::LocalGet(c));
        self.emit(Instr::I32Const(1));
        self.emit(Instr::Num(0x6B));
        self.emit(Instr::LocalTee(c));
        self.emit(Instr::BrIf(0));
        self.labels.pop();
        self.emit(Instr::End);
    }

    fn switch(&mut self, d: u32) {
        let n = 2 + self.r.below(3) as usize;
        for _ in 0..n {
            self.emit(Instr::Block(BlockType::Empty));
            self.labels.push(Lbl { results: vec![], is_loop: false });
        }
        self.expr(ValType::I32, d - 1);
        let k = 1 + self.r.below(n as u64) as usize;
        let targets: Vec<u32> = (0..k).map(|_| self.r.below(n as u64) as u32).collect();
        let default = self.r.below(n as u64) as u32;
        self.emit(Instr::BrTable(targets, default));
        for _ in 0..n {
            self.labels.pop();
            self.emit(Instr::End);
            self.stmts(1, d - 1);
        }
    }

    fn branch_stmt(&mut self, d: u32) {
        // pick a non-loop label (index 0 is the function body itself, i.e. `return`)
        let idxs: Vec<usize> = (0..self.labels.len()).filter(|&i| !self.labels[i].is_loop).collect();
        if idxs.is_empty() {
            return self.emit(Instr::Nop);
        }
        let i = *self.r.pick(&idxs);
        let depth = (self.labels.len() - 1 - i) as u32;
        let results = self.labels[i].results.clone();
        if self.r.chance(30) {
            // unconditional (rest of the enclosing block is dead but still type-checks)
            self.values(&results, d.saturating_sub(1));
            if i == 0 && self.r.chance(50) {
                self.emit(Instr::Return);
            } else {
                self.emit(Instr::Br(depth));
            }
        } else {
            self.values(&results, d.saturating_sub(1));
            self.expr(ValType::I32, d.saturating_sub(1));
            self.emit(Instr::BrIf(depth));
            for _ in &results {
                self.emit(Instr::Drop);
            }
        }
    }
}

pub struct CallSpec {
    pub export: String,
    pub args: Vec<Value>,
}

pub struct Case {
    pub module: Module,
    pub calls: Vec<CallSpec>,
}

pub fn generate(seed: u64) -> Case {
    let mut r = Rng(seed ^ 0xA5A5_5A5A_1234_5678);
    r.next();
    let nfuncs = 3 + r.below(6) as usize;
    let sigs: Vec<FuncType> = (0..nfuncs)
        .map(|i| {
            let np = r.below(4) as usize;
            let nr = if i == 0 || r.chance(75) { r.below(2) as usize } else { 2 + r.below(2) as usize };
            FuncType { params: (0..np).map(|_| rand_type(&mut r)).collect(), results: (0..nr).map(|_| rand_type(&mut r)).collect() }
        })
        .collect();
    // table: every function may sit in a random slot; some slots stay empty
    let tsize = nfuncs + 2;
    let mut table: Vec<Option<u32>> = vec![None; tsize];
    for f in 0..nfuncs {
        if r.chance(75) {
            let s = r.below(tsize as u64) as usize;
            if table[s].is_none() {
                table[s] = Some(f as u32);
            }
        }
    }
    // globals: one mutable of each type + one immutable
    let mut globals: Vec<GlobalType> = [ValType::I32, ValType::I64, ValType::F32, ValType::F64].iter().map(|&ty| GlobalType { ty, mutable: true }).collect();
    globals.push(GlobalType { ty: rand_type(&mut r), mutable: true });
    globals.push(GlobalType { ty: rand_type(&mut r), mutable: false });

    let mut shared = Shared { types: vec![], sigs: sigs.clone(), globals: globals.clone(), table: table.clone() };
    for s in &sigs {
        shared.type_idx(s);
    }
    let mut m = Module::default();
    let mut codes = vec![];
    for (fi, sig) in sigs.iter().enumerate() {
        let mut locals: Vec<ValType> = sig.params.clone();
        let nextra = r.below(4) as usize;
        for _ in 0..nextra {
            locals.push(rand_type(&mut r));
        }
        let scratch_f32 = locals.len() as u32;
        locals.push(ValType::F32);
        let scratch_f64 = locals.len() as u32;
        locals.push(ValType::F64);
        let pool: Vec<u32> = (0..(sig.params.len() + nextra) as u32).collect();
        let mut g = FnGen {
            r: &mut r,
            s: &mut shared,
            fidx: fi as u32,
            results: sig.results.clone(),
            locals,
            pool,
            nparams: sig.params.len(),
            scratch_f32,
            scratch_f64,
            labels: vec![Lbl { results: sig.results.clone(), is_loop: false }],
            in_loop: 0,
            calls_left: 3,
            out: vec![],
            new_locals: 0,
        };
        let depth = 2 + g.r.below(3) as u32;
        let nstmts = 3 + g.r.below(6) as u32;
        g.stmts(nstmts, depth);
        let results = g.results.clone();
        g.values(&results, depth);
        g.out.push(Instr::End);
        let np = g.nparams;
        codes.push(Code { locals: g.locals[np..].to_vec(), body: g.out });
    }
    m.types = shared.types.clone();
    m.funcs = sigs.iter().map(|s| shared.types.iter().position(|t| t == s).unwrap() as u32).collect();
    m.codes = codes;
    m.tables = vec![Limits { min: tsize as u32, max: Some(tsize as u32) }];
    m.mems = vec![Limits { min: 1, max: Some(4) }];
    m.globals = globals
        .iter()
        .map(|g| {
            let v = rand_value(&mut r, g.ty);
            let i = match v {
                Value::I32(x) => Instr::I32Const(x),
                Value::I64(x) => Instr::I64Const(x),
                Value::F32(x) => Instr::F32Const(x.to_bits()),
                Value::F64(x) => Instr::F64Const(x.to_bits()),
            };
            Global { ty: *g, init: vec![i, Instr::End] }
        })
        .collect();
    for i in 0..nfuncs {
        m.exports.push(Export { name: format!("f{i}"), kind: ExportKind::Func, index: i as u32 });
    }
    for i in 0..globals.len() {
        m.exports.push(Export { name: format!("g{i}"), kind: ExportKind::Global, index: i as u32 });
    }
    m.exports.push(Export { name: "mem".into(), kind: ExportKind::Mem, index: 0 });
    for (slot, f) in table.iter().enumerate() {
        if let Some(f) = f {
            m.elems.push(Elem { table: 0, offset: vec![Instr::I32Const(slot as i32), Instr::End], funcs: vec![*f] });
        }
    }
    let mut bytes = vec![];
    for _ in 0..(32 + r.below(64)) {
        bytes.push(if r.chance(30) { 0xFF } else { r.next() as u8 });
    }
    // sprinkle recognisable floats
    bytes.extend_from_slice(&1.5f64.to_le_bytes());
    bytes.extend_from_slice(&(-2.25f32).to_le_bytes());
    m.datas.push(Data { mem: 0, offset: vec![Instr::I32Const(r.below(128) as i32), Instr::End], bytes });

    let mut calls = vec![];
    for (i, sig) in sigs.iter().enumerate() {
        for _ in 0..3 {
            let args = sig.params.iter().map(|t| rand_value(&mut r, *t)).collect();
            calls.push(CallSpec { export: format!("f{i}"), args });
        }
    }
    Case { module: m, calls }
}

pub fn fnv32(data: &[u8]) -> u32 {
    let mut h: u32 = 2166136261;
    for &b in data {
        h ^= b as u32;
        h = h.wrapping_mul(16777619);
    }
    h
}

/// Canonical text for a value, shared with the JS harness.
pub fn enc(v: &Value) -> String {
    match v {
        Value::I32(x) => format!("i32:{x}"),
        Value::I64(x) => format!("i64:{x}"),
        Value::F32(x) => {
            if x.is_nan() { "f32:nan".into() } else { format!("f32:{:08x}", x.to_bits()) }
        }
        Value::F64(x) => {
            if x.is_nan() { "f64:nan".into() } else { format!("f64:{:016x}", x.to_bits()) }
        }
    }
}

fn jstr(s: &str) -> String {
    format!("\"{}\"", s.replace('\\', "\\\\").replace('"', "\\\""))
}

/// Execute a case in Wick and describe the outcome as JSON (consumed by diff/diff.js).
pub fn run_case_json(seed: u64, case: &Case) -> String {
    let mut inst = match Instance::new(case.module.clone(), Imports::default()) {
        Ok(i) => i,
        Err(e) => return format!("{{\"seed\":{seed},\"skip\":{}}}", jstr(&format!("instantiate: {e}"))),
    };
    inst.fuel = 300_000_000;
    let mut o = String::new();
    write!(o, "{{\"seed\":{seed},\"skip\":null,\"calls\":[").unwrap();
    for (i, c) in case.calls.iter().enumerate() {
        if i > 0 {
            o.push(',');
        }
        let args: Vec<String> = c.args.iter().map(|a| jstr(&enc(a))).collect();
        write!(o, "{{\"fn\":{},\"args\":[{}],", jstr(&c.export), args.join(",")).unwrap();
        match inst.invoke(&c.export, &c.args) {
            Ok(vs) => {
                let r: Vec<String> = vs.iter().map(|v| jstr(&enc(v))).collect();
                write!(o, "\"ret\":[{}]", r.join(",")).unwrap();
            }
            Err(crate::interp::InvokeError::Trap(Trap::OutOfFuel)) => {
                return format!("{{\"seed\":{seed},\"skip\":\"out of fuel\"}}");
            }
            Err(crate::interp::InvokeError::Trap(t)) => {
                write!(o, "\"trap\":{}", jstr(t.category())).unwrap();
            }
            Err(e) => return format!("{{\"seed\":{seed},\"skip\":{}}}", jstr(&e.to_string())),
        }
        o.push('}');
    }
    let mem = inst.memory.as_ref().unwrap();
    let globals: Vec<String> = inst.globals.iter().map(|(gt, raw)| jstr(&enc(&Value::from_raw(gt.ty, *raw)))).collect();
    write!(o, "],\"pages\":{},\"hash\":{},\"globals\":[{}]}}", mem.pages(), fnv32(&mem.data), globals.join(",")).unwrap();
    o
}

// ---------------------------------------------------------------------------------------------
// AST-level mutation: produce *almost valid* modules to stress the validator's type checking.

fn random_instr(r: &mut Rng, nlocals: u32, nfuncs: u32, nglobals: u32) -> Instr {
    let all = num::all();
    match r.below(22) {
        0 => Instr::Nop,
        1 => Instr::Drop,
        2 => Instr::Select,
        3 => Instr::I32Const(r.next() as i32),
        4 => Instr::I64Const(r.next() as i64),
        5 => Instr::F32Const(r.next() as u32),
        6 => Instr::F64Const(r.next()),
        7 => Instr::LocalGet(r.below(nlocals as u64 + 2) as u32),
        8 => Instr::LocalSet(r.below(nlocals as u64 + 2) as u32),
        9 => Instr::LocalTee(r.below(nlocals as u64 + 2) as u32),
        10 => Instr::GlobalGet(r.below(nglobals as u64 + 1) as u32),
        11 => Instr::GlobalSet(r.below(nglobals as u64 + 1) as u32),
        12 => Instr::Br(r.below(4) as u32),
        13 => Instr::BrIf(r.below(4) as u32),
        14 => Instr::Return,
        15 => Instr::Call(r.below(nfuncs as u64 + 1) as u32),
        16 | 17 => Instr::Num(all[r.below(all.len() as u64) as usize].code),
        18 => {
            let m = num::MEM_OPS[r.below(num::MEM_OPS.len() as u64) as usize];
            Instr::Mem { op: m.0, align: r.below(4) as u32, offset: r.below(16) as u32 }
        }
        19 => match r.below(4) {
            0 => Instr::End,
            1 => Instr::Else,
            2 => Instr::Block(BlockType::Empty),
            _ => Instr::If(BlockType::Val(rand_type(r))),
        },
        20 => Instr::BrTable(vec![r.below(3) as u32, r.below(3) as u32], r.below(3) as u32),
        _ => Instr::Unreachable,
    }
}

pub fn mutate_module(m: &Module, r: &mut Rng) -> Module {
    let mut m = m.clone();
    let rounds = 1 + r.below(2);
    for _ in 0..rounds {
        let which = r.below(100);
        if which < 85 && !m.codes.is_empty() {
            let fi = r.below(m.codes.len() as u64) as usize;
            let nfuncs = (m.num_imported_funcs() + m.funcs.len()) as u32;
            let nglobals = m.all_globals().len() as u32;
            let nparams = m.types[m.funcs[fi] as usize].params.len() as u32;
            let code = &mut m.codes[fi];
            let nlocals = nparams + code.locals.len() as u32;
            if code.body.is_empty() {
                continue;
            }
            let pos = r.below(code.body.len() as u64) as usize;
            match r.below(8) {
                0 => {
                    code.body.remove(pos);
                }
                1 => {
                    let i = code.body[pos].clone();
                    code.body.insert(pos, i);
                }
                2 if pos + 1 < code.body.len() => code.body.swap(pos, pos + 1),
                3 | 4 => code.body[pos] = random_instr(r, nlocals, nfuncs, nglobals),
                5 => {
                    let i = random_instr(r, nlocals, nfuncs, nglobals);
                    code.body.insert(pos, i)
                }
                6 => {
                    // tweak an immediate
                    code.body[pos] = match &code.body[pos] {
                        Instr::LocalGet(x) => Instr::LocalGet(x + 1),
                        Instr::LocalSet(x) => Instr::LocalSet(x.saturating_sub(1)),
                        Instr::Br(x) => Instr::Br(x + 1),
                        Instr::BrIf(x) => Instr::BrIf(x + 1),
                        Instr::Block(_) => Instr::Block(BlockType::Val(rand_type(r))),
                        Instr::If(_) => Instr::If(BlockType::Val(rand_type(r))),
                        Instr::Loop(_) => Instr::Loop(BlockType::Val(rand_type(r))),
                        Instr::I32Const(v) => Instr::I64Const(*v as i64),
                        Instr::Call(f) => Instr::Call(f + 1),
                        other => other.clone(),
                    };
                }
                _ => {
                    // change the function's locals
                    if !code.locals.is_empty() {
                        let k = r.below(code.locals.len() as u64) as usize;
                        code.locals[k] = rand_type(r);
                    }
                }
            }
        } else if which < 90 && !m.funcs.is_empty() {
            let i = r.below(m.funcs.len() as u64) as usize;
            m.funcs[i] = r.below(m.types.len() as u64) as u32;
        } else if which < 94 && !m.globals.is_empty() {
            let i = r.below(m.globals.len() as u64) as usize;
            if r.chance(50) {
                m.globals[i].ty.mutable = !m.globals[i].ty.mutable;
            } else {
                m.globals[i].ty.ty = rand_type(r);
            }
        } else if which < 97 && !m.elems.is_empty() {
            let i = r.below(m.elems.len() as u64) as usize;
            m.elems[i].funcs[0] = r.below(m.funcs.len() as u64 + 2) as u32;
        } else if !m.exports.is_empty() {
            let i = r.below(m.exports.len() as u64) as usize;
            m.exports[i].index += r.below(3) as u32;
        }
    }
    m
}
