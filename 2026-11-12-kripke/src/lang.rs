//! Lexer, AST and recursive-descent parser for the SMV-style input language.

use std::fmt;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Default)]
pub struct Pos {
    pub line: u32,
    pub col: u32,
}

#[derive(Clone, Debug)]
pub struct Error {
    pub pos: Pos,
    pub msg: String,
}

impl Error {
    pub fn new(pos: Pos, msg: impl Into<String>) -> Error {
        Error { pos, msg: msg.into() }
    }

    /// Render with the offending source line and a caret.
    pub fn render(&self, src: &str, file: &str) -> String {
        let mut s = format!("{}:{}:{}: error: {}\n", file, self.pos.line, self.pos.col, self.msg);
        if self.pos.line >= 1 {
            if let Some(line) = src.lines().nth(self.pos.line as usize - 1) {
                s.push_str(&format!("  {}\n  {}^\n", line, " ".repeat(self.pos.col.saturating_sub(1) as usize)));
            }
        }
        s
    }
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(f, "{}:{}: {}", self.pos.line, self.pos.col, self.msg)
    }
}

pub type Res<T> = Result<T, Error>;

// ------------------------------------------------------------------------------------------ AST

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum BinOp {
    And,
    Or,
    Xor,
    Imp,
    Iff,
    Eq,
    Ne,
    Lt,
    Le,
    Gt,
    Ge,
    Add,
    Sub,
    Mul,
    Div,
    Mod,
    In,
    // LTL binary
    Until,
    Release,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum UnOp {
    Not,
    Neg,
    // CTL
    EX,
    AX,
    EF,
    AF,
    EG,
    AG,
    // LTL
    X,
    F,
    G,
}

#[derive(Clone, Debug)]
pub struct Expr {
    pub k: Ek,
    pub pos: Pos,
}

#[derive(Clone, Debug)]
pub enum Ek {
    Int(i64),
    Bool(bool),
    Id(String),
    Next(Box<Expr>),
    Un(UnOp, Box<Expr>),
    Bin(BinOp, Box<Expr>, Box<Expr>),
    Case(Vec<(Expr, Expr)>),
    Set(Vec<Expr>),
    /// `E[a U b]` / `A[a U b]`
    EU(Box<Expr>, Box<Expr>),
    AU(Box<Expr>, Box<Expr>),
}

#[derive(Clone, Debug, PartialEq)]
pub enum Ty {
    Bool,
    Range(i64, i64),
    Enum(Vec<String>),
}

#[derive(Clone, Debug)]
pub struct VarDecl {
    pub name: String,
    pub ty: Ty,
    pub input: bool,
    pub pos: Pos,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum AssignKind {
    Init,
    Next,
    Plain,
}

#[derive(Clone, Debug)]
pub struct Assign {
    pub kind: AssignKind,
    pub var: String,
    pub expr: Expr,
    pub pos: Pos,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SpecKind {
    Ctl,
    Ltl,
    Invar,
}

#[derive(Clone, Debug)]
pub struct Spec {
    pub kind: SpecKind,
    pub name: Option<String>,
    pub expr: Expr,
    pub pos: Pos,
}

#[derive(Clone, Debug, Default)]
pub struct Program {
    pub vars: Vec<VarDecl>,
    pub defines: Vec<(String, Expr, Pos)>,
    pub inits: Vec<Expr>,
    pub invars: Vec<Expr>,
    pub transes: Vec<Expr>,
    pub assigns: Vec<Assign>,
    pub fairness: Vec<Expr>,
    pub specs: Vec<Spec>,
}

// -------------------------------------------------------------------------------------- printing

fn prec(e: &Expr) -> u8 {
    match &e.k {
        Ek::Bin(op, ..) => match op {
            BinOp::Iff => 1,
            BinOp::Imp => 2,
            BinOp::Or | BinOp::Xor => 3,
            BinOp::And => 4,
            BinOp::Until | BinOp::Release => 5,
            BinOp::Eq | BinOp::Ne | BinOp::Lt | BinOp::Le | BinOp::Gt | BinOp::Ge | BinOp::In => 6,
            BinOp::Add | BinOp::Sub => 7,
            BinOp::Mul | BinOp::Div | BinOp::Mod => 8,
        },
        Ek::Un(..) => 9,
        _ => 10,
    }
}

fn child(e: &Expr, parens: bool) -> String {
    if parens {
        format!("({})", e)
    } else {
        format!("{}", e)
    }
}

impl fmt::Display for Expr {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match &self.k {
            Ek::Int(n) => write!(f, "{}", n),
            Ek::Bool(b) => write!(f, "{}", if *b { "TRUE" } else { "FALSE" }),
            Ek::Id(s) => write!(f, "{}", s),
            Ek::Next(e) => write!(f, "next({})", e),
            Ek::Un(op, e) => {
                let s = match op {
                    UnOp::Not => "!",
                    UnOp::Neg => "-",
                    UnOp::EX => "EX ",
                    UnOp::AX => "AX ",
                    UnOp::EF => "EF ",
                    UnOp::AF => "AF ",
                    UnOp::EG => "EG ",
                    UnOp::AG => "AG ",
                    UnOp::X => "X ",
                    UnOp::F => "F ",
                    UnOp::G => "G ",
                };
                // `!` and `-` take a tight operand; temporal operators read better with a parenthesised body
                let tight = matches!(op, UnOp::Not | UnOp::Neg);
                let p = prec(e);
                let parens = if tight { p < 9 } else { p < 9 };
                write!(f, "{}{}", s, child(e, parens))
            }
            Ek::Bin(op, a, b) => {
                let s = match op {
                    BinOp::And => "&",
                    BinOp::Or => "|",
                    BinOp::Xor => "xor",
                    BinOp::Imp => "->",
                    BinOp::Iff => "<->",
                    BinOp::Eq => "=",
                    BinOp::Ne => "!=",
                    BinOp::Lt => "<",
                    BinOp::Le => "<=",
                    BinOp::Gt => ">",
                    BinOp::Ge => ">=",
                    BinOp::Add => "+",
                    BinOp::Sub => "-",
                    BinOp::Mul => "*",
                    BinOp::Div => "/",
                    BinOp::Mod => "mod",
                    BinOp::In => "in",
                    BinOp::Until => "U",
                    BinOp::Release => "R",
                };
                let p = prec(self);
                // `->` and `U`/`R` associate to the right, everything else to the left; non-associative
                // comparisons and `<->` always parenthesise a same-level child
                let right_assoc = matches!(op, BinOp::Imp | BinOp::Until | BinOp::Release);
                let non_assoc = p == 6 || matches!(op, BinOp::Iff);
                let (pa, pb) = (prec(a), prec(b));
                let lp = if right_assoc || non_assoc { pa <= p } else { pa < p };
                let rp = if right_assoc { pb < p } else { pb <= p };
                write!(f, "{} {} {}", child(a, lp), s, child(b, rp))
            }
            Ek::Case(arms) => {
                write!(f, "case ")?;
                for (c, v) in arms {
                    write!(f, "{} : {}; ", c, v)?;
                }
                write!(f, "esac")
            }
            Ek::Set(es) => {
                write!(f, "{{")?;
                for (i, e) in es.iter().enumerate() {
                    if i > 0 {
                        write!(f, ", ")?;
                    }
                    write!(f, "{}", e)?;
                }
                write!(f, "}}")
            }
            Ek::EU(a, b) => write!(f, "E[{} U {}]", a, b),
            Ek::AU(a, b) => write!(f, "A[{} U {}]", a, b),
        }
    }
}

// -------------------------------------------------------------------------------------- lexer

#[derive(Clone, Debug, PartialEq)]
pub enum Tok {
    Id(String),
    Num(i64),
    Sym(&'static str),
    Eof,
}

#[derive(Clone, Debug)]
pub struct Token {
    pub t: Tok,
    pub pos: Pos,
}

const SYMS: &[&str] = &[
    "<->", ":=", "..", "->", "!=", "<=", ">=", "(", ")", "{", "}", "[", "]", ",", ";", ":", "=", "<", ">", "+", "-", "*", "/", "!", "&", "|",
];

pub fn lex(src: &str) -> Res<Vec<Token>> {
    let cs: Vec<char> = src.chars().collect();
    let mut i = 0;
    let (mut line, mut col) = (1u32, 1u32);
    let mut out = Vec::new();
    macro_rules! adv {
        () => {{
            if cs[i] == '\n' {
                line += 1;
                col = 1;
            } else {
                col += 1;
            }
            i += 1;
        }};
    }
    while i < cs.len() {
        let c = cs[i];
        let pos = Pos { line, col };
        if c.is_whitespace() {
            adv!();
        } else if c == '-' && i + 1 < cs.len() && cs[i + 1] == '-' {
            while i < cs.len() && cs[i] != '\n' {
                adv!();
            }
        } else if c.is_ascii_digit() {
            let mut n: i64 = 0;
            while i < cs.len() && cs[i].is_ascii_digit() {
                n = n
                    .checked_mul(10)
                    .and_then(|n| n.checked_add(cs[i] as i64 - '0' as i64))
                    .ok_or_else(|| Error::new(pos, "integer literal too large"))?;
                adv!();
            }
            out.push(Token { t: Tok::Num(n), pos });
        } else if c.is_alphabetic() || c == '_' {
            let mut s = String::new();
            while i < cs.len() && (cs[i].is_alphanumeric() || cs[i] == '_' || cs[i] == '$' || cs[i] == '#') {
                s.push(cs[i]);
                adv!();
            }
            out.push(Token { t: Tok::Id(s), pos });
        } else {
            let mut matched = None;
            for s in SYMS {
                let sc: Vec<char> = s.chars().collect();
                if i + sc.len() <= cs.len() && cs[i..i + sc.len()] == sc[..] {
                    matched = Some(*s);
                    break;
                }
            }
            match matched {
                Some(s) => {
                    for _ in 0..s.chars().count() {
                        adv!();
                    }
                    out.push(Token { t: Tok::Sym(s), pos });
                }
                None => return Err(Error::new(pos, format!("unexpected character '{}'", c))),
            }
        }
    }
    out.push(Token { t: Tok::Eof, pos: Pos { line, col } });
    Ok(out)
}

// -------------------------------------------------------------------------------------- parser

const SECTIONS: &[&str] = &[
    "MODULE", "VAR", "IVAR", "DEFINE", "INIT", "INVAR", "TRANS", "ASSIGN", "FAIRNESS", "JUSTICE", "SPEC", "CTLSPEC", "LTLSPEC",
    "INVARSPEC",
];

const RESERVED: &[&str] = &[
    "MODULE", "VAR", "IVAR", "DEFINE", "INIT", "INVAR", "TRANS", "ASSIGN", "FAIRNESS", "JUSTICE", "SPEC", "CTLSPEC", "LTLSPEC",
    "INVARSPEC", "TRUE", "FALSE", "case", "esac", "next", "init", "boolean", "mod", "xor", "in", "EX", "AX", "EF", "AF", "EG", "AG", "E",
    "A", "X", "F", "G", "U", "R", "NAME",
];

pub fn is_reserved(s: &str) -> bool {
    RESERVED.contains(&s)
}

struct Parser {
    toks: Vec<Token>,
    p: usize,
    /// While true, a bare `U` is *not* consumed as the LTL until operator (inside `E[ .. U .. ]`).
    no_until: bool,
    depth: usize,
}

/// Maximum syntactic nesting (parentheses, unary operators, right-associative chains).
const MAX_DEPTH: usize = 2000;

pub fn parse(src: &str) -> Res<Program> {
    let toks = lex(src)?;
    let mut p = Parser { toks, p: 0, no_until: false, depth: 0 };
    p.program()
}

/// Parse a single expression (used by tests and the CLI `--spec` flag).
pub fn parse_expr(src: &str) -> Res<Expr> {
    let toks = lex(src)?;
    let mut p = Parser { toks, p: 0, no_until: false, depth: 0 };
    let e = p.expr()?;
    if p.peek() != &Tok::Eof {
        return Err(Error::new(p.pos(), "unexpected trailing input"));
    }
    Ok(e)
}

impl Parser {
    fn peek(&self) -> &Tok {
        &self.toks[self.p].t
    }

    fn peek_at(&self, k: usize) -> &Tok {
        &self.toks[(self.p + k).min(self.toks.len() - 1)].t
    }

    fn pos(&self) -> Pos {
        self.toks[self.p].pos
    }

    fn bump(&mut self) -> Token {
        let t = self.toks[self.p].clone();
        if self.p + 1 < self.toks.len() {
            self.p += 1;
        }
        t
    }

    fn is_sym(&self, s: &str) -> bool {
        matches!(self.peek(), Tok::Sym(x) if *x == s)
    }

    fn is_kw(&self, s: &str) -> bool {
        matches!(self.peek(), Tok::Id(x) if x == s)
    }

    fn eat_sym(&mut self, s: &str) -> bool {
        if self.is_sym(s) {
            self.bump();
            true
        } else {
            false
        }
    }

    fn eat_kw(&mut self, s: &str) -> bool {
        if self.is_kw(s) {
            self.bump();
            true
        } else {
            false
        }
    }

    fn describe(&self) -> String {
        match self.peek() {
            Tok::Id(s) => format!("'{}'", s),
            Tok::Num(n) => format!("'{}'", n),
            Tok::Sym(s) => format!("'{}'", s),
            Tok::Eof => "end of input".to_string(),
        }
    }

    fn expect_sym(&mut self, s: &str) -> Res<()> {
        if self.eat_sym(s) {
            Ok(())
        } else {
            Err(Error::new(self.pos(), format!("expected '{}', found {}", s, self.describe())))
        }
    }

    fn expect_kw(&mut self, s: &str) -> Res<()> {
        if self.eat_kw(s) {
            Ok(())
        } else {
            Err(Error::new(self.pos(), format!("expected '{}', found {}", s, self.describe())))
        }
    }

    fn ident(&mut self) -> Res<(String, Pos)> {
        let pos = self.pos();
        match self.peek().clone() {
            Tok::Id(s) if !is_reserved(&s) => {
                self.bump();
                Ok((s, pos))
            }
            Tok::Id(s) => Err(Error::new(pos, format!("'{}' is a reserved word and cannot be used as a name", s))),
            _ => Err(Error::new(pos, format!("expected an identifier, found {}", self.describe()))),
        }
    }

    fn at_section(&self) -> bool {
        matches!(self.peek(), Tok::Id(s) if SECTIONS.contains(&s.as_str())) || self.peek() == &Tok::Eof
    }

    fn program(&mut self) -> Res<Program> {
        let mut prog = Program::default();
        if self.eat_kw("MODULE") {
            let (n, pos) = self.ident()?;
            if n != "main" {
                return Err(Error::new(pos, "only 'MODULE main' is supported (flat models)"));
            }
        }
        while self.peek() != &Tok::Eof {
            let pos = self.pos();
            let kw = match self.peek().clone() {
                Tok::Id(s) if SECTIONS.contains(&s.as_str()) => s,
                _ => return Err(Error::new(pos, format!("expected a section keyword (VAR, INIT, TRANS, SPEC, ...), found {}", self.describe()))),
            };
            self.bump();
            match kw.as_str() {
                "MODULE" => return Err(Error::new(pos, "only a single MODULE is supported")),
                "VAR" | "IVAR" => {
                    while !self.at_section() {
                        let (name, npos) = self.ident()?;
                        self.expect_sym(":")?;
                        let ty = self.ty()?;
                        self.expect_sym(";")?;
                        prog.vars.push(VarDecl { name, ty, input: kw == "IVAR", pos: npos });
                    }
                }
                "DEFINE" => {
                    while !self.at_section() {
                        let (name, npos) = self.ident()?;
                        self.expect_sym(":=")?;
                        let e = self.expr()?;
                        self.expect_sym(";")?;
                        prog.defines.push((name, e, npos));
                    }
                }
                "ASSIGN" => {
                    while !self.at_section() {
                        let apos = self.pos();
                        let (kind, var) = if self.is_kw("init") || self.is_kw("next") {
                            let k = if self.is_kw("init") { AssignKind::Init } else { AssignKind::Next };
                            self.bump();
                            self.expect_sym("(")?;
                            let (v, _) = self.ident()?;
                            self.expect_sym(")")?;
                            (k, v)
                        } else {
                            (AssignKind::Plain, self.ident()?.0)
                        };
                        self.expect_sym(":=")?;
                        let e = self.expr()?;
                        self.expect_sym(";")?;
                        prog.assigns.push(Assign { kind, var, expr: e, pos: apos });
                    }
                }
                "INIT" => {
                    prog.inits.push(self.expr()?);
                    self.eat_sym(";");
                }
                "INVAR" => {
                    prog.invars.push(self.expr()?);
                    self.eat_sym(";");
                }
                "TRANS" => {
                    prog.transes.push(self.expr()?);
                    self.eat_sym(";");
                }
                "FAIRNESS" | "JUSTICE" => {
                    prog.fairness.push(self.expr()?);
                    self.eat_sym(";");
                }
                "SPEC" | "CTLSPEC" | "LTLSPEC" | "INVARSPEC" => {
                    let name = if self.eat_kw("NAME") {
                        let (n, _) = self.ident()?;
                        self.expect_sym(":=")?;
                        Some(n)
                    } else {
                        None
                    };
                    let e = self.expr()?;
                    self.eat_sym(";");
                    let kind = match kw.as_str() {
                        "LTLSPEC" => SpecKind::Ltl,
                        "INVARSPEC" => SpecKind::Invar,
                        _ => SpecKind::Ctl,
                    };
                    prog.specs.push(Spec { kind, name, expr: e, pos });
                }
                _ => unreachable!(),
            }
        }
        Ok(prog)
    }

    fn ty(&mut self) -> Res<Ty> {
        if self.eat_kw("boolean") {
            return Ok(Ty::Bool);
        }
        if self.eat_sym("{") {
            let mut names = Vec::new();
            loop {
                let (n, pos) = self.ident()?;
                if names.contains(&n) {
                    return Err(Error::new(pos, format!("duplicate enum value '{}'", n)));
                }
                names.push(n);
                if !self.eat_sym(",") {
                    break;
                }
            }
            self.expect_sym("}")?;
            if names.len() < 2 {
                return Err(Error::new(self.pos(), "an enum needs at least two values"));
            }
            return Ok(Ty::Enum(names));
        }
        let pos = self.pos();
        let lo = self.signed_num()?;
        self.expect_sym("..")?;
        let hi = self.signed_num()?;
        if hi < lo {
            return Err(Error::new(pos, format!("empty range {}..{}", lo, hi)));
        }
        if hi - lo > 1 << 20 {
            return Err(Error::new(pos, "range too large (max 2^20 values)"));
        }
        Ok(Ty::Range(lo, hi))
    }

    fn signed_num(&mut self) -> Res<i64> {
        let neg = self.eat_sym("-");
        match self.peek().clone() {
            Tok::Num(n) => {
                self.bump();
                Ok(if neg { -n } else { n })
            }
            _ => Err(Error::new(self.pos(), format!("expected a number, found {}", self.describe()))),
        }
    }

    // ---- expressions: iff < imp < or/xor < and < until < comparison < additive < multiplicative < unary

    fn mk(&self, k: Ek, pos: Pos) -> Expr {
        Expr { k, pos }
    }

    fn enter(&mut self) -> Res<()> {
        self.depth += 1;
        if self.depth > MAX_DEPTH {
            return Err(Error::new(self.pos(), format!("expression nested too deeply (limit {})", MAX_DEPTH)));
        }
        Ok(())
    }

    pub fn expr(&mut self) -> Res<Expr> {
        self.enter()?;
        let r = self.expr_inner();
        self.depth -= 1;
        r
    }

    fn expr_inner(&mut self) -> Res<Expr> {
        let mut lhs = self.imp()?;
        while self.is_sym("<->") {
            let pos = self.pos();
            self.bump();
            let rhs = self.imp()?;
            lhs = self.mk(Ek::Bin(BinOp::Iff, Box::new(lhs), Box::new(rhs)), pos);
        }
        Ok(lhs)
    }

    fn imp(&mut self) -> Res<Expr> {
        let lhs = self.or()?;
        if self.is_sym("->") {
            let pos = self.pos();
            self.bump();
            self.enter()?;
            let rhs = self.imp();
            self.depth -= 1;
            let rhs = rhs?;
            return Ok(self.mk(Ek::Bin(BinOp::Imp, Box::new(lhs), Box::new(rhs)), pos));
        }
        Ok(lhs)
    }

    fn or(&mut self) -> Res<Expr> {
        let mut lhs = self.and()?;
        loop {
            let pos = self.pos();
            let op = if self.is_sym("|") {
                BinOp::Or
            } else if self.is_kw("xor") {
                BinOp::Xor
            } else {
                break;
            };
            self.bump();
            let rhs = self.and()?;
            lhs = self.mk(Ek::Bin(op, Box::new(lhs), Box::new(rhs)), pos);
        }
        Ok(lhs)
    }

    fn and(&mut self) -> Res<Expr> {
        let mut lhs = self.until()?;
        while self.is_sym("&") {
            let pos = self.pos();
            self.bump();
            let rhs = self.until()?;
            lhs = self.mk(Ek::Bin(BinOp::And, Box::new(lhs), Box::new(rhs)), pos);
        }
        Ok(lhs)
    }

    fn until(&mut self) -> Res<Expr> {
        let lhs = self.cmp()?;
        let pos = self.pos();
        let op = if !self.no_until && self.is_kw("U") {
            Some(BinOp::Until)
        } else if self.is_kw("R") {
            Some(BinOp::Release)
        } else {
            None
        };
        if let Some(op) = op {
            self.bump();
            self.enter()?;
            let rhs = self.until();
            self.depth -= 1;
            let rhs = rhs?;
            return Ok(self.mk(Ek::Bin(op, Box::new(lhs), Box::new(rhs)), pos));
        }
        Ok(lhs)
    }

    fn cmp(&mut self) -> Res<Expr> {
        let lhs = self.add()?;
        let pos = self.pos();
        let op = match self.peek() {
            Tok::Sym("=") => BinOp::Eq,
            Tok::Sym("!=") => BinOp::Ne,
            Tok::Sym("<") => BinOp::Lt,
            Tok::Sym("<=") => BinOp::Le,
            Tok::Sym(">") => BinOp::Gt,
            Tok::Sym(">=") => BinOp::Ge,
            Tok::Id(s) if s == "in" => BinOp::In,
            _ => return Ok(lhs),
        };
        self.bump();
        let rhs = self.add()?;
        Ok(self.mk(Ek::Bin(op, Box::new(lhs), Box::new(rhs)), pos))
    }

    fn add(&mut self) -> Res<Expr> {
        let mut lhs = self.mul()?;
        loop {
            let pos = self.pos();
            let op = if self.is_sym("+") {
                BinOp::Add
            } else if self.is_sym("-") {
                BinOp::Sub
            } else {
                break;
            };
            self.bump();
            let rhs = self.mul()?;
            lhs = self.mk(Ek::Bin(op, Box::new(lhs), Box::new(rhs)), pos);
        }
        Ok(lhs)
    }

    fn mul(&mut self) -> Res<Expr> {
        let mut lhs = self.unary()?;
        loop {
            let pos = self.pos();
            let op = if self.is_sym("*") {
                BinOp::Mul
            } else if self.is_sym("/") {
                BinOp::Div
            } else if self.is_kw("mod") {
                BinOp::Mod
            } else {
                break;
            };
            self.bump();
            let rhs = self.unary()?;
            lhs = self.mk(Ek::Bin(op, Box::new(lhs), Box::new(rhs)), pos);
        }
        Ok(lhs)
    }

    fn unary(&mut self) -> Res<Expr> {
        self.enter()?;
        let r = self.unary_inner();
        self.depth -= 1;
        r
    }

    fn unary_inner(&mut self) -> Res<Expr> {
        let pos = self.pos();
        let op = match self.peek() {
            Tok::Sym("!") => Some(UnOp::Not),
            Tok::Sym("-") => Some(UnOp::Neg),
            Tok::Id(s) => match s.as_str() {
                "EX" => Some(UnOp::EX),
                "AX" => Some(UnOp::AX),
                "EF" => Some(UnOp::EF),
                "AF" => Some(UnOp::AF),
                "EG" => Some(UnOp::EG),
                "AG" => Some(UnOp::AG),
                "X" => Some(UnOp::X),
                "F" => Some(UnOp::F),
                "G" => Some(UnOp::G),
                _ => None,
            },
            _ => None,
        };
        if let Some(op) = op {
            self.bump();
            // `!` and unary `-` bind tightly; temporal prefix operators take a whole comparison, so that
            // `AG x = 3` means `AG (x = 3)` while `AG p -> q` still means `(AG p) -> q`.
            let temporal = !matches!(op, UnOp::Not | UnOp::Neg);
            let e = if temporal { self.cmp()? } else { self.unary()? };
            return Ok(self.mk(Ek::Un(op, Box::new(e)), pos));
        }
        self.primary()
    }

    fn primary(&mut self) -> Res<Expr> {
        let pos = self.pos();
        match self.peek().clone() {
            Tok::Num(n) => {
                self.bump();
                Ok(self.mk(Ek::Int(n), pos))
            }
            Tok::Sym("(") => {
                self.bump();
                let saved = self.no_until;
                self.no_until = false;
                let e = self.expr()?;
                self.no_until = saved;
                self.expect_sym(")")?;
                Ok(e)
            }
            Tok::Sym("{") => {
                self.bump();
                let mut es = vec![self.expr()?];
                while self.eat_sym(",") {
                    es.push(self.expr()?);
                }
                self.expect_sym("}")?;
                Ok(self.mk(Ek::Set(es), pos))
            }
            Tok::Id(s) => match s.as_str() {
                "TRUE" => {
                    self.bump();
                    Ok(self.mk(Ek::Bool(true), pos))
                }
                "FALSE" => {
                    self.bump();
                    Ok(self.mk(Ek::Bool(false), pos))
                }
                "next" => {
                    self.bump();
                    self.expect_sym("(")?;
                    let saved = self.no_until;
                    self.no_until = false;
                    let e = self.expr()?;
                    self.no_until = saved;
                    self.expect_sym(")")?;
                    Ok(self.mk(Ek::Next(Box::new(e)), pos))
                }
                "case" => {
                    self.bump();
                    let mut arms = Vec::new();
                    while !self.is_kw("esac") {
                        let c = self.expr()?;
                        self.expect_sym(":")?;
                        let v = self.expr()?;
                        self.expect_sym(";")?;
                        arms.push((c, v));
                    }
                    self.bump();
                    if arms.is_empty() {
                        return Err(Error::new(pos, "empty case expression"));
                    }
                    Ok(self.mk(Ek::Case(arms), pos))
                }
                "E" | "A" if matches!(self.peek_at(1), Tok::Sym("[")) => {
                    self.bump();
                    self.bump();
                    let saved = self.no_until;
                    self.no_until = true;
                    let a = self.expr()?;
                    self.no_until = saved;
                    self.expect_kw("U")?;
                    let saved = self.no_until;
                    self.no_until = false;
                    let b = self.expr()?;
                    self.no_until = saved;
                    self.expect_sym("]")?;
                    let k = if s == "E" { Ek::EU(Box::new(a), Box::new(b)) } else { Ek::AU(Box::new(a), Box::new(b)) };
                    Ok(self.mk(k, pos))
                }
                _ if is_reserved(&s) => Err(Error::new(pos, format!("unexpected keyword '{}' in expression", s))),
                _ => {
                    self.bump();
                    Ok(self.mk(Ek::Id(s), pos))
                }
            },
            _ => Err(Error::new(pos, format!("expected an expression, found {}", self.describe()))),
        }
    }
}

impl Expr {
    /// Does the expression contain any temporal operator?
    pub fn is_temporal(&self) -> bool {
        match &self.k {
            Ek::Int(_) | Ek::Bool(_) | Ek::Id(_) => false,
            Ek::Next(e) => e.is_temporal(),
            Ek::Un(op, e) => {
                matches!(op, UnOp::EX | UnOp::AX | UnOp::EF | UnOp::AF | UnOp::EG | UnOp::AG | UnOp::X | UnOp::F | UnOp::G) || e.is_temporal()
            }
            Ek::Bin(op, a, b) => matches!(op, BinOp::Until | BinOp::Release) || a.is_temporal() || b.is_temporal(),
            Ek::Case(arms) => arms.iter().any(|(c, v)| c.is_temporal() || v.is_temporal()),
            Ek::Set(es) => es.iter().any(|e| e.is_temporal()),
            Ek::EU(..) | Ek::AU(..) => true,
        }
    }
}
