//! Instantiation and execution.
use crate::ast::*;
use crate::num;
use crate::trace::Profile;
use crate::trap::Trap;
use crate::validate::{validate, ValidationError};
use std::collections::HashMap;

pub const PAGE: usize = 65536;
/// Hard cap on memory growth (pages) regardless of declared maximum: 512 MiB.
pub const MEM_CAP_PAGES: u32 = 8192;
pub const MAX_CALL_DEPTH: usize = 10_000;

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Value {
    I32(i32),
    I64(i64),
    F32(f32),
    F64(f64),
}

impl Value {
    pub fn ty(&self) -> ValType {
        match self {
            Value::I32(_) => ValType::I32,
            Value::I64(_) => ValType::I64,
            Value::F32(_) => ValType::F32,
            Value::F64(_) => ValType::F64,
        }
    }
    pub fn to_raw(self) -> u64 {
        match self {
            Value::I32(v) => v as u32 as u64,
            Value::I64(v) => v as u64,
            Value::F32(v) => v.to_bits() as u64,
            Value::F64(v) => v.to_bits(),
        }
    }
    pub fn from_raw(t: ValType, r: u64) -> Value {
        match t {
            ValType::I32 => Value::I32(r as u32 as i32),
            ValType::I64 => Value::I64(r as i64),
            ValType::F32 => Value::F32(f32::from_bits(r as u32)),
            ValType::F64 => Value::F64(f64::from_bits(r)),
        }
    }
    pub fn zero(t: ValType) -> Value {
        Value::from_raw(t, 0)
    }
    /// Parse a command-line argument for the given type. Accepts decimal/hex ints,
    /// floats, `inf`, `-inf`, `nan`, and `bits:0x...` for exact float bit patterns.
    pub fn parse(t: ValType, s: &str) -> Result<Value, String> {
        let bad = || format!("cannot parse `{s}` as {}", t.name());
        if let Some(h) = s.strip_prefix("bits:") {
            let h = h.trim_start_matches("0x");
            let b = u64::from_str_radix(h, 16).map_err(|_| bad())?;
            return Ok(match t {
                ValType::F32 => Value::F32(f32::from_bits(b as u32)),
                ValType::F64 => Value::F64(f64::from_bits(b)),
                _ => return Err(bad()),
            });
        }
        match t {
            ValType::I32 => crate::wat::parse_int(s, 32).map(|v| Value::I32(v as i32)).ok_or_else(bad),
            ValType::I64 => crate::wat::parse_int(s, 64).map(|v| Value::I64(v as i64)).ok_or_else(bad),
            ValType::F32 => crate::wat::parse_float(s, true).map(|b| Value::F32(f32::from_bits(b as u32))).ok_or_else(bad),
            ValType::F64 => crate::wat::parse_float(s, false).map(|b| Value::F64(f64::from_bits(b))).ok_or_else(bad),
        }
    }
}

impl std::fmt::Display for Value {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            Value::I32(v) => write!(f, "i32:{v}"),
            Value::I64(v) => write!(f, "i64:{v}"),
            Value::F32(v) => write!(f, "f32:{}", fmt_float(*v as f64, v.is_nan())),
            Value::F64(v) => write!(f, "f64:{}", fmt_float(*v, v.is_nan())),
        }
    }
}
fn fmt_float(v: f64, nan: bool) -> String {
    if nan {
        "nan".into()
    } else if v == 0.0 && v.is_sign_negative() {
        "-0".into()
    } else if v.is_infinite() {
        if v > 0.0 { "inf".into() } else { "-inf".into() }
    } else {
        format!("{v}")
    }
}

pub struct HostFunc {
    pub ty: FuncType,
    pub f: Box<dyn FnMut(&[Value]) -> Result<Vec<Value>, Trap>>,
}

pub struct Memory {
    pub data: Vec<u8>,
    pub max: Option<u32>,
}
impl Memory {
    pub fn new(min: u32, max: Option<u32>) -> Memory {
        Memory { data: vec![0; min as usize * PAGE], max }
    }
    pub fn pages(&self) -> u32 {
        (self.data.len() / PAGE) as u32
    }
    /// Returns the old size in pages, or None if growth is refused.
    pub fn grow(&mut self, delta: u32) -> Option<u32> {
        let old = self.pages();
        let new = old as u64 + delta as u64;
        let limit = self.max.unwrap_or(65536).min(65536).min(MEM_CAP_PAGES) as u64;
        if new > limit {
            return None;
        }
        self.data.resize(new as usize * PAGE, 0);
        Some(old)
    }
}

pub struct Table {
    pub elems: Vec<Option<u32>>,
    pub max: Option<u32>,
}

#[derive(Default)]
pub struct Imports {
    pub funcs: HashMap<(String, String), HostFunc>,
    pub globals: HashMap<(String, String), Value>,
    pub memories: HashMap<(String, String), Memory>,
    pub tables: HashMap<(String, String), Table>,
}

impl Imports {
    pub fn func(&mut self, module: &str, name: &str, params: &[ValType], results: &[ValType], f: impl FnMut(&[Value]) -> Result<Vec<Value>, Trap> + 'static) {
        self.funcs.insert((module.into(), name.into()), HostFunc { ty: FuncType::new(params, results), f: Box::new(f) });
    }
}

#[derive(Debug)]
pub enum InstanceError {
    Invalid(ValidationError),
    Link(String),
    Trap(Trap),
}
impl std::fmt::Display for InstanceError {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            InstanceError::Invalid(e) => write!(f, "{e}"),
            InstanceError::Link(s) => write!(f, "link error: {s}"),
            InstanceError::Trap(t) => write!(f, "trap during instantiation: {t}"),
        }
    }
}
impl std::error::Error for InstanceError {}

#[derive(Debug)]
pub enum InvokeError {
    NoExport(String),
    NotFunc(String),
    BadArgs(String),
    Trap(Trap),
}
impl std::fmt::Display for InvokeError {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            InvokeError::NoExport(n) => write!(f, "no export named `{n}`"),
            InvokeError::NotFunc(n) => write!(f, "export `{n}` is not a function"),
            InvokeError::BadArgs(s) => write!(f, "bad arguments: {s}"),
            InvokeError::Trap(t) => write!(f, "trap: {t}"),
        }
    }
}
impl std::error::Error for InvokeError {}

/// Per-defined-function precomputed control-flow side tables.
struct Compiled {
    /// For Block/Loop/If/Else: index of the matching End.
    end_of: Vec<u32>,
    /// For If: index of its Else, or u32::MAX.
    else_of: Vec<u32>,
    nparams: usize,
    nlocals: usize,
    nresults: usize,
}

fn compile(m: &Module, def_idx: usize) -> Compiled {
    let code = &m.codes[def_idx];
    let ft = &m.types[m.funcs[def_idx] as usize];
    let n = code.body.len();
    let mut end_of = vec![u32::MAX; n];
    let mut else_of = vec![u32::MAX; n];
    let mut stack: Vec<usize> = vec![];
    for (i, ins) in code.body.iter().enumerate() {
        match ins {
            Instr::Block(_) | Instr::Loop(_) | Instr::If(_) => stack.push(i),
            Instr::Else => {
                let open = *stack.last().unwrap();
                else_of[open] = i as u32;
                end_of[i] = open as u32; // temporarily remember the owning `if`
            }
            Instr::End => {
                if let Some(open) = stack.pop() {
                    end_of[open] = i as u32;
                    let e = else_of[open];
                    if e != u32::MAX {
                        end_of[e as usize] = i as u32;
                    }
                }
            }
            _ => {}
        }
    }
    Compiled { end_of, else_of, nparams: ft.params.len(), nlocals: ft.params.len() + code.locals.len(), nresults: ft.results.len() }
}

#[derive(Clone, Copy)]
struct Label {
    cont: u32,
    arity: u32,
    height: u32,
    is_loop: bool,
}

struct Frame {
    func: u32, // index in the whole function space
    pc: usize,
    base: usize,
    label_base: usize,
}

pub struct Instance {
    pub module: Module,
    compiled: Vec<Compiled>,
    hosts: Vec<HostFunc>,
    n_imp: usize,
    pub memory: Option<Memory>,
    pub table: Option<Table>,
    pub globals: Vec<(GlobalType, u64)>,
    stack: Vec<u64>,
    labels: Vec<Label>,
    /// Remaining instruction budget; `u64::MAX` = unlimited.
    pub fuel: u64,
    pub profile: Option<Box<Profile>>,
}

fn eval_const(e: &[Instr], globals: &[(GlobalType, u64)]) -> u64 {
    match &e[0] {
        Instr::I32Const(v) => *v as u32 as u64,
        Instr::I64Const(v) => *v as u64,
        Instr::F32Const(b) => *b as u64,
        Instr::F64Const(b) => *b,
        Instr::GlobalGet(g) => globals[*g as usize].1,
        _ => unreachable!("validated constant expression"),
    }
}

impl Instance {
    pub fn new(module: Module, mut imports: Imports) -> Result<Instance, InstanceError> {
        validate(&module).map_err(InstanceError::Invalid)?;
        let mut hosts = vec![];
        let mut globals: Vec<(GlobalType, u64)> = vec![];
        let mut memory: Option<Memory> = None;
        let mut table: Option<Table> = None;
        for imp in &module.imports {
            let key = (imp.module.clone(), imp.name.clone());
            let what = format!("{}.{}", imp.module, imp.name);
            match &imp.desc {
                ImportDesc::Func(t) => {
                    let h = imports.funcs.remove(&key).ok_or_else(|| InstanceError::Link(format!("missing function import `{what}`")))?;
                    if h.ty != module.types[*t as usize] {
                        return Err(InstanceError::Link(format!("import `{what}` has the wrong signature")));
                    }
                    hosts.push(h);
                }
                ImportDesc::Global(gt) => {
                    let v = imports.globals.remove(&key).ok_or_else(|| InstanceError::Link(format!("missing global import `{what}`")))?;
                    if v.ty() != gt.ty {
                        return Err(InstanceError::Link(format!("global import `{what}` has the wrong type")));
                    }
                    if gt.mutable {
                        return Err(InstanceError::Link(format!("mutable global import `{what}` is not supported")));
                    }
                    globals.push((*gt, v.to_raw()));
                }
                ImportDesc::Mem(l) => {
                    let m = imports.memories.remove(&key).ok_or_else(|| InstanceError::Link(format!("missing memory import `{what}`")))?;
                    if m.pages() < l.min || (l.max.is_some() && (m.max.is_none() || m.max.unwrap() > l.max.unwrap())) {
                        return Err(InstanceError::Link(format!("memory import `{what}` does not satisfy declared limits")));
                    }
                    memory = Some(m);
                }
                ImportDesc::Table(l) => {
                    let t = imports.tables.remove(&key).ok_or_else(|| InstanceError::Link(format!("missing table import `{what}`")))?;
                    if (t.elems.len() as u32) < l.min || (l.max.is_some() && (t.max.is_none() || t.max.unwrap() > l.max.unwrap())) {
                        return Err(InstanceError::Link(format!("table import `{what}` does not satisfy declared limits")));
                    }
                    table = Some(t);
                }
            }
        }
        if let Some(l) = module.mems.first() {
            memory = Some(Memory::new(l.min, l.max));
        }
        if let Some(l) = module.tables.first() {
            table = Some(Table { elems: vec![None; l.min as usize], max: l.max });
        }
        for g in &module.globals {
            let v = eval_const(&g.init, &globals);
            globals.push((g.ty, v));
        }
        // Active segments are applied in order; the first out-of-bounds one traps.
        for e in &module.elems {
            let off = eval_const(&e.offset, &globals) as u32 as usize;
            let t = table.as_mut().unwrap();
            if off.checked_add(e.funcs.len()).map_or(true, |end| end > t.elems.len()) {
                return Err(InstanceError::Trap(Trap::TableOob));
            }
            for (i, f) in e.funcs.iter().enumerate() {
                t.elems[off + i] = Some(*f);
            }
        }
        for d in &module.datas {
            let off = eval_const(&d.offset, &globals) as u32 as usize;
            let mem = memory.as_mut().unwrap();
            if off.checked_add(d.bytes.len()).map_or(true, |end| end > mem.data.len()) {
                return Err(InstanceError::Trap(Trap::MemoryOob));
            }
            mem.data[off..off + d.bytes.len()].copy_from_slice(&d.bytes);
        }
        let compiled = (0..module.codes.len()).map(|i| compile(&module, i)).collect();
        let n_imp = hosts.len();
        let mut inst = Instance { module, compiled, hosts, n_imp, memory, table, globals, stack: vec![], labels: vec![], fuel: u64::MAX, profile: None };
        if let Some(s) = inst.module.start {
            inst.call_index(s, &[]).map_err(InstanceError::Trap)?;
        }
        Ok(inst)
    }

    pub fn export_func_type(&self, name: &str) -> Result<FuncType, InvokeError> {
        let e = self.module.export(name).ok_or_else(|| InvokeError::NoExport(name.into()))?;
        if e.kind != ExportKind::Func {
            return Err(InvokeError::NotFunc(name.into()));
        }
        let t = self.module.all_func_types()[e.index as usize];
        Ok(self.module.types[t as usize].clone())
    }

    pub fn invoke(&mut self, name: &str, args: &[Value]) -> Result<Vec<Value>, InvokeError> {
        let ft = self.export_func_type(name)?;
        let idx = self.module.export(name).unwrap().index;
        if args.len() != ft.params.len() {
            return Err(InvokeError::BadArgs(format!("`{name}` takes {} argument(s), got {}", ft.params.len(), args.len())));
        }
        for (i, (a, p)) in args.iter().zip(&ft.params).enumerate() {
            if a.ty() != *p {
                return Err(InvokeError::BadArgs(format!("argument {i} of `{name}` must be {}, got {}", p.name(), a.ty().name())));
            }
        }
        self.call_index(idx, args).map_err(InvokeError::Trap)
    }

    pub fn get_global(&self, name: &str) -> Option<Value> {
        let e = self.module.export(name)?;
        if e.kind != ExportKind::Global {
            return None;
        }
        let (gt, raw) = self.globals[e.index as usize];
        Some(Value::from_raw(gt.ty, raw))
    }

    fn call_index(&mut self, fidx: u32, args: &[Value]) -> Result<Vec<Value>, Trap> {
        self.stack.clear();
        self.labels.clear();
        let t = self.module.all_func_types()[fidx as usize];
        let ft = self.module.types[t as usize].clone();
        if (fidx as usize) < self.n_imp {
            let r = (self.hosts[fidx as usize].f)(args)?;
            return Ok(r);
        }
        for a in args {
            self.stack.push(a.to_raw());
        }
        self.execute(fidx)?;
        let n = ft.results.len();
        let start = self.stack.len() - n;
        let out = ft.results.iter().enumerate().map(|(i, t)| Value::from_raw(*t, self.stack[start + i])).collect();
        self.stack.clear();
        Ok(out)
    }

    /// Run function `entry` (arguments already on the value stack) to completion.
    fn execute(&mut self, entry: u32) -> Result<(), Trap> {
        let Instance { module, compiled, hosts, n_imp, memory, table, globals, stack, labels, fuel, profile } = self;
        let n_imp = *n_imp;
        let func_types = module.all_func_types();
        let mut frames: Vec<Frame> = Vec::new();

        macro_rules! enter {
            ($f:expr) => {{
                let f: u32 = $f;
                if frames.len() >= MAX_CALL_DEPTH {
                    return Err(Trap::StackExhausted);
                }
                let c = &compiled[f as usize - n_imp];
                let base = stack.len() - c.nparams;
                let ft = &module.types[func_types[f as usize] as usize];
                let code = &module.codes[f as usize - n_imp];
                for _ in c.nparams..c.nlocals {
                    stack.push(0);
                }
                let _ = ft;
                let _ = code;
                let label_base = labels.len();
                labels.push(Label { cont: module.codes[f as usize - n_imp].body.len() as u32, arity: c.nresults as u32, height: stack.len() as u32, is_loop: false });
                Frame { func: f, pc: 0, base, label_base }
            }};
        }

        let mut cur = enter!(entry);
        if let Some(p) = profile.as_deref_mut() {
            p.on_call(None, entry, false, 1);
        }
        let mut code: &[Instr] = &module.codes[entry as usize - n_imp].body;

        macro_rules! trap {
            ($e:expr) => {
                return Err($e)
            };
        }
        macro_rules! ea {
            ($offset:expr, $width:expr) => {{
                let addr = num::pop_i32(stack) as u32 as u64;
                let ea = addr + $offset as u64;
                let mem = memory.as_mut().unwrap();
                if ea + $width as u64 > mem.data.len() as u64 {
                    trap!(Trap::MemoryOob);
                }
                ea as usize
            }};
        }

        loop {
            if cur.pc >= code.len() {
                // Function return: results are the top `nresults` slots.
                let c = &compiled[cur.func as usize - n_imp];
                let src = stack.len() - c.nresults;
                if src != cur.base {
                    stack.copy_within(src.., cur.base);
                }
                stack.truncate(cur.base + c.nresults);
                labels.truncate(cur.label_base);
                match frames.pop() {
                    None => return Ok(()),
                    Some(f) => {
                        cur = f;
                        code = &module.codes[cur.func as usize - n_imp].body;
                        continue;
                    }
                }
            }
            if *fuel == 0 {
                trap!(Trap::OutOfFuel);
            }
            *fuel -= 1;
            let pc = cur.pc;
            let ins = &code[pc];
            cur.pc += 1;
            if let Some(p) = profile.as_deref_mut() {
                p.on_instr(cur.func, pc, ins, frames.len() + 1, stack.len());
            }
            match ins {
                Instr::Unreachable => trap!(Trap::Unreachable),
                Instr::Nop => {}
                Instr::Block(bt) | Instr::Loop(bt) => {
                    let (np, nr) = bt_arity(module, bt);
                    let is_loop = matches!(ins, Instr::Loop(_));
                    let c = &compiled[cur.func as usize - n_imp];
                    let cont = if is_loop { pc as u32 + 1 } else { c.end_of[pc] + 1 };
                    labels.push(Label { cont, arity: if is_loop { np } else { nr } as u32, height: (stack.len() - np) as u32, is_loop });
                }
                Instr::If(bt) => {
                    let cond = num::pop_i32(stack);
                    let (np, nr) = bt_arity(module, bt);
                    let c = &compiled[cur.func as usize - n_imp];
                    let end = c.end_of[pc];
                    labels.push(Label { cont: end + 1, arity: nr as u32, height: (stack.len() - np) as u32, is_loop: false });
                    if cond == 0 {
                        let e = c.else_of[pc];
                        cur.pc = if e != u32::MAX { e as usize + 1 } else { end as usize };
                    }
                }
                Instr::Else => {
                    // Reached by falling out of the then-branch: skip to the End (which pops the label).
                    let c = &compiled[cur.func as usize - n_imp];
                    cur.pc = c.end_of[pc] as usize;
                }
                Instr::End => {
                    labels.pop();
                }
                Instr::Br(_) | Instr::BrIf(_) | Instr::BrTable(_, _) => {
                    let depth = match ins {
                        Instr::Br(d) => *d,
                        Instr::BrIf(d) => {
                            if num::pop_i32(stack) == 0 {
                                continue;
                            }
                            *d
                        }
                        Instr::BrTable(ls, d) => {
                            let i = num::pop_i32(stack) as u32 as usize;
                            if i < ls.len() { ls[i] } else { *d }
                        }
                        _ => unreachable!(),
                    };
                    let li = labels.len() - 1 - depth as usize;
                    let l = labels[li];
                    let arity = l.arity as usize;
                    let src = stack.len() - arity;
                    if src != l.height as usize {
                        stack.copy_within(src.., l.height as usize);
                    }
                    stack.truncate(l.height as usize + arity);
                    labels.truncate(if l.is_loop { li + 1 } else { li });
                    cur.pc = l.cont as usize;
                }
                Instr::Return => {
                    cur.pc = code.len();
                }
                Instr::Call(_) | Instr::CallIndirect(_, _) => {
                    let target = match ins {
                        Instr::Call(f) => *f,
                        Instr::CallIndirect(t, _) => {
                            let i = num::pop_i32(stack) as u32 as usize;
                            let tab = table.as_ref().unwrap();
                            match tab.elems.get(i) {
                                None => trap!(Trap::TableOob),
                                Some(None) => trap!(Trap::UninitializedElement),
                                Some(Some(f)) => {
                                    if module.types[func_types[*f as usize] as usize] != module.types[*t as usize] {
                                        trap!(Trap::IndirectCallTypeMismatch);
                                    }
                                    *f
                                }
                            }
                        }
                        _ => unreachable!(),
                    };
                    if (target as usize) < n_imp {
                        let ft = &module.types[func_types[target as usize] as usize];
                        let np = ft.params.len();
                        let at = stack.len() - np;
                        let args: Vec<Value> = ft.params.iter().enumerate().map(|(i, t)| Value::from_raw(*t, stack[at + i])).collect();
                        stack.truncate(at);
                        if let Some(p) = profile.as_deref_mut() {
                            p.on_call(Some(cur.func), target, true, frames.len() + 1);
                        }
                        let res = (hosts[target as usize].f)(&args)?;
                        if res.len() != ft.results.len() || res.iter().zip(&ft.results).any(|(v, t)| v.ty() != *t) {
                            trap!(Trap::Host("host function returned values that do not match its signature".into()));
                        }
                        for v in res {
                            stack.push(v.to_raw());
                        }
                    } else {
                        let callee = enter!(target);
                        if let Some(p) = profile.as_deref_mut() {
                            p.on_call(Some(cur.func), target, false, frames.len() + 2);
                        }
                        frames.push(std::mem::replace(&mut cur, callee));
                        code = &module.codes[target as usize - n_imp].body;
                    }
                }
                Instr::Drop => {
                    stack.pop();
                }
                Instr::Select | Instr::SelectT(_) => {
                    let c = num::pop_i32(stack);
                    let b = stack.pop().unwrap();
                    if c == 0 {
                        *stack.last_mut().unwrap() = b;
                    }
                }
                Instr::LocalGet(x) => {
                    let v = stack[cur.base + *x as usize];
                    stack.push(v);
                }
                Instr::LocalSet(x) => {
                    let v = stack.pop().unwrap();
                    stack[cur.base + *x as usize] = v;
                }
                Instr::LocalTee(x) => {
                    let v = *stack.last().unwrap();
                    stack[cur.base + *x as usize] = v;
                }
                Instr::GlobalGet(x) => stack.push(globals[*x as usize].1),
                Instr::GlobalSet(x) => {
                    let v = stack.pop().unwrap();
                    globals[*x as usize].1 = v;
                }
                Instr::Mem { op, offset, .. } => {
                    let op = *op;
                    if op < 0x36 {
                        let w = num::mem_op(op).unwrap().3 as usize;
                        let ea = ea!(*offset, w);
                        let mem = memory.as_ref().unwrap();
                        let mut buf = [0u8; 8];
                        buf[..w].copy_from_slice(&mem.data[ea..ea + w]);
                        let raw = u64::from_le_bytes(buf);
                        let v = match op {
                            0x2C => raw as u8 as i8 as i32 as u32 as u64,
                            0x2E => raw as u16 as i16 as i32 as u32 as u64,
                            0x30 => raw as u8 as i8 as i64 as u64,
                            0x32 => raw as u16 as i16 as i64 as u64,
                            0x34 => raw as u32 as i32 as i64 as u64,
                            _ => raw,
                        };
                        stack.push(v);
                    } else {
                        let w = num::mem_op(op).unwrap().3 as usize;
                        let v = stack.pop().unwrap();
                        let ea = ea!(*offset, w);
                        let mem = memory.as_mut().unwrap();
                        mem.data[ea..ea + w].copy_from_slice(&v.to_le_bytes()[..w]);
                    }
                }
                Instr::MemorySize => num::push_i32(stack, memory.as_ref().unwrap().pages() as i32),
                Instr::MemoryGrow => {
                    let d = num::pop_i32(stack) as u32;
                    let r = memory.as_mut().unwrap().grow(d).map(|p| p as i32).unwrap_or(-1);
                    num::push_i32(stack, r);
                }
                Instr::MemoryCopy => {
                    let n = num::pop_i32(stack) as u32 as u64;
                    let s = num::pop_i32(stack) as u32 as u64;
                    let d = num::pop_i32(stack) as u32 as u64;
                    let mem = memory.as_mut().unwrap();
                    let len = mem.data.len() as u64;
                    if s + n > len || d + n > len {
                        trap!(Trap::MemoryOob);
                    }
                    mem.data.copy_within(s as usize..(s + n) as usize, d as usize);
                }
                Instr::MemoryFill => {
                    let n = num::pop_i32(stack) as u32 as u64;
                    let v = num::pop_i32(stack) as u8;
                    let d = num::pop_i32(stack) as u32 as u64;
                    let mem = memory.as_mut().unwrap();
                    if d + n > mem.data.len() as u64 {
                        trap!(Trap::MemoryOob);
                    }
                    mem.data[d as usize..(d + n) as usize].fill(v);
                }
                Instr::I32Const(v) => num::push_i32(stack, *v),
                Instr::I64Const(v) => num::push_i64(stack, *v),
                Instr::F32Const(b) => stack.push(*b as u64),
                Instr::F64Const(b) => stack.push(*b),
                Instr::Num(c) => num::exec(*c, stack)?,
            }
        }
    }
}

fn bt_arity(m: &Module, bt: &BlockType) -> (usize, usize) {
    match bt {
        BlockType::Empty => (0, 0),
        BlockType::Val(_) => (0, 1),
        BlockType::Type(i) => {
            let t = &m.types[*i as usize];
            (t.params.len(), t.results.len())
        }
    }
}
