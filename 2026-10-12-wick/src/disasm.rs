//! Module -> WAT text. Output re-assembles to an identical module (round-trip tested).
use crate::ast::*;
use crate::num;
use std::collections::{HashMap, HashSet};
use std::fmt::Write;

/// Static mnemonic of an instruction (used by the disassembler and the profiler).
pub fn mnemonic(i: &Instr) -> &'static str {
    match i {
        Instr::Unreachable => "unreachable",
        Instr::Nop => "nop",
        Instr::Block(_) => "block",
        Instr::Loop(_) => "loop",
        Instr::If(_) => "if",
        Instr::Else => "else",
        Instr::End => "end",
        Instr::Br(_) => "br",
        Instr::BrIf(_) => "br_if",
        Instr::BrTable(..) => "br_table",
        Instr::Return => "return",
        Instr::Call(_) => "call",
        Instr::CallIndirect(..) => "call_indirect",
        Instr::Drop => "drop",
        Instr::Select | Instr::SelectT(_) => "select",
        Instr::LocalGet(_) => "local.get",
        Instr::LocalSet(_) => "local.set",
        Instr::LocalTee(_) => "local.tee",
        Instr::GlobalGet(_) => "global.get",
        Instr::GlobalSet(_) => "global.set",
        Instr::Mem { op, .. } => num::mem_op(*op).map(|m| m.1).unwrap_or("?mem"),
        Instr::MemorySize => "memory.size",
        Instr::MemoryGrow => "memory.grow",
        Instr::MemoryCopy => "memory.copy",
        Instr::MemoryFill => "memory.fill",
        Instr::I32Const(_) => "i32.const",
        Instr::I64Const(_) => "i64.const",
        Instr::F32Const(_) => "f32.const",
        Instr::F64Const(_) => "f64.const",
        Instr::Num(c) => num::by_code(*c).map(|o| o.name).unwrap_or("?num"),
    }
}

fn f32_text(b: u32) -> String {
    let f = f32::from_bits(b);
    if f.is_nan() {
        let payload = b & 0x7f_ffff;
        return format!("{}nan:0x{:x}", if b >> 31 == 1 { "-" } else { "" }, payload);
    }
    if f.is_infinite() {
        return if f > 0.0 { "inf".into() } else { "-inf".into() };
    }
    format!("{f:?}")
}
fn f64_text(b: u64) -> String {
    let f = f64::from_bits(b);
    if f.is_nan() {
        let payload = b & 0xf_ffff_ffff_ffff;
        return format!("{}nan:0x{:x}", if b >> 63 == 1 { "-" } else { "" }, payload);
    }
    if f.is_infinite() {
        return if f > 0.0 { "inf".into() } else { "-inf".into() };
    }
    format!("{f:?}")
}

fn bt_text(bt: &BlockType) -> String {
    match bt {
        BlockType::Empty => String::new(),
        BlockType::Val(v) => format!(" (result {})", v.name()),
        BlockType::Type(i) => format!(" (type {i})"),
    }
}

/// Text of one instruction with its immediates (no indentation).
pub fn instr_text(i: &Instr, label: &dyn Fn(u32) -> String) -> String {
    let m = mnemonic(i);
    match i {
        Instr::Block(bt) | Instr::Loop(bt) | Instr::If(bt) => format!("{m}{}", bt_text(bt)),
        Instr::Br(l) | Instr::BrIf(l) => format!("{m} {l}"),
        Instr::BrTable(ls, d) => {
            let mut s = m.to_string();
            for l in ls {
                write!(s, " {l}").unwrap();
            }
            write!(s, " {d}").unwrap();
            s
        }
        Instr::Call(f) => format!("{m} {}", label(*f)),
        Instr::CallIndirect(t, tab) => {
            if *tab == 0 {
                format!("{m} (type {t})")
            } else {
                format!("{m} {tab} (type {t})")
            }
        }
        Instr::SelectT(t) => format!("select (result {})", t.name()),
        Instr::LocalGet(x) | Instr::LocalSet(x) | Instr::LocalTee(x) | Instr::GlobalGet(x) | Instr::GlobalSet(x) => format!("{m} {x}"),
        Instr::Mem { op, align, offset } => {
            let mut s = m.to_string();
            if *offset != 0 {
                write!(s, " offset={offset}").unwrap();
            }
            let natural = num::mem_op(*op).map(|m| m.3.trailing_zeros()).unwrap_or(0);
            if *align != natural {
                write!(s, " align={}", 1u64 << (*align).min(40)).unwrap();
            }
            s
        }
        Instr::I32Const(v) => format!("{m} {v}"),
        Instr::I64Const(v) => format!("{m} {v}"),
        Instr::F32Const(b) => format!("{m} {}", f32_text(*b)),
        Instr::F64Const(b) => format!("{m} {}", f64_text(*b)),
        _ => m.to_string(),
    }
}

fn escape(bytes: &[u8]) -> String {
    let mut s = String::from("\"");
    for &b in bytes {
        match b {
            b'"' => s.push_str("\\\""),
            b'\\' => s.push_str("\\\\"),
            0x20..=0x7e => s.push(b as char),
            _ => write!(s, "\\{b:02x}").unwrap(),
        }
    }
    s.push('"');
    s
}

fn sanitize(n: &str) -> String {
    n.chars().map(|c| if c.is_ascii_alphanumeric() || "!#$%&'*+-./:<=>?@\\^_`|~".contains(c) { c } else { '_' }).collect()
}

fn limits_text(l: &Limits) -> String {
    match l.max {
        Some(m) => format!("{} {}", l.min, m),
        None => format!("{}", l.min),
    }
}

pub fn disassemble(m: &Module) -> String {
    // unique, valid function labels
    let total_funcs = m.all_func_types().len() as u32;
    let mut used: HashSet<String> = HashSet::new();
    let mut labels: HashMap<u32, String> = HashMap::new();
    for i in 0..total_funcs {
        if let Some(n) = m.func_names.get(&i) {
            let s = sanitize(n);
            if !s.is_empty() && used.insert(s.clone()) {
                labels.insert(i, format!("${s}"));
                continue;
            }
        }
    }
    for i in 0..total_funcs {
        labels.entry(i).or_insert_with(|| {
            let mut s = format!("f{i}");
            while !used.insert(s.clone()) {
                s.push('_');
            }
            format!("${s}")
        });
    }
    let label = |i: u32| labels.get(&i).cloned().unwrap_or_else(|| i.to_string());

    let mut o = String::from("(module\n");
    for (i, t) in m.types.iter().enumerate() {
        let _ = i;
        o.push_str("  (type (func");
        if !t.params.is_empty() {
            o.push_str(" (param");
            for p in &t.params {
                write!(o, " {}", p.name()).unwrap();
            }
            o.push(')');
        }
        if !t.results.is_empty() {
            o.push_str(" (result");
            for r in &t.results {
                write!(o, " {}", r.name()).unwrap();
            }
            o.push(')');
        }
        o.push_str("))\n");
    }
    let (mut nf, mut nt, mut nm, mut ng) = (0u32, 0u32, 0u32, 0u32);
    for imp in &m.imports {
        write!(o, "  (import {} {} ", escape(imp.module.as_bytes()), escape(imp.name.as_bytes())).unwrap();
        match &imp.desc {
            ImportDesc::Func(t) => {
                write!(o, "(func {} (type {t}))", label(nf)).unwrap();
                nf += 1;
            }
            ImportDesc::Table(l) => {
                write!(o, "(table {} funcref)", limits_text(l)).unwrap();
                nt += 1;
            }
            ImportDesc::Mem(l) => {
                write!(o, "(memory {})", limits_text(l)).unwrap();
                nm += 1;
            }
            ImportDesc::Global(g) => {
                if g.mutable {
                    write!(o, "(global (mut {}))", g.ty.name()).unwrap();
                } else {
                    write!(o, "(global {})", g.ty.name()).unwrap();
                }
                ng += 1;
            }
        }
        o.push_str(")\n");
    }
    let _ = (nt, nm, ng);
    for t in &m.tables {
        writeln!(o, "  (table {} funcref)", limits_text(t)).unwrap();
    }
    for t in &m.mems {
        writeln!(o, "  (memory {})", limits_text(t)).unwrap();
    }
    let noop = |_: u32| String::new();
    let _ = noop;
    for g in &m.globals {
        let ty = if g.ty.mutable { format!("(mut {})", g.ty.ty.name()) } else { g.ty.ty.name().to_string() };
        let init: Vec<String> = g.init.iter().filter(|i| **i != Instr::End).map(|i| instr_text(i, &label)).collect();
        writeln!(o, "  (global {ty} ({}))", init.join(" ")).unwrap();
    }
    let n_imp = m.num_imported_funcs() as u32;
    for (i, (tidx, code)) in m.funcs.iter().zip(&m.codes).enumerate() {
        let fi = n_imp + i as u32;
        write!(o, "  (func {} (type {tidx})", label(fi)).unwrap();
        if !code.locals.is_empty() {
            o.push_str(" (local");
            for l in &code.locals {
                write!(o, " {}", l.name()).unwrap();
            }
            o.push(')');
        }
        o.push('\n');
        let mut depth = 1usize;
        // the final End closes the function itself, which the `(func` paren handles
        let body = &code.body;
        for (k, ins) in body.iter().enumerate() {
            if k + 1 == body.len() && *ins == Instr::End {
                break;
            }
            if matches!(ins, Instr::End | Instr::Else) {
                depth = depth.saturating_sub(1).max(1);
            }
            writeln!(o, "{}{}", "  ".repeat(depth + 1), instr_text(ins, &label)).unwrap();
            if matches!(ins, Instr::Block(_) | Instr::Loop(_) | Instr::If(_) | Instr::Else) {
                depth += 1;
            }
        }
        o.push_str("  )\n");
    }
    for e in &m.exports {
        let (k, idx) = match e.kind {
            ExportKind::Func => ("func", label(e.index)),
            ExportKind::Table => ("table", e.index.to_string()),
            ExportKind::Mem => ("memory", e.index.to_string()),
            ExportKind::Global => ("global", e.index.to_string()),
        };
        writeln!(o, "  (export {} ({k} {idx}))", escape(e.name.as_bytes())).unwrap();
    }
    if let Some(s) = m.start {
        writeln!(o, "  (start {})", label(s)).unwrap();
    }
    for e in &m.elems {
        let off: Vec<String> = e.offset.iter().filter(|i| **i != Instr::End).map(|i| instr_text(i, &label)).collect();
        let fs: Vec<String> = e.funcs.iter().map(|f| label(*f)).collect();
        if e.table == 0 {
            writeln!(o, "  (elem ({}) func {})", off.join(" "), fs.join(" ")).unwrap();
        } else {
            writeln!(o, "  (elem (table {}) ({}) func {})", e.table, off.join(" "), fs.join(" ")).unwrap();
        }
    }
    for d in &m.datas {
        let off: Vec<String> = d.offset.iter().filter(|i| **i != Instr::End).map(|i| instr_text(i, &label)).collect();
        if d.mem == 0 {
            writeln!(o, "  (data ({}) {})", off.join(" "), escape(&d.bytes)).unwrap();
        } else {
            writeln!(o, "  (data (memory {}) ({}) {})", d.mem, off.join(" "), escape(&d.bytes)).unwrap();
        }
    }
    o.push_str(")\n");
    o
}
