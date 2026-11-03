//! The Cairn mutator language: an s-expression syntax, a reader and a resolver that turns names
//! into frame slots / global indices. Values live only in the managed heap.
//!
//! ```text
//! (def counter 0)                       ; global
//! (fn (len xs) (if (nil? xs) 0 (+ 1 (len (cdr xs)))))
//! (let ((xs (cons 1 (cons 2 nil)))) (print (len xs)))
//! ```

use std::collections::HashMap;

#[derive(Debug, Clone)]
pub enum Sx {
    Int(i64, usize),
    Str(String, usize),
    Sym(String, usize),
    List(Vec<Sx>, usize),
}

impl Sx {
    pub fn line(&self) -> usize {
        match self {
            Sx::Int(_, l) | Sx::Str(_, l) | Sx::Sym(_, l) | Sx::List(_, l) => *l,
        }
    }
}

#[derive(Debug, Clone)]
pub struct LangError {
    pub line: usize,
    pub msg: String,
}
impl std::fmt::Display for LangError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "line {}: {}", self.line, self.msg)
    }
}
impl std::error::Error for LangError {}

fn err<T>(line: usize, msg: impl Into<String>) -> Result<T, LangError> {
    Err(LangError { line, msg: msg.into() })
}

const MAX_NEST: usize = 400;

pub fn read(src: &str) -> Result<Vec<Sx>, LangError> {
    let b: Vec<char> = src.chars().collect();
    let mut i = 0;
    let mut line = 1;
    let mut stack: Vec<(Vec<Sx>, usize)> = vec![(Vec::new(), 1)];
    while i < b.len() {
        let c = b[i];
        match c {
            '\n' => {
                line += 1;
                i += 1;
            }
            c if c.is_whitespace() => i += 1,
            ';' => {
                while i < b.len() && b[i] != '\n' {
                    i += 1;
                }
            }
            '(' => {
                if stack.len() > MAX_NEST {
                    return err(line, "expression nested too deeply");
                }
                stack.push((Vec::new(), line));
                i += 1;
            }
            ')' => {
                if stack.len() < 2 {
                    return err(line, "unexpected ')'");
                }
                let (items, l) = stack.pop().unwrap();
                stack.last_mut().unwrap().0.push(Sx::List(items, l));
                i += 1;
            }
            '"' => {
                let start = line;
                i += 1;
                let mut s = String::new();
                loop {
                    if i >= b.len() {
                        return err(start, "unterminated string");
                    }
                    match b[i] {
                        '"' => {
                            i += 1;
                            break;
                        }
                        '\\' => {
                            i += 1;
                            match b.get(i) {
                                Some('n') => s.push('\n'),
                                Some('t') => s.push('\t'),
                                Some('"') => s.push('"'),
                                Some('\\') => s.push('\\'),
                                other => return err(line, format!("bad string escape {:?}", other)),
                            }
                            i += 1;
                        }
                        ch => {
                            if ch == '\n' {
                                line += 1;
                            }
                            s.push(ch);
                            i += 1;
                        }
                    }
                }
                stack.last_mut().unwrap().0.push(Sx::Str(s, start));
            }
            _ => {
                let st = i;
                while i < b.len() && !b[i].is_whitespace() && !matches!(b[i], '(' | ')' | ';' | '"') {
                    i += 1;
                }
                let tok: String = b[st..i].iter().collect();
                let atom = match tok.parse::<i64>() {
                    Ok(n) => {
                        if !(-(1i64 << 62)..(1i64 << 62)).contains(&n) {
                            return err(line, format!("integer {n} does not fit in 63 bits"));
                        }
                        Sx::Int(n, line)
                    }
                    Err(_) => {
                        let digits = tok.trim_start_matches(['-', '+']);
                        if !digits.is_empty() && digits.chars().all(|c| c.is_ascii_digit()) {
                            return err(line, format!("integer {tok} does not fit in 63 bits"));
                        }
                        Sx::Sym(tok, line)
                    }
                };
                stack.last_mut().unwrap().0.push(atom);
            }
        }
    }
    if stack.len() != 1 {
        return err(stack.last().unwrap().1, "unclosed '('");
    }
    Ok(stack.pop().unwrap().0)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Prim {
    Add,
    Sub,
    Mul,
    Div,
    Rem,
    Lt,
    Gt,
    Le,
    Ge,
    NumEq,
    Ne,
    Eq,
    Cons,
    Car,
    Cdr,
    SetCar,
    SetCdr,
    IsPair,
    IsNil,
    IsInt,
    IsVec,
    IsStr,
    Vector,
    Vref,
    Vset,
    Vlen,
    StrCat,
    StrLen,
    StrRef,
    Substr,
    Print,
    Assert,
    Rand,
    Gc,
    GcMinor,
    GcBegin,
    Digest,
    Not,
    Int2Str,
}

fn prim_of(name: &str) -> Option<(Prim, usize, usize)> {
    use Prim::*;
    // (prim, min args, max args)
    Some(match name {
        "+" => (Add, 2, 32),
        "-" => (Sub, 1, 32),
        "*" => (Mul, 2, 32),
        "/" => (Div, 2, 2),
        "%" => (Rem, 2, 2),
        "<" => (Lt, 2, 2),
        ">" => (Gt, 2, 2),
        "<=" => (Le, 2, 2),
        ">=" => (Ge, 2, 2),
        "=" => (NumEq, 2, 2),
        "!=" => (Ne, 2, 2),
        "eq" => (Eq, 2, 2),
        "cons" => (Cons, 2, 2),
        "car" => (Car, 1, 1),
        "cdr" => (Cdr, 1, 1),
        "set-car!" => (SetCar, 2, 2),
        "set-cdr!" => (SetCdr, 2, 2),
        "pair?" => (IsPair, 1, 1),
        "nil?" => (IsNil, 1, 1),
        "int?" => (IsInt, 1, 1),
        "vector?" => (IsVec, 1, 1),
        "string?" => (IsStr, 1, 1),
        "vector" => (Vector, 1, 2),
        "vref" => (Vref, 2, 2),
        "vset!" => (Vset, 3, 3),
        "vlen" => (Vlen, 1, 1),
        "strcat" => (StrCat, 2, 2),
        "strlen" => (StrLen, 1, 1),
        "strref" => (StrRef, 2, 2),
        "substr" => (Substr, 3, 3),
        "print" => (Print, 0, 64),
        "assert" => (Assert, 1, 1),
        "rand" => (Rand, 1, 1),
        "gc" => (Gc, 0, 0),
        "gc-minor" => (GcMinor, 0, 0),
        "gc-begin" => (GcBegin, 0, 0),
        "digest" => (Digest, 1, 1),
        "not" => (Not, 1, 1),
        "str" => (Int2Str, 1, 1),
        _ => return None,
    })
}

#[derive(Debug, Clone)]
pub enum Expr {
    Int(i64),
    Nil,
    Str(String),
    Local(usize),
    Global(usize),
    SetLocal(usize, Box<Expr>),
    SetGlobal(usize, Box<Expr>),
    Let(Vec<(usize, Expr)>, Vec<Expr>),
    If(Box<Expr>, Box<Expr>, Box<Expr>),
    While(Box<Expr>, Vec<Expr>),
    Begin(Vec<Expr>),
    And(Vec<Expr>),
    Or(Vec<Expr>),
    Call(usize, Vec<Expr>),
    Prim(Prim, Vec<Expr>),
}

#[derive(Debug, Clone)]
pub struct Func {
    pub name: String,
    pub nparams: usize,
    pub nslots: usize,
    pub body: Vec<Expr>,
}

#[derive(Debug, Clone)]
pub struct Program {
    pub funcs: Vec<Func>,
    pub globals: Vec<String>,
    /// top-level forms run in order inside an implicit frame
    pub main: Func,
}

struct Scope<'a> {
    funcs: &'a HashMap<String, (usize, usize)>,
    globals: &'a HashMap<String, usize>,
    vars: Vec<(String, usize)>,
    next: usize,
    max: usize,
}

impl Scope<'_> {
    fn lookup(&self, name: &str) -> Option<usize> {
        self.vars.iter().rev().find(|(n, _)| n == name).map(|(_, s)| *s)
    }
    fn declare(&mut self, name: &str) -> usize {
        let s = self.next;
        self.next += 1;
        self.max = self.max.max(self.next);
        self.vars.push((name.to_string(), s));
        s
    }
}

fn sym(x: &Sx) -> Result<&str, LangError> {
    match x {
        Sx::Sym(s, _) => Ok(s),
        other => err(other.line(), "expected a name"),
    }
}

fn body(items: &[Sx], sc: &mut Scope, line: usize) -> Result<Vec<Expr>, LangError> {
    if items.is_empty() {
        return err(line, "empty body");
    }
    items.iter().map(|x| expr(x, sc)).collect()
}

fn expr(x: &Sx, sc: &mut Scope) -> Result<Expr, LangError> {
    match x {
        Sx::Int(n, _) => Ok(Expr::Int(*n)),
        Sx::Str(s, _) => Ok(Expr::Str(s.clone())),
        Sx::Sym(s, line) => {
            if s == "nil" {
                Ok(Expr::Nil)
            } else if s == "true" {
                Ok(Expr::Int(1))
            } else if let Some(slot) = sc.lookup(s) {
                Ok(Expr::Local(slot))
            } else if let Some(g) = sc.globals.get(s) {
                Ok(Expr::Global(*g))
            } else {
                err(*line, format!("unknown variable '{s}'"))
            }
        }
        Sx::List(items, line) => {
            let line = *line;
            let Some(head) = items.first() else {
                return err(line, "empty list is not an expression (use nil)");
            };
            let Sx::Sym(h, _) = head else {
                return err(line, "the head of a form must be a name");
            };
            let args = &items[1..];
            match h.as_str() {
                "if" => {
                    if args.len() != 3 {
                        return err(line, "if needs (if cond then else)");
                    }
                    Ok(Expr::If(
                        Box::new(expr(&args[0], sc)?),
                        Box::new(expr(&args[1], sc)?),
                        Box::new(expr(&args[2], sc)?),
                    ))
                }
                "when" => {
                    if args.len() < 2 {
                        return err(line, "when needs a condition and a body");
                    }
                    let c = expr(&args[0], sc)?;
                    let b = body(&args[1..], sc, line)?;
                    Ok(Expr::If(Box::new(c), Box::new(Expr::Begin(b)), Box::new(Expr::Nil)))
                }
                "while" => {
                    if args.len() < 2 {
                        return err(line, "while needs a condition and a body");
                    }
                    let c = expr(&args[0], sc)?;
                    Ok(Expr::While(Box::new(c), body(&args[1..], sc, line)?))
                }
                "begin" => Ok(Expr::Begin(body(args, sc, line)?)),
                "and" => Ok(Expr::And(body(args, sc, line)?)),
                "or" => Ok(Expr::Or(body(args, sc, line)?)),
                "set!" => {
                    if args.len() != 2 {
                        return err(line, "set! needs (set! name value)");
                    }
                    let name = sym(&args[0])?;
                    let v = Box::new(expr(&args[1], sc)?);
                    if let Some(s) = sc.lookup(name) {
                        Ok(Expr::SetLocal(s, v))
                    } else if let Some(g) = sc.globals.get(name) {
                        Ok(Expr::SetGlobal(*g, v))
                    } else {
                        err(line, format!("set! of unknown variable '{name}'"))
                    }
                }
                "let" => {
                    let Some(Sx::List(binds, bl)) = args.first() else {
                        return err(line, "let needs a binding list");
                    };
                    let saved_vars = sc.vars.len();
                    let saved_next = sc.next;
                    let mut out = Vec::new();
                    for b in binds {
                        let Sx::List(p, pl) = b else {
                            return err(*bl, "let binding must be (name value)");
                        };
                        if p.len() != 2 {
                            return err(*pl, "let binding must be (name value)");
                        }
                        let name = sym(&p[0])?;
                        let init = expr(&p[1], sc)?; // sequential: earlier bindings are visible
                        let slot = sc.declare(name);
                        out.push((slot, init));
                    }
                    let b = body(&args[1..], sc, line)?;
                    sc.vars.truncate(saved_vars);
                    sc.next = saved_next;
                    Ok(Expr::Let(out, b))
                }
                "def" | "fn" => err(line, format!("'{h}' is only allowed at top level")),
                name => {
                    if let Some(&(idx, arity)) = sc.funcs.get(name) {
                        if args.len() != arity {
                            return err(line, format!("{name} takes {arity} argument(s), got {}", args.len()));
                        }
                        let a: Result<Vec<_>, _> = args.iter().map(|x| expr(x, sc)).collect();
                        return Ok(Expr::Call(idx, a?));
                    }
                    if let Some((p, lo, hi)) = prim_of(name) {
                        if args.len() < lo || args.len() > hi {
                            let want = if lo == hi { format!("{lo}") } else { format!("{lo}..{hi}") };
                            return err(line, format!("{name} takes {want} argument(s), got {}", args.len()));
                        }
                        let a: Result<Vec<_>, _> = args.iter().map(|x| expr(x, sc)).collect();
                        return Ok(Expr::Prim(p, a?));
                    }
                    err(line, format!("unknown function '{name}'"))
                }
            }
        }
    }
}

pub fn compile(src: &str) -> Result<Program, LangError> {
    let forms = read(src)?;
    let mut funcs_idx: HashMap<String, (usize, usize)> = HashMap::new();
    let mut globals_idx: HashMap<String, usize> = HashMap::new();
    let mut global_names = Vec::new();
    let mut fn_forms: Vec<(&Vec<Sx>, usize)> = Vec::new();
    for f in &forms {
        if let Sx::List(items, line) = f {
            match items.first() {
                Some(Sx::Sym(h, _)) if h == "fn" => {
                    let Some(Sx::List(sig, _)) = items.get(1) else {
                        return err(*line, "fn needs (fn (name params...) body...)");
                    };
                    let name = sig.first().map(sym).transpose()?.ok_or(LangError {
                        line: *line,
                        msg: "fn needs a name".into(),
                    })?;
                    if funcs_idx.contains_key(name) || prim_of(name).is_some() {
                        return err(*line, format!("function '{name}' is already defined or is a builtin"));
                    }
                    funcs_idx.insert(name.to_string(), (funcs_idx.len(), sig.len() - 1));
                    fn_forms.push((items, *line));
                }
                Some(Sx::Sym(h, _)) if h == "def" => {
                    if items.len() != 3 {
                        return err(*line, "def needs (def name value)");
                    }
                    let name = sym(&items[1])?;
                    if !globals_idx.contains_key(name) {
                        globals_idx.insert(name.to_string(), global_names.len());
                        global_names.push(name.to_string());
                    }
                }
                _ => {}
            }
        }
    }
    let mut funcs = Vec::new();
    for (items, line) in fn_forms {
        let Sx::List(sig, _) = &items[1] else { unreachable!() };
        let name = sym(&sig[0])?.to_string();
        let mut sc = Scope {
            funcs: &funcs_idx,
            globals: &globals_idx,
            vars: Vec::new(),
            next: 0,
            max: 0,
        };
        for p in &sig[1..] {
            let pn = sym(p)?;
            if sc.vars.iter().any(|(n, _)| n == pn) {
                return err(line, format!("duplicate parameter '{pn}'"));
            }
            sc.declare(pn);
        }
        let b = body(&items[2..], &mut sc, line)?;
        funcs.push(Func {
            name,
            nparams: sig.len() - 1,
            nslots: sc.max,
            body: b,
        });
    }
    let mut sc = Scope {
        funcs: &funcs_idx,
        globals: &globals_idx,
        vars: Vec::new(),
        next: 0,
        max: 0,
    };
    let mut main_body = Vec::new();
    for f in &forms {
        if let Sx::List(items, _) = f {
            match items.first() {
                Some(Sx::Sym(h, _)) if h == "fn" => continue,
                Some(Sx::Sym(h, _)) if h == "def" => {
                    let g = globals_idx[sym(&items[1])?];
                    main_body.push(Expr::SetGlobal(g, Box::new(expr(&items[2], &mut sc)?)));
                    continue;
                }
                _ => {}
            }
        }
        main_body.push(expr(f, &mut sc)?);
    }
    let main = Func {
        name: "<main>".into(),
        nparams: 0,
        nslots: sc.max,
        body: main_body,
    };
    // keep funcs ordered by index
    let mut ordered = funcs;
    let mut order: Vec<(usize, String)> = funcs_idx.iter().map(|(n, (i, _))| (*i, n.clone())).collect();
    order.sort();
    ordered.sort_by_key(|f| order.iter().position(|(_, n)| *n == f.name).unwrap());
    Ok(Program {
        funcs: ordered,
        globals: global_names,
        main,
    })
}
