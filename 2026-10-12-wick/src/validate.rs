//! Module validation: the WebAssembly spec's stack-polymorphic type-checking algorithm.
use crate::ast::*;
use crate::num;
use std::collections::HashSet;

#[derive(Debug, Clone, PartialEq)]
pub struct ValidationError {
    /// Function index (in the whole function index space) the error occurred in, if any.
    pub func: Option<u32>,
    /// Instruction index within the function body / constant expression, if any.
    pub instr: Option<usize>,
    pub msg: String,
}

impl std::fmt::Display for ValidationError {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "validation error")?;
        if let Some(fi) = self.func {
            write!(f, " in function #{fi}")?;
        }
        if let Some(i) = self.instr {
            write!(f, " at instruction {i}")?;
        }
        write!(f, ": {}", self.msg)
    }
}
impl std::error::Error for ValidationError {}

fn merr<T>(msg: impl Into<String>) -> Result<T, ValidationError> {
    Err(ValidationError { func: None, instr: None, msg: msg.into() })
}

const MAX_PAGES: u32 = 65536;

fn check_limits(l: &Limits, what: &str, bound: u32) -> Result<(), ValidationError> {
    if l.min > bound {
        return merr(format!("{what} minimum {} exceeds {bound}", l.min));
    }
    if let Some(max) = l.max {
        if max > bound {
            return merr(format!("{what} maximum {max} exceeds {bound}"));
        }
        if max < l.min {
            return merr(format!("{what} maximum {max} is less than minimum {}", l.min));
        }
    }
    Ok(())
}

pub fn validate(m: &Module) -> Result<(), ValidationError> {
    let ntypes = m.types.len() as u32;
    for imp in &m.imports {
        match &imp.desc {
            ImportDesc::Func(t) if *t >= ntypes => return merr(format!("import {}.{}: unknown type {t}", imp.module, imp.name)),
            ImportDesc::Table(l) => check_limits(l, "table", u32::MAX)?,
            ImportDesc::Mem(l) => check_limits(l, "memory", MAX_PAGES)?,
            _ => {}
        }
    }
    for t in &m.funcs {
        if *t >= ntypes {
            return merr(format!("function declares unknown type {t}"));
        }
    }
    if m.funcs.len() != m.codes.len() {
        return merr("function and code section lengths differ");
    }
    for t in &m.tables {
        check_limits(t, "table", u32::MAX)?;
    }
    for t in &m.mems {
        check_limits(t, "memory", MAX_PAGES)?;
    }
    let tables = m.all_tables();
    let mems = m.all_mems();
    if tables.len() > 1 {
        return merr("multiple tables are not supported");
    }
    if mems.len() > 1 {
        return merr("multiple memories are not supported");
    }
    let globals = m.all_globals();
    let func_types = m.all_func_types();
    let n_imp_globals = globals.len() - m.globals.len();

    // global initialisers
    for (i, g) in m.globals.iter().enumerate() {
        const_expr(m, &g.init, g.ty.ty, &globals[..n_imp_globals]).map_err(|mut e| {
            e.msg = format!("global {}: {}", n_imp_globals + i, e.msg);
            e
        })?;
    }
    // exports
    let mut seen = HashSet::new();
    for e in &m.exports {
        if !seen.insert(e.name.as_str()) {
            return merr(format!("duplicate export name \"{}\"", e.name));
        }
        let (n, what) = match e.kind {
            ExportKind::Func => (func_types.len(), "function"),
            ExportKind::Table => (tables.len(), "table"),
            ExportKind::Mem => (mems.len(), "memory"),
            ExportKind::Global => (globals.len(), "global"),
        };
        if e.index as usize >= n {
            return merr(format!("export \"{}\": unknown {what} {}", e.name, e.index));
        }
    }
    if let Some(s) = m.start {
        match func_types.get(s as usize) {
            None => return merr(format!("start function {s} does not exist")),
            Some(&t) => {
                let ft = &m.types[t as usize];
                if !ft.params.is_empty() || !ft.results.is_empty() {
                    return merr("start function must have type [] -> []");
                }
            }
        }
    }
    for (i, e) in m.elems.iter().enumerate() {
        if e.table as usize >= tables.len() {
            return merr(format!("element segment {i}: unknown table {}", e.table));
        }
        const_expr(m, &e.offset, ValType::I32, &globals[..n_imp_globals]).map_err(|mut x| {
            x.msg = format!("element segment {i} offset: {}", x.msg);
            x
        })?;
        for f in &e.funcs {
            if *f as usize >= func_types.len() {
                return merr(format!("element segment {i}: unknown function {f}"));
            }
        }
    }
    for (i, d) in m.datas.iter().enumerate() {
        if d.mem as usize >= mems.len() {
            return merr(format!("data segment {i}: unknown memory {}", d.mem));
        }
        const_expr(m, &d.offset, ValType::I32, &globals[..n_imp_globals]).map_err(|mut x| {
            x.msg = format!("data segment {i} offset: {}", x.msg);
            x
        })?;
    }

    let n_imp = m.num_imported_funcs() as u32;
    let ctx = Ctx { m, func_types: &func_types, tables: &tables, mems: &mems, globals: &globals };
    for (i, code) in m.codes.iter().enumerate() {
        let fidx = n_imp + i as u32;
        let ft = &m.types[m.funcs[i] as usize];
        validate_func(&ctx, ft, code).map_err(|mut e| {
            e.func = Some(fidx);
            e
        })?;
    }
    Ok(())
}

fn const_expr(_m: &Module, e: &[Instr], want: ValType, imported_globals: &[GlobalType]) -> Result<(), ValidationError> {
    if e.len() != 2 || e[1] != Instr::End {
        return merr("constant expression must be a single constant instruction followed by end");
    }
    let got = match &e[0] {
        Instr::I32Const(_) => ValType::I32,
        Instr::I64Const(_) => ValType::I64,
        Instr::F32Const(_) => ValType::F32,
        Instr::F64Const(_) => ValType::F64,
        Instr::GlobalGet(g) => match imported_globals.get(*g as usize) {
            Some(gt) if !gt.mutable => gt.ty,
            Some(_) => return merr("constant expression may not read a mutable global"),
            None => return merr(format!("constant expression reads global {g}, which is not an imported global")),
        },
        other => return merr(format!("instruction {other:?} is not allowed in a constant expression")),
    };
    if got != want {
        return merr(format!("constant expression has type {} but {} is required", got.name(), want.name()));
    }
    Ok(())
}

struct Ctx<'a> {
    m: &'a Module,
    func_types: &'a [u32],
    tables: &'a [Limits],
    mems: &'a [Limits],
    globals: &'a [GlobalType],
}

#[derive(Clone, Copy, PartialEq, Debug)]
enum Kind {
    Func,
    Block,
    Loop,
    If,
    Else,
}

struct Frame {
    kind: Kind,
    start: Vec<ValType>,
    end: Vec<ValType>,
    height: usize,
    unreachable: bool,
}

struct Checker<'a> {
    ctx: &'a Ctx<'a>,
    vals: Vec<Option<ValType>>,
    ctrls: Vec<Frame>,
    pos: usize,
}

type V<T> = Result<T, ValidationError>;


impl<'a> Checker<'a> {
    fn err<T>(&self, msg: impl Into<String>) -> V<T> {
        Err(ValidationError { func: None, instr: Some(self.pos), msg: msg.into() })
    }
    fn push(&mut self, t: ValType) {
        self.vals.push(Some(t));
    }
    fn pop(&mut self) -> V<Option<ValType>> {
        let f = self.ctrls.last().unwrap();
        if self.vals.len() == f.height {
            if f.unreachable {
                return Ok(None);
            }
            return self.err("type mismatch: operand stack underflow");
        }
        Ok(self.vals.pop().unwrap())
    }
    fn pop_expect(&mut self, want: ValType) -> V<Option<ValType>> {
        let got = self.pop()?;
        match got {
            Some(g) if g != want => self.err(format!("type mismatch: expected {}, found {}", want.name(), g.name())),
            _ => Ok(got.or(Some(want))),
        }
    }
    fn pop_vals(&mut self, ts: &[ValType]) -> V<()> {
        for t in ts.iter().rev() {
            self.pop_expect(*t)?;
        }
        Ok(())
    }
    fn push_vals(&mut self, ts: &[ValType]) {
        for t in ts {
            self.push(*t);
        }
    }
    fn push_ctrl(&mut self, kind: Kind, start: Vec<ValType>, end: Vec<ValType>) {
        let height = self.vals.len();
        self.ctrls.push(Frame { kind, start: start.clone(), end, height, unreachable: false });
        self.push_vals(&start);
    }
    fn pop_ctrl(&mut self) -> V<Frame> {
        let end = self.ctrls.last().unwrap().end.clone();
        self.pop_vals(&end)?;
        let f = self.ctrls.last().unwrap();
        if self.vals.len() != f.height {
            let extra = self.vals.len() - f.height;
            return self.err(format!("type mismatch: {extra} extra value(s) left on the stack at end of block"));
        }
        Ok(self.ctrls.pop().unwrap())
    }
    fn set_unreachable(&mut self) {
        let f = self.ctrls.last_mut().unwrap();
        self.vals.truncate(f.height);
        f.unreachable = true;
    }
    fn label_types(&self, depth: u32) -> V<Vec<ValType>> {
        if depth as usize >= self.ctrls.len() {
            return self.err(format!("unknown label {depth}"));
        }
        let f = &self.ctrls[self.ctrls.len() - 1 - depth as usize];
        Ok(if f.kind == Kind::Loop { f.start.clone() } else { f.end.clone() })
    }
    fn block_sig(&self, bt: &BlockType) -> V<(Vec<ValType>, Vec<ValType>)> {
        Ok(match bt {
            BlockType::Empty => (vec![], vec![]),
            BlockType::Val(v) => (vec![], vec![*v]),
            BlockType::Type(i) => match self.ctx.m.types.get(*i as usize) {
                Some(t) => (t.params.clone(), t.results.clone()),
                None => return self.err(format!("unknown block type index {i}")),
            },
        })
    }
    fn need_mem(&self) -> V<()> {
        if self.ctx.mems.is_empty() {
            return self.err("memory instruction but module has no memory");
        }
        Ok(())
    }
}

fn validate_func(ctx: &Ctx, ft: &FuncType, code: &Code) -> V<()> {
    let mut locals = ft.params.clone();
    locals.extend(code.locals.iter().copied());
    if locals.len() > 50_000 {
        return Err(ValidationError { func: None, instr: None, msg: format!("too many locals ({})", locals.len()) });
    }
    let mut c = Checker { ctx, vals: vec![], ctrls: vec![], pos: 0 };
    c.ctrls.push(Frame { kind: Kind::Func, start: vec![], end: ft.results.clone(), height: 0, unreachable: false });
    for (pos, ins) in code.body.iter().enumerate() {
        c.pos = pos;
        if c.ctrls.is_empty() {
            return c.err("instructions after the end of the function body");
        }
        step(&mut c, ins, &locals)?;
    }
    c.pos = code.body.len().saturating_sub(1);
    if !c.ctrls.is_empty() {
        return c.err("function body is not terminated by `end` (unclosed block)");
    }
    Ok(())
}

fn step(c: &mut Checker, ins: &Instr, locals: &[ValType]) -> V<()> {
    use ValType::*;
    match ins {
        Instr::Unreachable => c.set_unreachable(),
        Instr::Nop => {}
        Instr::Block(bt) | Instr::Loop(bt) => {
            let (p, r) = c.block_sig(bt)?;
            c.pop_vals(&p)?;
            c.push_ctrl(if matches!(ins, Instr::Loop(_)) { Kind::Loop } else { Kind::Block }, p, r);
        }
        Instr::If(bt) => {
            let (p, r) = c.block_sig(bt)?;
            c.pop_expect(I32)?;
            c.pop_vals(&p)?;
            c.push_ctrl(Kind::If, p, r);
        }
        Instr::Else => {
            let f = c.pop_ctrl()?;
            if f.kind != Kind::If {
                return c.err("`else` without matching `if`");
            }
            c.push_ctrl(Kind::Else, f.start, f.end);
        }
        Instr::End => {
            let f = c.pop_ctrl()?;
            if f.kind == Kind::If && f.start != f.end {
                return c.err("`if` without `else` must have matching parameter and result types");
            }
            c.push_vals(&f.end);
        }
        Instr::Br(l) => {
            let ts = c.label_types(*l)?;
            c.pop_vals(&ts)?;
            c.set_unreachable();
        }
        Instr::BrIf(l) => {
            c.pop_expect(I32)?;
            let ts = c.label_types(*l)?;
            c.pop_vals(&ts)?;
            c.push_vals(&ts);
        }
        Instr::BrTable(ls, d) => {
            c.pop_expect(I32)?;
            let dt = c.label_types(*d)?;
            for l in ls {
                let lt = c.label_types(*l)?;
                if lt.len() != dt.len() {
                    return c.err("br_table targets have different arities");
                }
                // each target must accept the same operands (checked against the polymorphic stack)
                let saved: Vec<Option<ValType>> = c.vals.clone();
                c.pop_vals(&lt)?;
                c.vals = saved;
            }
            c.pop_vals(&dt)?;
            c.set_unreachable();
        }
        Instr::Return => {
            let r = c.ctrls[0].end.clone();
            c.pop_vals(&r)?;
            c.set_unreachable();
        }
        Instr::Call(f) => {
            let t = match c.ctx.func_types.get(*f as usize) {
                Some(t) => &c.ctx.m.types[*t as usize],
                None => return c.err(format!("call to unknown function {f}")),
            };
            c.pop_vals(&t.params)?;
            c.push_vals(&t.results);
        }
        Instr::CallIndirect(t, tab) => {
            if *tab as usize >= c.ctx.tables.len() {
                return c.err(format!("call_indirect: unknown table {tab}"));
            }
            let ft = match c.ctx.m.types.get(*t as usize) {
                Some(t) => t,
                None => return c.err(format!("call_indirect: unknown type {t}")),
            };
            c.pop_expect(I32)?;
            c.pop_vals(&ft.params)?;
            c.push_vals(&ft.results);
        }
        Instr::Drop => {
            c.pop()?;
        }
        Instr::Select => {
            c.pop_expect(I32)?;
            let t1 = c.pop()?;
            let t2 = c.pop()?;
            match (t1, t2) {
                (Some(a), Some(b)) if a != b => return c.err(format!("select operands have different types ({} vs {})", a.name(), b.name())),
                _ => {}
            }
            match t1.or(t2) {
                Some(t) => c.push(t),
                None => c.vals.push(None),
            }
        }
        Instr::SelectT(t) => {
            c.pop_expect(I32)?;
            c.pop_expect(*t)?;
            c.pop_expect(*t)?;
            c.push(*t);
        }
        Instr::LocalGet(x) | Instr::LocalSet(x) | Instr::LocalTee(x) => {
            let t = match locals.get(*x as usize) {
                Some(t) => *t,
                None => return c.err(format!("unknown local {x}")),
            };
            match ins {
                Instr::LocalGet(_) => c.push(t),
                Instr::LocalSet(_) => {
                    c.pop_expect(t)?;
                }
                _ => {
                    c.pop_expect(t)?;
                    c.push(t);
                }
            }
        }
        Instr::GlobalGet(x) | Instr::GlobalSet(x) => {
            let g = match c.ctx.globals.get(*x as usize) {
                Some(g) => *g,
                None => return c.err(format!("unknown global {x}")),
            };
            if matches!(ins, Instr::GlobalGet(_)) {
                c.push(g.ty);
            } else {
                if !g.mutable {
                    return c.err(format!("global.set on immutable global {x}"));
                }
                c.pop_expect(g.ty)?;
            }
        }
        Instr::Mem { op, align, offset: _ } => {
            c.need_mem()?;
            let (_, _, ty, width) = match num::mem_op(*op) {
                Some(m) => *m,
                None => return c.err(format!("unknown memory opcode {op:#x}")),
            };
            if (1u64 << (*align).min(40)) > width as u64 {
                return c.err(format!("alignment 2^{align} exceeds natural alignment of {width} bytes"));
            }
            if num::is_store(*op) {
                c.pop_expect(ty)?;
                c.pop_expect(I32)?;
            } else {
                c.pop_expect(I32)?;
                c.push(ty);
            }
        }
        Instr::MemorySize => {
            c.need_mem()?;
            c.push(I32);
        }
        Instr::MemoryGrow => {
            c.need_mem()?;
            c.pop_expect(I32)?;
            c.push(I32);
        }
        Instr::MemoryCopy | Instr::MemoryFill => {
            c.need_mem()?;
            c.pop_expect(I32)?;
            c.pop_expect(I32)?;
            c.pop_expect(I32)?;
        }
        Instr::I32Const(_) => c.push(I32),
        Instr::I64Const(_) => c.push(I64),
        Instr::F32Const(_) => c.push(F32),
        Instr::F64Const(_) => c.push(F64),
        Instr::Num(code) => {
            let op = match num::by_code(*code) {
                Some(o) => o,
                None => return c.err(format!("unknown numeric opcode {code:#x}")),
            };
            c.pop_vals(op.params)?;
            c.push(op.result);
        }
    }
    Ok(())
}
