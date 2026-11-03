//! GC-safe evaluator. Every live Value is kept in `roots` (an explicit stack) across anything
//! that can allocate, because a moving collector rewrites that vector in place. Rust locals only
//! ever hold a Value between two operations that cannot allocate.

use crate::heap::*;
use crate::lang::*;
use crate::verify;
use std::collections::HashSet;
use std::io::Write;

#[derive(Debug, Clone)]
pub enum VmError {
    Type(String),
    DivZero,
    Index(String),
    Oom(OutOfMemory),
    StackOverflow,
    Assert(String),
    StepLimit,
    /// the oracle caught the collector breaking the heap
    Corrupt(String),
}
impl std::fmt::Display for VmError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            VmError::Type(s) => write!(f, "type error: {s}"),
            VmError::DivZero => write!(f, "division by zero"),
            VmError::Index(s) => write!(f, "index error: {s}"),
            VmError::Oom(o) => write!(f, "{o}"),
            VmError::StackOverflow => write!(f, "stack overflow (call depth limit)"),
            VmError::Assert(s) => write!(f, "assertion failed{}", if s.is_empty() { String::new() } else { format!(": {s}") }),
            VmError::StepLimit => write!(f, "step limit exceeded"),
            VmError::Corrupt(s) => write!(f, "HEAP CORRUPTION detected by oracle: {s}"),
        }
    }
}
impl std::error::Error for VmError {}
impl From<OutOfMemory> for VmError {
    fn from(o: OutOfMemory) -> Self {
        VmError::Oom(o)
    }
}

type R<T> = Result<T, VmError>;

pub struct VmOptions {
    /// after every allocation/collect: snapshot-compare + structural heap check (slow)
    pub verify: bool,
    /// collect at every allocation
    pub torture: bool,
    pub max_depth: usize,
    pub step_limit: u64,
    pub seed: u64,
    /// copy program output to stdout as it is produced
    pub stream: bool,
    /// cap on captured output bytes
    pub max_output: usize,
}
impl Default for VmOptions {
    fn default() -> Self {
        VmOptions { verify: false, torture: false, max_depth: 2000, step_limit: u64::MAX, seed: 0x9E3779B97F4A7C15, stream: false, max_output: 1 << 26 }
    }
}

pub struct Vm {
    pub gc: Box<dyn Gc>,
    pub roots: Vec<Value>,
    pub out: Vec<u8>,
    opts: VmOptions,
    rng: u64,
    depth: usize,
    steps: u64,
    pub verify_checks: u64,
}

impl Vm {
    pub fn new(mut gc: Box<dyn Gc>, opts: VmOptions) -> Vm {
        gc.set_torture(opts.torture);
        let rng = opts.seed | 1;
        Vm { gc, roots: Vec::new(), out: Vec::new(), opts, rng, depth: 0, steps: 0, verify_checks: 0 }
    }

    pub fn steps(&self) -> u64 {
        self.steps
    }

    /// Run a whole program; returns the value of the last top-level form (as a debug string).
    pub fn run(&mut self, prog: &Program) -> R<()> {
        self.roots.clear();
        self.roots.resize(prog.globals.len(), Value::NIL);
        let base = self.roots.len();
        self.roots.resize(base + prog.main.nslots, Value::NIL);
        for e in &prog.main.body {
            self.eval(prog, e, base)?;
        }
        let mut roots = std::mem::take(&mut self.roots);
        self.gc.finish(&mut roots)?;
        self.roots = roots;
        if self.opts.verify {
            self.verify_now("end of program")?;
        }
        Ok(())
    }

    // ---------------------------------------------------------------- helpers

    fn emit(&mut self, s: &str) {
        if self.opts.stream {
            let _ = std::io::stdout().write_all(s.as_bytes());
        }
        if self.out.len() < self.opts.max_output {
            self.out.extend_from_slice(s.as_bytes());
        }
    }

    fn verify_now(&mut self, when: &str) -> R<()> {
        let errs = verify::check_heap(self.gc.as_ref(), &self.roots);
        if let Some(e) = errs.first() {
            return Err(VmError::Corrupt(format!("{when}: {e} ({} violations, collector {})", errs.len(), self.gc.name())));
        }
        Ok(())
    }

    fn alloc(&mut self, kind: Kind, len: usize) -> R<Value> {
        if self.opts.verify {
            let before = verify::snapshot(self.gc.as_ref(), &self.roots);
            let v = self.gc.alloc(kind, len, &mut self.roots)?;
            let after = verify::snapshot(self.gc.as_ref(), &self.roots);
            self.verify_checks += 1;
            if before != after {
                return Err(VmError::Corrupt(format!(
                    "reachable graph changed across an allocation under {} ({} -> {} objects)",
                    self.gc.name(),
                    before.nodes.len(),
                    after.nodes.len()
                )));
            }
            self.verify_now("after allocation")?;
            Ok(v)
        } else {
            Ok(self.gc.alloc(kind, len, &mut self.roots)?)
        }
    }

    fn collect(&mut self, full: bool) -> R<()> {
        let before = if self.opts.verify { Some(verify::snapshot(self.gc.as_ref(), &self.roots)) } else { None };
        let mut roots = std::mem::take(&mut self.roots);
        let r = self.gc.collect(&mut roots, full);
        self.roots = roots;
        r?;
        if let Some(b) = before {
            let after = verify::snapshot(self.gc.as_ref(), &self.roots);
            self.verify_checks += 1;
            if b != after {
                return Err(VmError::Corrupt(format!("reachable graph changed across collect() under {}", self.gc.name())));
            }
            self.verify_now("after collect")?;
        }
        Ok(())
    }

    fn truthy(v: Value) -> bool {
        !v.is_nil()
    }

    fn int_of(&self, v: Value, what: &str) -> R<i64> {
        if v.is_int() {
            Ok(v.as_int())
        } else {
            Err(VmError::Type(format!("{what} expects an integer, got {}", self.describe(v))))
        }
    }

    fn describe(&self, v: Value) -> &'static str {
        if v.is_nil() {
            "nil"
        } else if v.is_int() {
            "an integer"
        } else {
            match self.gc.kind(v) {
                Kind::Pair => "a pair",
                Kind::Vec => "a vector",
                Kind::Str => "a string",
                Kind::Free => "a freed object (!)",
            }
        }
    }

    fn pair_of(&self, v: Value, what: &str) -> R<Value> {
        if v.is_ptr() && self.gc.kind(v) == Kind::Pair {
            Ok(v)
        } else {
            Err(VmError::Type(format!("{what} expects a pair, got {}", self.describe(v))))
        }
    }

    fn vec_of(&self, v: Value, what: &str) -> R<Value> {
        if v.is_ptr() && self.gc.kind(v) == Kind::Vec {
            Ok(v)
        } else {
            Err(VmError::Type(format!("{what} expects a vector, got {}", self.describe(v))))
        }
    }

    fn str_of(&self, v: Value, what: &str) -> R<Value> {
        if v.is_ptr() && self.gc.kind(v) == Kind::Str {
            Ok(v)
        } else {
            Err(VmError::Type(format!("{what} expects a string, got {}", self.describe(v))))
        }
    }

    fn new_str(&mut self, bytes: &[u8]) -> R<Value> {
        let v = self.alloc(Kind::Str, str_words(bytes.len()))?;
        let a = v.addr();
        let m = self.gc.mem_mut();
        m[a + 1] = bytes.len() as u64;
        for (i, b) in bytes.iter().enumerate() {
            m[a + 2 + i / 8] |= (*b as u64) << ((i % 8) * 8);
        }
        Ok(v)
    }

    // ---------------------------------------------------------------- printing

    pub fn render(&self, v: Value, top: bool) -> String {
        let mut s = String::new();
        let mut budget = 200_000usize;
        let mut path = HashSet::new();
        self.fmt_value(v, top, &mut s, &mut budget, &mut path, 0);
        s
    }

    fn fmt_value(&self, v: Value, top: bool, out: &mut String, budget: &mut usize, path: &mut HashSet<Addr>, depth: usize) {
        if *budget == 0 {
            if !out.ends_with('…') {
                out.push('…');
            }
            return;
        }
        *budget -= 1;
        if v.is_nil() {
            out.push_str("nil");
        } else if v.is_int() {
            out.push_str(&v.as_int().to_string());
        } else {
            let a = v.addr();
            match self.gc.kind(v) {
                Kind::Str => {
                    let b = self.gc.str_bytes(v);
                    let s = String::from_utf8_lossy(&b);
                    if top {
                        out.push_str(&s);
                    } else {
                        out.push('"');
                        for c in s.chars() {
                            match c {
                                '"' => out.push_str("\\\""),
                                '\\' => out.push_str("\\\\"),
                                '\n' => out.push_str("\\n"),
                                c => out.push(c),
                            }
                        }
                        out.push('"');
                    }
                }
                Kind::Pair => {
                    if depth > 500 || path.contains(&a) {
                        out.push_str("#<cycle>");
                        return;
                    }
                    out.push('(');
                    let mut cur = v;
                    let mut chain: Vec<Addr> = Vec::new();
                    let mut first = true;
                    loop {
                        let ca = cur.addr();
                        if path.contains(&ca) {
                            out.push_str(" . #<cycle>");
                            break;
                        }
                        path.insert(ca);
                        chain.push(ca);
                        if !first {
                            out.push(' ');
                        }
                        first = false;
                        self.fmt_value(self.gc.load(cur, 0), false, out, budget, path, depth + 1);
                        let tail = self.gc.load(cur, 1);
                        if tail.is_nil() {
                            break;
                        }
                        if tail.is_ptr() && self.gc.kind(tail) == Kind::Pair {
                            cur = tail;
                            if *budget == 0 {
                                out.push_str(" …");
                                break;
                            }
                            *budget -= 1;
                        } else {
                            out.push_str(" . ");
                            self.fmt_value(tail, false, out, budget, path, depth + 1);
                            break;
                        }
                    }
                    for c in chain {
                        path.remove(&c);
                    }
                    out.push(')');
                }
                Kind::Vec => {
                    if depth > 500 || path.contains(&a) {
                        out.push_str("#<cycle>");
                        return;
                    }
                    path.insert(a);
                    out.push_str("#(");
                    for i in 0..self.gc.len(v) {
                        if i > 0 {
                            out.push(' ');
                        }
                        if *budget == 0 {
                            out.push('…');
                            break;
                        }
                        self.fmt_value(self.gc.load(v, i), false, out, budget, path, depth + 1);
                    }
                    out.push(')');
                    path.remove(&a);
                }
                Kind::Free => out.push_str("#<FREED>"),
            }
        }
    }

    // ---------------------------------------------------------------- evaluation

    fn tick(&mut self) -> R<()> {
        self.steps += 1;
        if self.steps > self.opts.step_limit {
            return Err(VmError::StepLimit);
        }
        Ok(())
    }

    /// Evaluate each argument, leaving results on the root stack. Returns the stack position of arg 0.
    fn push_args(&mut self, prog: &Program, args: &[Expr], base: usize) -> R<usize> {
        let sp = self.roots.len();
        for a in args {
            let v = self.eval(prog, a, base)?;
            self.roots.push(v);
        }
        Ok(sp)
    }

    pub fn eval(&mut self, prog: &Program, e: &Expr, base: usize) -> R<Value> {
        self.tick()?;
        match e {
            Expr::Int(n) => Ok(Value::int(*n)),
            Expr::Nil => Ok(Value::NIL),
            Expr::Str(s) => self.new_str(s.as_bytes()),
            Expr::Local(i) => Ok(self.roots[base + i]),
            Expr::Global(i) => Ok(self.roots[*i]),
            Expr::SetLocal(i, x) => {
                let v = self.eval(prog, x, base)?;
                self.roots[base + i] = v;
                Ok(v)
            }
            Expr::SetGlobal(i, x) => {
                let v = self.eval(prog, x, base)?;
                self.roots[*i] = v;
                Ok(v)
            }
            Expr::Let(binds, body) => {
                for (slot, init) in binds {
                    let v = self.eval(prog, init, base)?;
                    self.roots[base + slot] = v;
                }
                let mut last = Value::NIL;
                for b in body {
                    last = self.eval(prog, b, base)?;
                }
                // let the collector reclaim whatever the dead bindings kept alive
                for (slot, _) in binds {
                    self.roots[base + slot] = Value::NIL;
                }
                Ok(last)
            }
            Expr::If(c, a, b) => {
                let cv = self.eval(prog, c, base)?;
                if Self::truthy(cv) {
                    self.eval(prog, a, base)
                } else {
                    self.eval(prog, b, base)
                }
            }
            Expr::While(c, body) => {
                loop {
                    let cv = self.eval(prog, c, base)?;
                    if !Self::truthy(cv) {
                        break;
                    }
                    for b in body {
                        self.eval(prog, b, base)?;
                    }
                }
                Ok(Value::NIL)
            }
            Expr::Begin(xs) => {
                let mut last = Value::NIL;
                for x in xs {
                    last = self.eval(prog, x, base)?;
                }
                Ok(last)
            }
            Expr::And(xs) => {
                let mut last = Value::int(1);
                for x in xs {
                    last = self.eval(prog, x, base)?;
                    if !Self::truthy(last) {
                        return Ok(Value::NIL);
                    }
                }
                Ok(last)
            }
            Expr::Or(xs) => {
                for x in xs {
                    let v = self.eval(prog, x, base)?;
                    if Self::truthy(v) {
                        return Ok(v);
                    }
                }
                Ok(Value::NIL)
            }
            Expr::Call(fi, args) => {
                if self.depth >= self.opts.max_depth {
                    return Err(VmError::StackOverflow);
                }
                let f = &prog.funcs[*fi];
                let fbase = self.push_args(prog, args, base)?;
                self.roots.resize(fbase + f.nslots.max(f.nparams), Value::NIL);
                self.depth += 1;
                let mut last = Value::NIL;
                for b in &f.body {
                    last = self.eval(prog, b, fbase)?;
                }
                self.depth -= 1;
                self.roots.truncate(fbase);
                Ok(last)
            }
            Expr::Prim(p, args) => self.prim(prog, *p, args, base),
        }
    }

    fn bool_v(b: bool) -> Value {
        if b {
            Value::int(1)
        } else {
            Value::NIL
        }
    }

    fn prim(&mut self, prog: &Program, p: Prim, args: &[Expr], base: usize) -> R<Value> {
        use Prim::*;
        let sp = self.push_args(prog, args, base)?;
        let a = |vm: &Vm, i: usize| vm.roots[sp + i];
        let result = match p {
            Add | Sub | Mul | Div | Rem | Lt | Gt | Le | Ge | NumEq | Ne => {
                let name = match p {
                    Add => "+",
                    Sub => "-",
                    Mul => "*",
                    Div => "/",
                    Rem => "%",
                    Lt => "<",
                    Gt => ">",
                    Le => "<=",
                    Ge => ">=",
                    NumEq => "=",
                    _ => "!=",
                };
                let x = self.int_of(a(self, 0), name)?;
                let y = self.int_of(a(self, 1), name)?;
                match p {
                    Add => Value::int(x.wrapping_add(y)),
                    Sub => Value::int(x.wrapping_sub(y)),
                    Mul => Value::int(x.wrapping_mul(y)),
                    Div | Rem => {
                        if y == 0 {
                            return Err(VmError::DivZero);
                        }
                        Value::int(if p == Div { x.wrapping_div(y) } else { x.wrapping_rem(y) })
                    }
                    Lt => Self::bool_v(x < y),
                    Gt => Self::bool_v(x > y),
                    Le => Self::bool_v(x <= y),
                    Ge => Self::bool_v(x >= y),
                    NumEq => Self::bool_v(x == y),
                    _ => Self::bool_v(x != y),
                }
            }
            Eq => Self::bool_v(a(self, 0) == a(self, 1)),
            Not => Self::bool_v(!Self::truthy(a(self, 0))),
            Cons => {
                let p = self.alloc(Kind::Pair, 2)?;
                let (x, y) = (self.roots[sp], self.roots[sp + 1]);
                self.gc.store(p, 0, x);
                self.gc.store(p, 1, y);
                p
            }
            Car | Cdr => {
                let pv = self.pair_of(a(self, 0), if p == Car { "car" } else { "cdr" })?;
                self.gc.load(pv, (p == Cdr) as usize)
            }
            SetCar | SetCdr => {
                let pv = self.pair_of(a(self, 0), if p == SetCar { "set-car!" } else { "set-cdr!" })?;
                let v = a(self, 1);
                self.gc.store(pv, (p == SetCdr) as usize, v);
                v
            }
            IsPair => Self::bool_v(a(self, 0).is_ptr() && self.gc.kind(a(self, 0)) == Kind::Pair),
            IsNil => Self::bool_v(a(self, 0).is_nil()),
            IsInt => Self::bool_v(a(self, 0).is_int()),
            IsVec => Self::bool_v(a(self, 0).is_ptr() && self.gc.kind(a(self, 0)) == Kind::Vec),
            IsStr => Self::bool_v(a(self, 0).is_ptr() && self.gc.kind(a(self, 0)) == Kind::Str),
            Vector => {
                let n = self.int_of(a(self, 0), "vector")?;
                if !(0..=(1 << 28)).contains(&n) {
                    return Err(VmError::Index(format!("vector length {n} out of range")));
                }
                let v = self.alloc(Kind::Vec, n as usize)?;
                if args.len() == 2 {
                    let fill = self.roots[sp + 1];
                    if !fill.is_nil() {
                        for i in 0..n as usize {
                            self.gc.store(v, i, fill);
                        }
                    }
                }
                v
            }
            Vref | Vset => {
                let name = if p == Vref { "vref" } else { "vset!" };
                let v = self.vec_of(a(self, 0), name)?;
                let i = self.int_of(a(self, 1), name)?;
                let n = self.gc.len(v);
                if i < 0 || i as usize >= n {
                    return Err(VmError::Index(format!("{name}: index {i} outside 0..{n}")));
                }
                if p == Vref {
                    self.gc.load(v, i as usize)
                } else {
                    let x = a(self, 2);
                    self.gc.store(v, i as usize, x);
                    x
                }
            }
            Vlen => {
                let v = self.vec_of(a(self, 0), "vlen")?;
                Value::int(self.gc.len(v) as i64)
            }
            StrLen => {
                let s = self.str_of(a(self, 0), "strlen")?;
                Value::int(self.gc.mem()[s.addr() + 1] as i64)
            }
            StrRef => {
                let s = self.str_of(a(self, 0), "strref")?;
                let i = self.int_of(a(self, 1), "strref")?;
                let n = self.gc.mem()[s.addr() + 1] as i64;
                if i < 0 || i >= n {
                    return Err(VmError::Index(format!("strref: index {i} outside 0..{n}")));
                }
                Value::int(self.gc.str_bytes(s)[i as usize] as i64)
            }
            Substr => {
                let s = self.str_of(a(self, 0), "substr")?;
                let i = self.int_of(a(self, 1), "substr")?;
                let j = self.int_of(a(self, 2), "substr")?;
                let bytes = self.gc.str_bytes(s);
                if i < 0 || j < i || j as usize > bytes.len() {
                    return Err(VmError::Index(format!("substr: range {i}..{j} outside 0..{}", bytes.len())));
                }
                self.new_str(&bytes[i as usize..j as usize])?
            }
            StrCat => {
                let x = self.str_of(a(self, 0), "strcat")?;
                let y = self.str_of(a(self, 1), "strcat")?;
                let mut bytes = self.gc.str_bytes(x);
                bytes.extend(self.gc.str_bytes(y));
                self.new_str(&bytes)?
            }
            Int2Str => {
                let n = self.int_of(a(self, 0), "str")?;
                self.new_str(n.to_string().as_bytes())?
            }
            Print => {
                let mut line = String::new();
                for i in 0..args.len() {
                    if i > 0 {
                        line.push(' ');
                    }
                    line.push_str(&self.render(self.roots[sp + i], true));
                }
                line.push('\n');
                self.emit(&line);
                Value::NIL
            }
            Assert => {
                if !Self::truthy(a(self, 0)) {
                    return Err(VmError::Assert(String::new()));
                }
                Value::int(1)
            }
            Rand => {
                let n = self.int_of(a(self, 0), "rand")?;
                if n <= 0 {
                    return Err(VmError::Index(format!("rand: bound {n} must be positive")));
                }
                // xorshift64*
                let mut x = self.rng;
                x ^= x >> 12;
                x ^= x << 25;
                x ^= x >> 27;
                self.rng = x;
                Value::int((x.wrapping_mul(0x2545F4914F6CDD1D) >> 2) as i64 % n)
            }
            Gc => {
                self.collect(true)?;
                Value::NIL
            }
            GcMinor => {
                self.collect(false)?;
                Value::NIL
            }
            Digest => {
                let snap = verify::snapshot(self.gc.as_ref(), &[self.roots[sp]]);
                Value::int(snap.digest())
            }
        };
        self.roots.truncate(sp);
        Ok(result)
    }
}

/// Convenience: compile + run a source string under a named collector, returning (output, vm).
pub fn run_source(src: &str, gc_name: &str, cfg: &crate::GcConfig, opts: VmOptions) -> Result<(String, Vm), String> {
    let prog = compile(src).map_err(|e| e.to_string())?;
    let gc = crate::make_gc(gc_name, cfg)?;
    let mut vm = Vm::new(gc, opts);
    match vm.run(&prog) {
        Ok(()) => {
            let out = String::from_utf8_lossy(&vm.out).into_owned();
            Ok((out, vm))
        }
        Err(e) => Err(format!("{e}")),
    }
}
