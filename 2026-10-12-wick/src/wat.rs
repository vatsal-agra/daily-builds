//! WebAssembly text format (WAT): lexer, s-expression parser, name resolution, assembler to `Module`.
//! Supports flat and folded instruction syntax, `$identifiers`, inline import/export abbreviations,
//! hex/decimal/hex-float literals, string escapes, nested block comments.
use crate::ast::*;
use crate::num;
use std::collections::HashMap;

#[derive(Debug, Clone, PartialEq)]
pub struct WatError {
    pub line: usize,
    pub col: usize,
    pub msg: String,
}
impl std::fmt::Display for WatError {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "{}:{}: {}", self.line, self.col, self.msg)
    }
}
impl std::error::Error for WatError {}

type R<T> = Result<T, WatError>;

#[derive(Clone, Copy, Debug, Default)]
struct Pos {
    line: usize,
    col: usize,
}

#[derive(Clone, Debug)]
enum Node {
    Atom(String, Pos),
    Str(Vec<u8>, Pos),
    List(Vec<Node>, Pos),
}

impl Node {
    fn pos(&self) -> Pos {
        match self {
            Node::Atom(_, p) | Node::Str(_, p) | Node::List(_, p) => *p,
        }
    }
    fn atom(&self) -> Option<&str> {
        if let Node::Atom(s, _) = self { Some(s) } else { None }
    }
    /// Head keyword of a list, e.g. `param` for `(param i32)`.
    fn head(&self) -> Option<&str> {
        if let Node::List(l, _) = self {
            l.first().and_then(|n| n.atom())
        } else {
            None
        }
    }
}

fn err<T>(p: Pos, msg: impl Into<String>) -> R<T> {
    Err(WatError { line: p.line, col: p.col, msg: msg.into() })
}

// ---------------------------------------------------------------- lexer / s-expr parser

struct Lexer<'a> {
    s: &'a [u8],
    i: usize,
    line: usize,
    col: usize,
}

impl<'a> Lexer<'a> {
    fn pos(&self) -> Pos {
        Pos { line: self.line, col: self.col }
    }
    fn bump(&mut self) -> Option<u8> {
        let c = *self.s.get(self.i)?;
        self.i += 1;
        if c == b'\n' {
            self.line += 1;
            self.col = 1;
        } else {
            self.col += 1;
        }
        Some(c)
    }
    fn peek(&self) -> Option<u8> {
        self.s.get(self.i).copied()
    }
    fn skip_ws(&mut self) -> R<()> {
        loop {
            match self.peek() {
                Some(b' ') | Some(b'\t') | Some(b'\n') | Some(b'\r') => {
                    self.bump();
                }
                Some(b';') if self.s.get(self.i + 1) == Some(&b';') => {
                    while let Some(c) = self.peek() {
                        if c == b'\n' {
                            break;
                        }
                        self.bump();
                    }
                }
                Some(b'(') if self.s.get(self.i + 1) == Some(&b';') => {
                    let start = self.pos();
                    self.bump();
                    self.bump();
                    let mut depth = 1;
                    while depth > 0 {
                        match (self.peek(), self.s.get(self.i + 1)) {
                            (None, _) => return err(start, "unterminated block comment"),
                            (Some(b'('), Some(b';')) => {
                                self.bump();
                                self.bump();
                                depth += 1;
                            }
                            (Some(b';'), Some(b')')) => {
                                self.bump();
                                self.bump();
                                depth -= 1;
                            }
                            _ => {
                                self.bump();
                            }
                        }
                    }
                }
                _ => return Ok(()),
            }
        }
    }

    fn string(&mut self) -> R<Vec<u8>> {
        let start = self.pos();
        self.bump(); // opening quote
        let mut out = vec![];
        loop {
            let p = self.pos();
            match self.bump() {
                None => return err(start, "unterminated string literal"),
                Some(b'"') => return Ok(out),
                Some(b'\n') => return err(p, "newline in string literal"),
                Some(b'\\') => match self.bump() {
                    Some(b'n') => out.push(b'\n'),
                    Some(b't') => out.push(b'\t'),
                    Some(b'r') => out.push(b'\r'),
                    Some(b'\\') => out.push(b'\\'),
                    Some(b'"') => out.push(b'"'),
                    Some(b'\'') => out.push(b'\''),
                    Some(b'u') => {
                        if self.bump() != Some(b'{') {
                            return err(p, "expected `{` after \\u");
                        }
                        let mut hex = String::new();
                        loop {
                            match self.bump() {
                                Some(b'}') => break,
                                Some(c) if c.is_ascii_hexdigit() => hex.push(c as char),
                                _ => return err(p, "malformed \\u{...} escape"),
                            }
                        }
                        let cp = u32::from_str_radix(&hex, 16).ok().and_then(char::from_u32);
                        match cp {
                            Some(ch) => {
                                let mut b = [0u8; 4];
                                out.extend_from_slice(ch.encode_utf8(&mut b).as_bytes());
                            }
                            None => return err(p, "invalid unicode scalar in \\u{...}"),
                        }
                    }
                    Some(h1) if h1.is_ascii_hexdigit() => match self.bump() {
                        Some(h2) if h2.is_ascii_hexdigit() => {
                            let v = (hexval(h1) << 4) | hexval(h2);
                            out.push(v);
                        }
                        _ => return err(p, "malformed \\hh escape"),
                    },
                    _ => return err(p, "invalid escape sequence in string"),
                },
                Some(c) => out.push(c),
            }
        }
    }

    fn parse_list(&mut self, open: Pos) -> R<Vec<Node>> {
        let mut items = vec![];
        loop {
            self.skip_ws()?;
            let p = self.pos();
            match self.peek() {
                None => return err(open, "unclosed `(`"),
                Some(b')') => {
                    self.bump();
                    return Ok(items);
                }
                Some(b'(') => {
                    self.bump();
                    let inner = self.parse_list(p)?;
                    items.push(Node::List(inner, p));
                }
                Some(b'"') => {
                    let s = self.string()?;
                    items.push(Node::Str(s, p));
                }
                Some(_) => {
                    let mut a = String::new();
                    while let Some(c) = self.peek() {
                        if c.is_ascii_whitespace() || matches!(c, b'(' | b')' | b'"') || (c == b';' && self.s.get(self.i + 1) == Some(&b';')) {
                            break;
                        }
                        a.push(c as char);
                        self.bump();
                    }
                    if a.is_empty() {
                        return err(p, "unexpected character");
                    }
                    items.push(Node::Atom(a, p));
                }
            }
        }
    }
}

fn hexval(c: u8) -> u8 {
    (c as char).to_digit(16).unwrap() as u8
}

fn lex(src: &str) -> R<Vec<Node>> {
    let mut lx = Lexer { s: src.as_bytes(), i: 0, line: 1, col: 1 };
    let mut top = vec![];
    loop {
        lx.skip_ws()?;
        let p = lx.pos();
        match lx.peek() {
            None => return Ok(top),
            Some(b'(') => {
                lx.bump();
                let l = lx.parse_list(p)?;
                top.push(Node::List(l, p));
            }
            Some(b')') => return err(p, "unexpected `)`"),
            Some(b'"') => return err(p, "unexpected string at top level"),
            Some(_) => {
                let mut a = String::new();
                while let Some(c) = lx.peek() {
                    if c.is_ascii_whitespace() || c == b'(' || c == b')' {
                        break;
                    }
                    a.push(c as char);
                    lx.bump();
                }
                top.push(Node::Atom(a, p));
            }
        }
    }
}

// ---------------------------------------------------------------- numeric literals

/// Parse an integer literal into `bits` bits (two's complement). Accepts `-`/`+`, `_` separators and `0x`.
/// A literal is accepted if it fits either as a signed or as an unsigned `bits`-bit value.
pub fn parse_int(s: &str, bits: u32) -> Option<u64> {
    let (neg, body) = match s.as_bytes().first()? {
        b'-' => (true, &s[1..]),
        b'+' => (false, &s[1..]),
        _ => (false, s),
    };
    let (radix, digits) = if let Some(h) = body.strip_prefix("0x").or_else(|| body.strip_prefix("0X")) { (16, h) } else { (10, body) };
    if digits.is_empty() || digits.starts_with('_') || digits.ends_with('_') || digits.contains("__") {
        return None;
    }
    let mut mag: u128 = 0;
    for c in digits.chars() {
        if c == '_' {
            continue;
        }
        let d = c.to_digit(radix)? as u128;
        mag = mag.checked_mul(radix as u128)?.checked_add(d)?;
        if mag > u64::MAX as u128 + 1 {
            return None;
        }
    }
    if neg {
        if mag > 1u128 << (bits - 1) {
            return None;
        }
        Some((mag as u64).wrapping_neg() & mask(bits))
    } else {
        if mag > (1u128 << bits) - 1 {
            return None;
        }
        Some(mag as u64)
    }
}

fn mask(bits: u32) -> u64 {
    if bits == 64 { u64::MAX } else { (1u64 << bits) - 1 }
}

/// Parse a float literal and return its IEEE-754 bit pattern (32 or 64 bits wide).
/// Supports decimal, hex floats (`0x1.8p3`), `inf`, `nan`, and `nan:0xPAYLOAD`.
pub fn parse_float(s: &str, is32: bool) -> Option<u64> {
    let (neg, body) = match s.as_bytes().first()? {
        b'-' => (true, &s[1..]),
        b'+' => (false, &s[1..]),
        _ => (false, s),
    };
    let sign32 = (neg as u64) << 31;
    let sign64 = (neg as u64) << 63;
    if body == "inf" {
        return Some(if is32 { sign32 | 0x7f80_0000 } else { sign64 | 0x7ff0_0000_0000_0000 });
    }
    if body == "nan" {
        return Some(if is32 { sign32 | 0x7fc0_0000 } else { sign64 | 0x7ff8_0000_0000_0000 });
    }
    if let Some(p) = body.strip_prefix("nan:0x") {
        let payload = u64::from_str_radix(&p.replace('_', ""), 16).ok()?;
        if payload == 0 {
            return None;
        }
        return if is32 {
            if payload >= 1 << 23 { None } else { Some(sign32 | 0x7f80_0000 | payload) }
        } else if payload >= 1 << 52 {
            None
        } else {
            Some(sign64 | 0x7ff0_0000_0000_0000 | payload)
        };
    }
    if body.is_empty() || body.starts_with('_') || body.ends_with('_') || body.contains("__") {
        return None;
    }
    let clean = body.replace('_', "");
    let v: f64 = if let Some(h) = clean.strip_prefix("0x").or_else(|| clean.strip_prefix("0X")) {
        parse_hex_float(h)?
    } else {
        // Rust's float parser is correctly rounded; parse directly in the target width.
        if !clean.chars().next()?.is_ascii_digit() {
            return None;
        }
        if clean.chars().any(|c| !(c.is_ascii_digit() || matches!(c, '.' | 'e' | 'E' | '+' | '-'))) {
            return None;
        }
        if is32 {
            let f: f32 = clean.parse().ok()?;
            let b = f.to_bits() as u64 | sign32;
            return Some(b);
        }
        clean.parse().ok()?
    };
    if is32 {
        Some((v as f32).to_bits() as u64 | sign32)
    } else {
        Some(v.to_bits() | sign64)
    }
}

fn parse_hex_float(h: &str) -> Option<f64> {
    let (mant, exp) = match h.find(|c| c == 'p' || c == 'P') {
        Some(i) => (&h[..i], h[i + 1..].parse::<i32>().ok()?),
        None => (h, 0),
    };
    let (ip, fp) = match mant.find('.') {
        Some(i) => (&mant[..i], &mant[i + 1..]),
        None => (mant, ""),
    };
    if ip.is_empty() && fp.is_empty() {
        return None;
    }
    let mut m: u64 = 0;
    let mut sticky = false;
    let mut scale: i32 = 0; // power-of-two adjustment for digits dropped / fractional digits
    for c in ip.chars() {
        let d = c.to_digit(16)? as u64;
        if m >> 60 == 0 {
            m = m * 16 + d;
        } else {
            sticky |= d != 0;
            scale += 4;
        }
    }
    for c in fp.chars() {
        let d = c.to_digit(16)? as u64;
        if m >> 60 == 0 {
            m = m * 16 + d;
            scale -= 4;
        } else {
            sticky |= d != 0;
        }
    }
    if sticky {
        m |= 1;
    }
    let mut v = m as f64;
    let mut e = exp + scale;
    while e > 0 {
        let step = e.min(1000);
        v *= 2f64.powi(step);
        e -= step;
    }
    while e < 0 {
        let step = (-e).min(1000);
        v /= 2f64.powi(step);
        e += step;
    }
    Some(v)
}

// ---------------------------------------------------------------- builder

#[derive(Default)]
struct Names {
    types: HashMap<String, u32>,
    funcs: HashMap<String, u32>,
    tables: HashMap<String, u32>,
    mems: HashMap<String, u32>,
    globals: HashMap<String, u32>,
}

struct FnCtx {
    locals: HashMap<String, u32>,
    labels: Vec<Option<String>>,
}

struct B {
    m: Module,
    names: Names,
}

fn declare(map: &mut HashMap<String, u32>, id: &str, idx: u32, p: Pos) -> R<()> {
    if map.insert(id.to_string(), idx).is_some() {
        return err(p, format!("duplicate identifier {id}"));
    }
    Ok(())
}

fn lookup(map: &HashMap<String, u32>, a: &str, what: &str, p: Pos) -> R<u32> {
    if a.starts_with('$') {
        map.get(a).copied().ok_or(()).or_else(|_| err(p, format!("unknown {what} {a}")))
    } else {
        match parse_int(a, 32) {
            Some(v) => Ok(v as u32),
            None => err(p, format!("expected {what} index or $name, found `{a}`")),
        }
    }
}

fn expect_atom(n: &Node, what: &str) -> R<String> {
    match n {
        Node::Atom(s, _) => Ok(s.clone()),
        other => err(other.pos(), format!("expected {what}")),
    }
}

fn expect_str(n: &Node, what: &str) -> R<String> {
    match n {
        Node::Str(s, p) => String::from_utf8(s.clone()).or_else(|_| err(*p, format!("{what} must be valid UTF-8"))),
        other => err(other.pos(), format!("expected string for {what}")),
    }
}

fn valtype(n: &Node) -> R<ValType> {
    match n {
        Node::Atom(s, p) => ValType::parse(s).ok_or(()).or_else(|_| err(*p, format!("unknown value type `{s}`"))),
        other => err(other.pos(), "expected value type"),
    }
}

fn limits(items: &[Node], p: Pos) -> R<(Limits, usize)> {
    let num = |n: Option<&Node>| -> Option<u32> { n.and_then(|n| n.atom()).and_then(|a| parse_int(a, 32)).map(|v| v as u32) };
    let min = match num(items.first()) {
        Some(v) => v,
        None => return err(items.first().map(|n| n.pos()).unwrap_or(p), "expected limits (minimum size)"),
    };
    match num(items.get(1)) {
        Some(max) => Ok((Limits { min, max: Some(max) }, 2)),
        None => Ok((Limits { min, max: None }, 1)),
    }
}

/// Parsed header of a func/import: type use and bound param names.
struct TypeUse {
    idx: u32,
    param_names: Vec<Option<String>>,
}

impl B {
    fn find_or_add_type(&mut self, ft: FuncType) -> u32 {
        if let Some(i) = self.m.types.iter().position(|t| *t == ft) {
            return i as u32;
        }
        self.m.types.push(ft);
        (self.m.types.len() - 1) as u32
    }

    /// Consume `(type X)? (param ..)* (result ..)*` at `items[*i..]`.
    fn typeuse(&mut self, items: &[Node], i: &mut usize) -> R<TypeUse> {
        let mut explicit: Option<u32> = None;
        if let Some(n) = items.get(*i) {
            if n.head() == Some("type") {
                if let Node::List(l, p) = n {
                    if l.len() != 2 {
                        return err(*p, "(type) takes exactly one index");
                    }
                    let a = expect_atom(&l[1], "type index")?;
                    explicit = Some(lookup(&self.names.types, &a, "type", l[1].pos())?);
                    *i += 1;
                }
            }
        }
        let (params, names, results) = self.params_results(items, i)?;
        match explicit {
            Some(t) => {
                if (!params.is_empty() || !results.is_empty()) && (t as usize) < self.m.types.len() {
                    let ft = &self.m.types[t as usize];
                    if ft.params != params || ft.results != results {
                        return err(items.get(*i - 1).map(|n| n.pos()).unwrap_or_default(), "inline signature does not match the referenced type");
                    }
                }
                // Names for params come from the explicit type's arity when no inline params were given.
                let names = if names.is_empty() { vec![None; self.m.types.get(t as usize).map_or(0, |ft| ft.params.len())] } else { names };
                Ok(TypeUse { idx: t, param_names: names })
            }
            None => {
                let idx = self.find_or_add_type(FuncType { params, results });
                Ok(TypeUse { idx, param_names: names })
            }
        }
    }

    fn params_results(&mut self, items: &[Node], i: &mut usize) -> R<(Vec<ValType>, Vec<Option<String>>, Vec<ValType>)> {
        let mut params = vec![];
        let mut names = vec![];
        let mut results = vec![];
        while let Some(n) = items.get(*i) {
            match n.head() {
                Some("param") => {
                    let Node::List(l, p) = n else { unreachable!() };
                    if let Some(Node::Atom(a, _)) = l.get(1) {
                        if a.starts_with('$') {
                            if l.len() != 3 {
                                return err(*p, "a named param declares exactly one type");
                            }
                            params.push(valtype(&l[2])?);
                            names.push(Some(a.clone()));
                            *i += 1;
                            continue;
                        }
                    }
                    for t in &l[1..] {
                        params.push(valtype(t)?);
                        names.push(None);
                    }
                    *i += 1;
                }
                Some("result") => {
                    let Node::List(l, _) = n else { unreachable!() };
                    for t in &l[1..] {
                        results.push(valtype(t)?);
                    }
                    *i += 1;
                }
                _ => break,
            }
        }
        Ok((params, names, results))
    }

    fn block_type(&mut self, items: &[Node], i: &mut usize) -> R<BlockType> {
        let start = *i;
        let has_type = items.get(*i).map_or(false, |n| n.head() == Some("type"));
        let tu = self.typeuse(items, i)?;
        if has_type {
            return Ok(BlockType::Type(tu.idx));
        }
        let ft = self.m.types[tu.idx as usize].clone();
        let consumed = *i > start;
        if !consumed || (ft.params.is_empty() && ft.results.is_empty()) {
            return Ok(BlockType::Empty);
        }
        if ft.params.is_empty() && ft.results.len() == 1 {
            return Ok(BlockType::Val(ft.results[0]));
        }
        Ok(BlockType::Type(tu.idx))
    }

    fn label_depth(&self, fc: &FnCtx, a: &str, p: Pos) -> R<u32> {
        if a.starts_with('$') {
            for (d, l) in fc.labels.iter().rev().enumerate() {
                if l.as_deref() == Some(a) {
                    return Ok(d as u32);
                }
            }
            return err(p, format!("unknown label {a}"));
        }
        match parse_int(a, 32) {
            Some(v) => Ok(v as u32),
            None => err(p, format!("expected label index or $name, found `{a}`")),
        }
    }

    fn instrs(&mut self, items: &[Node], fc: &mut FnCtx, out: &mut Vec<Instr>) -> R<()> {
        let mut i = 0;
        while i < items.len() {
            match &items[i] {
                Node::List(l, p) => {
                    self.folded(l, *p, fc, out)?;
                    i += 1;
                }
                Node::Atom(op, p) => {
                    i = self.plain(op, *p, items, i + 1, fc, out)?;
                }
                Node::Str(_, p) => return err(*p, "unexpected string where an instruction was expected"),
            }
        }
        Ok(())
    }

    fn opt_label(&self, items: &[Node], i: &mut usize) -> Option<String> {
        if let Some(Node::Atom(a, _)) = items.get(*i) {
            if a.starts_with('$') {
                *i += 1;
                return Some(a.clone());
            }
        }
        None
    }

    fn folded(&mut self, l: &[Node], p: Pos, fc: &mut FnCtx, out: &mut Vec<Instr>) -> R<()> {
        let op = match l.first() {
            Some(Node::Atom(a, _)) => a.as_str(),
            _ => return err(p, "expected an instruction keyword after `(`"),
        };
        match op {
            "block" | "loop" => {
                let mut i = 1;
                let label = self.opt_label(l, &mut i);
                let bt = self.block_type(l, &mut i)?;
                out.push(if op == "block" { Instr::Block(bt) } else { Instr::Loop(bt) });
                fc.labels.push(label);
                self.instrs(&l[i..], fc, out)?;
                fc.labels.pop();
                out.push(Instr::End);
            }
            "if" => {
                let mut i = 1;
                let label = self.opt_label(l, &mut i);
                let bt = self.block_type(l, &mut i)?;
                // condition operands: everything before (then ...)
                while i < l.len() && l[i].head() != Some("then") {
                    match &l[i] {
                        Node::List(inner, ip) => self.folded(inner, *ip, fc, out)?,
                        other => return err(other.pos(), "expected folded condition or (then ...)"),
                    }
                    i += 1;
                }
                out.push(Instr::If(bt));
                fc.labels.push(label);
                match l.get(i) {
                    Some(Node::List(t, _)) if l[i].head() == Some("then") => self.instrs(&t[1..], fc, out)?,
                    _ => return err(p, "`if` is missing its (then ...) branch"),
                }
                i += 1;
                if let Some(n) = l.get(i) {
                    if n.head() == Some("else") {
                        let Node::List(e, _) = n else { unreachable!() };
                        out.push(Instr::Else);
                        self.instrs(&e[1..], fc, out)?;
                        i += 1;
                    }
                }
                if i != l.len() {
                    return err(l[i].pos(), "unexpected item after (then)/(else)");
                }
                fc.labels.pop();
                out.push(Instr::End);
            }
            _ => {
                let mut tmp = vec![];
                let after = self.plain(op, l[0].pos(), l, 1, fc, &mut tmp)?;
                for operand in &l[after..] {
                    match operand {
                        Node::List(inner, ip) => self.folded(inner, *ip, fc, out)?,
                        other => return err(other.pos(), "unexpected token among folded operands"),
                    }
                }
                out.extend(tmp);
            }
        }
        Ok(())
    }

    /// Parse one plain (flat) instruction whose keyword is `op`, immediates at `items[i..]`.
    /// Returns the index after the immediates.
    fn plain(&mut self, op: &str, p: Pos, items: &[Node], mut i: usize, fc: &mut FnCtx, out: &mut Vec<Instr>) -> R<usize> {
        let imm_atom = |i: &mut usize, what: &str| -> R<(String, Pos)> {
            match items.get(*i) {
                Some(Node::Atom(a, ap)) => {
                    *i += 1;
                    Ok((a.clone(), *ap))
                }
                Some(other) => err(other.pos(), format!("expected {what}")),
                None => err(p, format!("`{op}` is missing its {what}")),
            }
        };
        match op {
            "unreachable" => out.push(Instr::Unreachable),
            "nop" => out.push(Instr::Nop),
            "return" => out.push(Instr::Return),
            "drop" => out.push(Instr::Drop),
            "select" => {
                if items.get(i).map_or(false, |n| n.head() == Some("result")) {
                    let Node::List(l, lp) = &items[i] else { unreachable!() };
                    if l.len() != 2 {
                        return err(*lp, "typed select takes exactly one result type");
                    }
                    out.push(Instr::SelectT(valtype(&l[1])?));
                    i += 1;
                } else {
                    out.push(Instr::Select);
                }
            }
            "block" | "loop" | "if" => {
                let label = self.opt_label(items, &mut i);
                let bt = self.block_type(items, &mut i)?;
                out.push(match op {
                    "block" => Instr::Block(bt),
                    "loop" => Instr::Loop(bt),
                    _ => Instr::If(bt),
                });
                fc.labels.push(label);
            }
            "else" => {
                let l = self.opt_label(items, &mut i);
                if let (Some(l), Some(Some(cur))) = (&l, fc.labels.last()) {
                    if l != cur {
                        return err(p, format!("`else {l}` does not match enclosing label {cur}"));
                    }
                }
                if fc.labels.is_empty() {
                    return err(p, "`else` outside of an `if`");
                }
                out.push(Instr::Else);
            }
            "end" => {
                let l = self.opt_label(items, &mut i);
                match fc.labels.pop() {
                    None => return err(p, "`end` without a matching block (the function body's `end` is implicit)"),
                    Some(cur) => {
                        if let (Some(l), Some(cur)) = (&l, &cur) {
                            if l != cur {
                                return err(p, format!("`end {l}` does not match label {cur}"));
                            }
                        }
                    }
                }
                out.push(Instr::End);
            }
            "br" | "br_if" => {
                let (a, ap) = imm_atom(&mut i, "label")?;
                let d = self.label_depth(fc, &a, ap)?;
                out.push(if op == "br" { Instr::Br(d) } else { Instr::BrIf(d) });
            }
            "br_table" => {
                let mut ls = vec![];
                while let Some(Node::Atom(a, ap)) = items.get(i) {
                    ls.push(self.label_depth(fc, a, *ap)?);
                    i += 1;
                }
                let Some(d) = ls.pop() else { return err(p, "br_table needs at least a default label") };
                out.push(Instr::BrTable(ls, d));
            }
            "call" => {
                let (a, ap) = imm_atom(&mut i, "function index")?;
                out.push(Instr::Call(lookup(&self.names.funcs, &a, "function", ap)?));
            }
            "call_indirect" => {
                let mut table = 0;
                if let Some(Node::Atom(a, ap)) = items.get(i) {
                    table = lookup(&self.names.tables, a, "table", *ap)?;
                    i += 1;
                }
                let tu = self.typeuse(items, &mut i)?;
                out.push(Instr::CallIndirect(tu.idx, table));
            }
            "local.get" | "local.set" | "local.tee" => {
                let (a, ap) = imm_atom(&mut i, "local index")?;
                let x = lookup(&fc.locals, &a, "local", ap)?;
                out.push(match op {
                    "local.get" => Instr::LocalGet(x),
                    "local.set" => Instr::LocalSet(x),
                    _ => Instr::LocalTee(x),
                });
            }
            "global.get" | "global.set" => {
                let (a, ap) = imm_atom(&mut i, "global index")?;
                let x = lookup(&self.names.globals, &a, "global", ap)?;
                out.push(if op == "global.get" { Instr::GlobalGet(x) } else { Instr::GlobalSet(x) });
            }
            "memory.size" => out.push(Instr::MemorySize),
            "memory.grow" => out.push(Instr::MemoryGrow),
            "memory.copy" => out.push(Instr::MemoryCopy),
            "memory.fill" => out.push(Instr::MemoryFill),
            "i32.const" => {
                let (a, ap) = imm_atom(&mut i, "i32 literal")?;
                match parse_int(&a, 32) {
                    Some(v) => out.push(Instr::I32Const(v as u32 as i32)),
                    None => return err(ap, format!("invalid or out-of-range i32 literal `{a}`")),
                }
            }
            "i64.const" => {
                let (a, ap) = imm_atom(&mut i, "i64 literal")?;
                match parse_int(&a, 64) {
                    Some(v) => out.push(Instr::I64Const(v as i64)),
                    None => return err(ap, format!("invalid or out-of-range i64 literal `{a}`")),
                }
            }
            "f32.const" => {
                let (a, ap) = imm_atom(&mut i, "f32 literal")?;
                match parse_float(&a, true) {
                    Some(b) => out.push(Instr::F32Const(b as u32)),
                    None => return err(ap, format!("invalid f32 literal `{a}`")),
                }
            }
            "f64.const" => {
                let (a, ap) = imm_atom(&mut i, "f64 literal")?;
                match parse_float(&a, false) {
                    Some(b) => out.push(Instr::F64Const(b)),
                    None => return err(ap, format!("invalid f64 literal `{a}`")),
                }
            }
            _ => {
                if let Some(&(code, _, _, width)) = num::mem_op_by_name(op) {
                    let mut offset: u32 = 0;
                    let mut align = width.trailing_zeros();
                    while let Some(Node::Atom(a, ap)) = items.get(i) {
                        if let Some(v) = a.strip_prefix("offset=") {
                            offset = parse_int(v, 32).ok_or(()).or_else(|_| err(*ap, "invalid offset"))? as u32;
                        } else if let Some(v) = a.strip_prefix("align=") {
                            let n = parse_int(v, 32).ok_or(()).or_else(|_| err(*ap, "invalid alignment"))? as u32;
                            if n == 0 || !n.is_power_of_two() {
                                return err(*ap, "alignment must be a power of two");
                            }
                            align = n.trailing_zeros();
                        } else {
                            break;
                        }
                        i += 1;
                    }
                    out.push(Instr::Mem { op: code, align, offset });
                } else if let Some(n) = num::by_name(op) {
                    out.push(Instr::Num(n.code));
                } else {
                    return err(p, format!("unknown instruction `{op}`"));
                }
            }
        }
        Ok(i)
    }

    fn const_expr(&mut self, items: &[Node], p: Pos) -> R<Vec<Instr>> {
        let mut fc = FnCtx { locals: HashMap::new(), labels: vec![] };
        let mut out = vec![];
        // allow `(offset <expr>)` wrapper
        if items.len() == 1 && items[0].head() == Some("offset") {
            let Node::List(l, _) = &items[0] else { unreachable!() };
            self.instrs(&l[1..], &mut fc, &mut out)?;
        } else {
            self.instrs(items, &mut fc, &mut out)?;
        }
        if out.is_empty() {
            return err(p, "expected a constant expression");
        }
        out.push(Instr::End);
        Ok(out)
    }
}

enum FieldKind {
    Func,
    Table,
    Mem,
    Global,
}

/// Leading `(export "x")` / `(import "m" "n")` sublists (inline abbreviations).
fn inline_ie(items: &[Node], i: &mut usize) -> R<(Vec<String>, Option<(String, String)>)> {
    let mut exports = vec![];
    let mut import = None;
    while let Some(n) = items.get(*i) {
        match n.head() {
            Some("export") => {
                let Node::List(l, p) = n else { unreachable!() };
                if l.len() != 2 {
                    return err(*p, "(export) takes one name");
                }
                exports.push(expect_str(&l[1], "export name")?);
                *i += 1;
            }
            Some("import") => {
                let Node::List(l, p) = n else { unreachable!() };
                if l.len() != 3 {
                    return err(*p, "inline (import) takes module and name");
                }
                import = Some((expect_str(&l[1], "import module")?, expect_str(&l[2], "import name")?));
                *i += 1;
            }
            _ => break,
        }
    }
    Ok((exports, import))
}

pub fn parse_module(src: &str) -> Result<Module, WatError> {
    let top = lex(src)?;
    // Accept either `(module ...)` or a bare list of fields.
    let (fields, mpos): (Vec<Node>, Pos) = if top.len() == 1 && top[0].head() == Some("module") {
        let Node::List(l, p) = &top[0] else { unreachable!() };
        let mut rest = l[1..].to_vec();
        if let Some(Node::Atom(a, _)) = rest.first() {
            if a.starts_with('$') {
                rest.remove(0);
            }
        }
        (rest, *p)
    } else {
        (top.clone(), top.first().map(|n| n.pos()).unwrap_or_default())
    };
    for f in &fields {
        if !matches!(f, Node::List(..)) {
            return err(f.pos(), "expected a module field like (func ...)");
        }
    }
    let mut b = B { m: Module::default(), names: Names::default() };

    // ---- pass 1: types, then index-space names (imports occupy the lowest indices)
    for f in &fields {
        if f.head() == Some("type") {
            let Node::List(l, p) = f else { unreachable!() };
            let mut i = 1;
            if let Some(Node::Atom(a, ap)) = l.get(i) {
                if a.starts_with('$') {
                    declare(&mut b.names.types, a, b.m.types.len() as u32, *ap)?;
                    i += 1;
                }
            }
            let Some(func) = l.get(i).filter(|n| n.head() == Some("func")) else { return err(*p, "(type) must contain a (func ...) signature") };
            let Node::List(fl, _) = func else { unreachable!() };
            let mut j = 1;
            let (params, _, results) = b.params_results(fl, &mut j)?;
            if j != fl.len() {
                return err(fl[j].pos(), "unexpected item in function type");
            }
            b.m.types.push(FuncType { params, results });
        }
    }
    // classify fields
    struct Slot {
        kind: FieldKind,
        imported: bool,
    }
    let mut slots: Vec<Option<Slot>> = vec![];
    let mut counts = [0u32; 4]; // imported: func, table, mem, global
    for f in &fields {
        let Node::List(l, _) = f else { unreachable!() };
        let kind = match f.head() {
            Some("func") => Some(FieldKind::Func),
            Some("table") => Some(FieldKind::Table),
            Some("memory") => Some(FieldKind::Mem),
            Some("global") => Some(FieldKind::Global),
            _ => None,
        };
        let mut imported_kind: Option<FieldKind> = None;
        if f.head() == Some("import") {
            if let Some(Node::List(desc, _)) = l.get(3) {
                imported_kind = match desc.first().and_then(|n| n.atom()) {
                    Some("func") => Some(FieldKind::Func),
                    Some("table") => Some(FieldKind::Table),
                    Some("memory") => Some(FieldKind::Mem),
                    Some("global") => Some(FieldKind::Global),
                    _ => None,
                };
            }
        }
        let slot = if let Some(k) = imported_kind {
            Some(Slot { kind: k, imported: true })
        } else if let Some(k) = kind {
            let mut i = 1;
            if matches!(l.get(i), Some(Node::Atom(a, _)) if a.starts_with('$')) {
                i += 1;
            }
            let (_, imp) = inline_ie(l, &mut i)?;
            Some(Slot { kind: k, imported: imp.is_some() })
        } else {
            None
        };
        if let Some(s) = &slot {
            if s.imported {
                let ix = match s.kind {
                    FieldKind::Func => 0,
                    FieldKind::Table => 1,
                    FieldKind::Mem => 2,
                    FieldKind::Global => 3,
                };
                counts[ix] += 1;
            }
        }
        slots.push(slot);
    }
    let mut next_imp = [0u32; 4];
    let mut next_def = counts;
    for (f, slot) in fields.iter().zip(&slots) {
        let Some(slot) = slot else { continue };
        let Node::List(l, _) = f else { unreachable!() };
        let (ix, map) = match slot.kind {
            FieldKind::Func => (0, &mut b.names.funcs),
            FieldKind::Table => (1, &mut b.names.tables),
            FieldKind::Mem => (2, &mut b.names.mems),
            FieldKind::Global => (3, &mut b.names.globals),
        };
        let idx = if slot.imported {
            next_imp[ix] += 1;
            next_imp[ix] - 1
        } else {
            next_def[ix] += 1;
            next_def[ix] - 1
        };
        // identifier position: `(func $id` or `(import "m" "n" (func $id`
        let id = if f.head() == Some("import") {
            match l.get(3) {
                Some(Node::List(d, _)) => d.get(1).and_then(|n| n.atom()).filter(|a| a.starts_with('$')).map(|s| (s.to_string(), d[1].pos())),
                _ => None,
            }
        } else {
            l.get(1).and_then(|n| n.atom()).filter(|a| a.starts_with('$')).map(|s| (s.to_string(), l[1].pos()))
        };
        if let Some((id, ip)) = id {
            if ix == 0 {
                b.m.func_names.insert(idx, id[1..].to_string());
            }
            declare(map, &id, idx, ip)?;
        }
    }

    // ---- pass 2: build
    let mut pending_funcs: Vec<(u32, TypeUse, Vec<ValType>, Vec<(String, u32)>, &[Node], Pos)> = vec![];
    let mut exports_inline: Vec<Export> = vec![];
    let mut defined_func_ord = 0u32;
    let n_imp_funcs = counts[0];
    let mut table_elem_abbrevs: Vec<Elem> = vec![];
    let mut mem_data_abbrevs: Vec<Data> = vec![];

    for (f, slot) in fields.iter().zip(&slots) {
        let Node::List(l, fp) = f else { unreachable!() };
        match f.head().unwrap_or("") {
            "type" => {}
            "import" => {
                if l.len() != 4 {
                    return err(*fp, "(import \"module\" \"name\" (kind ...)) expected");
                }
                let module = expect_str(&l[1], "import module")?;
                let name = expect_str(&l[2], "import name")?;
                let Node::List(d, dp) = &l[3] else { return err(l[3].pos(), "expected import descriptor like (func ...)") };
                let mut i = 1;
                if matches!(d.get(i), Some(Node::Atom(a, _)) if a.starts_with('$')) {
                    i += 1;
                }
                let desc = match d.first().and_then(|n| n.atom()) {
                    Some("func") => {
                        let tu = b.typeuse(d, &mut i)?;
                        ImportDesc::Func(tu.idx)
                    }
                    Some("table") => {
                        let (lim, used) = limits(&d[i..], *dp)?;
                        i += used;
                        ImportDesc::Table(lim)
                    }
                    Some("memory") => {
                        let (lim, used) = limits(&d[i..], *dp)?;
                        i += used;
                        ImportDesc::Mem(lim)
                    }
                    Some("global") => {
                        let g = global_type(d.get(i), *dp)?;
                        i += 1;
                        ImportDesc::Global(g)
                    }
                    _ => return err(*dp, "unknown import kind"),
                };
                if matches!(desc, ImportDesc::Table(_)) {
                    if d.get(i).and_then(|n| n.atom()) != Some("funcref") {
                        return err(*dp, "table import must end with `funcref`");
                    }
                    i += 1;
                }
                if i != d.len() {
                    return err(d[i].pos(), "unexpected item in import descriptor");
                }
                b.m.imports.push(Import { module, name, desc });
            }
            "func" => {
                let slot = slot.as_ref().unwrap();
                let mut i = 1;
                if matches!(l.get(i), Some(Node::Atom(a, _)) if a.starts_with('$')) {
                    i += 1;
                }
                let (exports, imp) = inline_ie(l, &mut i)?;
                let tu = b.typeuse(l, &mut i)?;
                let findex = if slot.imported { b.m.imports.iter().filter(|x| matches!(x.desc, ImportDesc::Func(_))).count() as u32 } else { n_imp_funcs + defined_func_ord };
                for e in exports {
                    exports_inline.push(Export { name: e, kind: ExportKind::Func, index: findex });
                }
                if let Some((module, name)) = imp {
                    if i != l.len() {
                        return err(l[i].pos(), "an imported function cannot have a body or locals");
                    }
                    // keep import ordering stable: imports vector is in field order
                    b.m.imports.push(Import { module, name, desc: ImportDesc::Func(tu.idx) });
                } else {
                    // locals
                    let mut locals: Vec<ValType> = vec![];
                    let mut local_names: Vec<(String, u32)> = vec![];
                    let nparams = tu.param_names.len() as u32;
                    for (pi, pn) in tu.param_names.iter().enumerate() {
                        if let Some(n) = pn {
                            local_names.push((n.clone(), pi as u32));
                        }
                    }
                    while let Some(n) = l.get(i) {
                        if n.head() != Some("local") {
                            break;
                        }
                        let Node::List(ll, lp) = n else { unreachable!() };
                        if let Some(Node::Atom(a, ap)) = ll.get(1) {
                            if a.starts_with('$') {
                                if ll.len() != 3 {
                                    return err(*lp, "a named local declares exactly one type");
                                }
                                local_names.push((a.clone(), nparams + locals.len() as u32));
                                locals.push(valtype(&ll[2])?);
                                let _ = ap;
                                i += 1;
                                continue;
                            }
                        }
                        for t in &ll[1..] {
                            locals.push(valtype(t)?);
                        }
                        i += 1;
                    }
                    b.m.funcs.push(tu.idx);
                    pending_funcs.push((findex, tu, locals, local_names, &l[i..], *fp));
                    defined_func_ord += 1;
                }
            }
            "table" => {
                let mut i = 1;
                if matches!(l.get(i), Some(Node::Atom(a, _)) if a.starts_with('$')) {
                    i += 1;
                }
                let (exports, imp) = inline_ie(l, &mut i)?;
                let tindex = if slot.as_ref().unwrap().imported { b.m.imports.iter().filter(|x| matches!(x.desc, ImportDesc::Table(_))).count() as u32 } else { counts[1] + b.m.tables.len() as u32 };
                for e in exports {
                    exports_inline.push(Export { name: e, kind: ExportKind::Table, index: tindex });
                }
                if let Some(a) = l.get(i).and_then(|n| n.atom()).filter(|a| *a == "funcref") {
                    // (table funcref (elem $f $g ...))
                    let _ = a;
                    i += 1;
                    let Some(Node::List(el, _)) = l.get(i).filter(|n| n.head() == Some("elem")) else { return err(*fp, "expected (elem ...) after funcref") };
                    let mut funcs = vec![];
                    for n in &el[1..] {
                        let a = expect_atom(n, "function reference")?;
                        funcs.push(lookup(&b.names.funcs, &a, "function", n.pos())?);
                    }
                    let n = funcs.len() as u32;
                    b.m.tables.push(Limits { min: n, max: Some(n) });
                    table_elem_abbrevs.push(Elem { table: tindex, offset: vec![Instr::I32Const(0), Instr::End], funcs });
                } else {
                    let (lim, used) = limits(&l[i..], *fp)?;
                    i += used;
                    if l.get(i).and_then(|n| n.atom()) != Some("funcref") {
                        return err(*fp, "table element type must be `funcref`");
                    }
                    if imp.is_some() {
                        b.m.imports.push(Import { module: imp.clone().unwrap().0, name: imp.unwrap().1, desc: ImportDesc::Table(lim) });
                    } else {
                        b.m.tables.push(lim);
                    }
                }
            }
            "memory" => {
                let mut i = 1;
                if matches!(l.get(i), Some(Node::Atom(a, _)) if a.starts_with('$')) {
                    i += 1;
                }
                let (exports, imp) = inline_ie(l, &mut i)?;
                let mindex = if slot.as_ref().unwrap().imported { b.m.imports.iter().filter(|x| matches!(x.desc, ImportDesc::Mem(_))).count() as u32 } else { counts[2] + b.m.mems.len() as u32 };
                for e in exports {
                    exports_inline.push(Export { name: e, kind: ExportKind::Mem, index: mindex });
                }
                if let Some(Node::List(dl, _)) = l.get(i).filter(|n| n.head() == Some("data")) {
                    let mut bytes = vec![];
                    for n in &dl[1..] {
                        match n {
                            Node::Str(s, _) => bytes.extend_from_slice(s),
                            other => return err(other.pos(), "expected string in (data ...)"),
                        }
                    }
                    let pages = ((bytes.len() + 65535) / 65536) as u32;
                    b.m.mems.push(Limits { min: pages, max: Some(pages) });
                    mem_data_abbrevs.push(Data { mem: mindex, offset: vec![Instr::I32Const(0), Instr::End], bytes });
                } else {
                    let (lim, used) = limits(&l[i..], *fp)?;
                    i += used;
                    if i != l.len() {
                        return err(l[i].pos(), "unexpected item in memory definition");
                    }
                    if let Some((module, name)) = imp {
                        b.m.imports.push(Import { module, name, desc: ImportDesc::Mem(lim) });
                    } else {
                        b.m.mems.push(lim);
                    }
                }
            }
            "global" => {
                let mut i = 1;
                if matches!(l.get(i), Some(Node::Atom(a, _)) if a.starts_with('$')) {
                    i += 1;
                }
                let (exports, imp) = inline_ie(l, &mut i)?;
                let gindex = if slot.as_ref().unwrap().imported { b.m.imports.iter().filter(|x| matches!(x.desc, ImportDesc::Global(_))).count() as u32 } else { counts[3] + b.m.globals.len() as u32 };
                for e in exports {
                    exports_inline.push(Export { name: e, kind: ExportKind::Global, index: gindex });
                }
                let gt = global_type(l.get(i), *fp)?;
                i += 1;
                if let Some((module, name)) = imp {
                    if i != l.len() {
                        return err(l[i].pos(), "an imported global has no initializer");
                    }
                    b.m.imports.push(Import { module, name, desc: ImportDesc::Global(gt) });
                } else {
                    let init = b.const_expr(&l[i..], *fp)?;
                    b.m.globals.push(Global { ty: gt, init });
                }
            }
            "export" => {
                if l.len() != 3 {
                    return err(*fp, "(export \"name\" (kind index)) expected");
                }
                let name = expect_str(&l[1], "export name")?;
                let Node::List(d, dp) = &l[2] else { return err(l[2].pos(), "expected export descriptor") };
                if d.len() != 2 {
                    return err(*dp, "export descriptor needs exactly one index");
                }
                let a = expect_atom(&d[1], "index")?;
                let (kind, idx) = match d[0].atom() {
                    Some("func") => (ExportKind::Func, lookup(&b.names.funcs, &a, "function", d[1].pos())?),
                    Some("table") => (ExportKind::Table, lookup(&b.names.tables, &a, "table", d[1].pos())?),
                    Some("memory") => (ExportKind::Mem, lookup(&b.names.mems, &a, "memory", d[1].pos())?),
                    Some("global") => (ExportKind::Global, lookup(&b.names.globals, &a, "global", d[1].pos())?),
                    _ => return err(*dp, "unknown export kind"),
                };
                b.m.exports.push(Export { name, kind, index: idx });
            }
            "start" => {
                if l.len() != 2 {
                    return err(*fp, "(start $func) expected");
                }
                let a = expect_atom(&l[1], "function index")?;
                b.m.start = Some(lookup(&b.names.funcs, &a, "function", l[1].pos())?);
            }
            "elem" => {
                let mut i = 1;
                if matches!(l.get(i), Some(Node::Atom(a, _)) if a.starts_with('$')) {
                    i += 1;
                }
                let mut table = 0;
                if let Some(Node::List(tl, _)) = l.get(i).filter(|n| n.head() == Some("table")) {
                    let a = expect_atom(tl.get(1).ok_or(()).or_else(|_| err(*fp, "(table) needs an index"))?, "table index")?;
                    table = lookup(&b.names.tables, &a, "table", tl[1].pos())?;
                    i += 1;
                }
                let Some(off) = l.get(i) else { return err(*fp, "element segment needs an offset") };
                let Node::List(..) = off else { return err(off.pos(), "element offset must be a parenthesised constant expression") };
                let offset = b.const_expr(std::slice::from_ref(off), *fp)?;
                i += 1;
                if l.get(i).and_then(|n| n.atom()) == Some("func") {
                    i += 1;
                }
                let mut funcs = vec![];
                for n in &l[i..] {
                    let a = expect_atom(n, "function reference")?;
                    funcs.push(lookup(&b.names.funcs, &a, "function", n.pos())?);
                }
                b.m.elems.push(Elem { table, offset, funcs });
            }
            "data" => {
                let mut i = 1;
                if matches!(l.get(i), Some(Node::Atom(a, _)) if a.starts_with('$')) {
                    i += 1;
                }
                let mut mem = 0;
                if let Some(Node::List(ml, _)) = l.get(i).filter(|n| n.head() == Some("memory")) {
                    let a = expect_atom(ml.get(1).ok_or(()).or_else(|_| err(*fp, "(memory) needs an index"))?, "memory index")?;
                    mem = lookup(&b.names.mems, &a, "memory", ml[1].pos())?;
                    i += 1;
                }
                let Some(off) = l.get(i) else { return err(*fp, "data segment needs an offset") };
                let Node::List(..) = off else { return err(off.pos(), "data offset must be a parenthesised constant expression") };
                let offset = b.const_expr(std::slice::from_ref(off), *fp)?;
                i += 1;
                let mut bytes = vec![];
                for n in &l[i..] {
                    match n {
                        Node::Str(s, _) => bytes.extend_from_slice(s),
                        other => return err(other.pos(), "expected string literal in data segment"),
                    }
                }
                b.m.datas.push(Data { mem, offset, bytes });
            }
            other => return err(*fp, format!("unknown module field `{other}`")),
        }
    }
    let _ = mpos;
    b.m.elems.extend(table_elem_abbrevs);
    b.m.datas.extend(mem_data_abbrevs);

    // function bodies (all names known now)
    for (_findex, tu, locals, local_names, body, _fp) in pending_funcs {
        let mut fc = FnCtx { locals: HashMap::new(), labels: vec![] };
        for (n, i) in local_names {
            if fc.locals.insert(n.clone(), i).is_some() {
                return err(_fp, format!("duplicate local name {n}"));
            }
        }
        let _ = tu;
        let mut out = vec![];
        b.instrs(body, &mut fc, &mut out)?;
        if !fc.labels.is_empty() {
            return err(_fp, "unclosed block: missing `end`");
        }
        out.push(Instr::End);
        b.m.codes.push(Code { locals, body: out });
    }
    b.m.exports.extend(exports_inline);
    Ok(b.m)
}

fn global_type(n: Option<&Node>, p: Pos) -> R<GlobalType> {
    match n {
        Some(Node::Atom(..)) => Ok(GlobalType { ty: valtype(n.unwrap())?, mutable: false }),
        Some(Node::List(l, lp)) if n.unwrap().head() == Some("mut") => {
            if l.len() != 2 {
                return err(*lp, "(mut <type>) expected");
            }
            Ok(GlobalType { ty: valtype(&l[1])?, mutable: true })
        }
        Some(other) => err(other.pos(), "expected global type"),
        None => err(p, "global is missing its type"),
    }
}
