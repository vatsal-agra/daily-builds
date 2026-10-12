//! Module -> .wasm binary.
use crate::ast::*;
use crate::leb::{write_s, write_u};

fn name(out: &mut Vec<u8>, s: &str) {
    write_u(out, s.len() as u64);
    out.extend_from_slice(s.as_bytes());
}

fn limits(out: &mut Vec<u8>, l: &Limits) {
    match l.max {
        None => {
            out.push(0);
            write_u(out, l.min as u64);
        }
        Some(m) => {
            out.push(1);
            write_u(out, l.min as u64);
            write_u(out, m as u64);
        }
    }
}

fn block_type(out: &mut Vec<u8>, bt: &BlockType) {
    match bt {
        BlockType::Empty => out.push(0x40),
        BlockType::Val(v) => out.push(v.byte()),
        BlockType::Type(i) => write_s(out, *i as i64),
    }
}

pub fn instr(out: &mut Vec<u8>, i: &Instr) {
    match i {
        Instr::Unreachable => out.push(0x00),
        Instr::Nop => out.push(0x01),
        Instr::Block(bt) => {
            out.push(0x02);
            block_type(out, bt)
        }
        Instr::Loop(bt) => {
            out.push(0x03);
            block_type(out, bt)
        }
        Instr::If(bt) => {
            out.push(0x04);
            block_type(out, bt)
        }
        Instr::Else => out.push(0x05),
        Instr::End => out.push(0x0B),
        Instr::Br(l) => {
            out.push(0x0C);
            write_u(out, *l as u64)
        }
        Instr::BrIf(l) => {
            out.push(0x0D);
            write_u(out, *l as u64)
        }
        Instr::BrTable(ls, d) => {
            out.push(0x0E);
            write_u(out, ls.len() as u64);
            for l in ls {
                write_u(out, *l as u64);
            }
            write_u(out, *d as u64);
        }
        Instr::Return => out.push(0x0F),
        Instr::Call(f) => {
            out.push(0x10);
            write_u(out, *f as u64)
        }
        Instr::CallIndirect(t, tab) => {
            out.push(0x11);
            write_u(out, *t as u64);
            write_u(out, *tab as u64);
        }
        Instr::Drop => out.push(0x1A),
        Instr::Select => out.push(0x1B),
        Instr::SelectT(t) => {
            out.push(0x1C);
            write_u(out, 1);
            out.push(t.byte());
        }
        Instr::LocalGet(x) => {
            out.push(0x20);
            write_u(out, *x as u64)
        }
        Instr::LocalSet(x) => {
            out.push(0x21);
            write_u(out, *x as u64)
        }
        Instr::LocalTee(x) => {
            out.push(0x22);
            write_u(out, *x as u64)
        }
        Instr::GlobalGet(x) => {
            out.push(0x23);
            write_u(out, *x as u64)
        }
        Instr::GlobalSet(x) => {
            out.push(0x24);
            write_u(out, *x as u64)
        }
        Instr::Mem { op, align, offset } => {
            out.push(*op);
            write_u(out, *align as u64);
            write_u(out, *offset as u64);
        }
        Instr::MemorySize => out.extend_from_slice(&[0x3F, 0x00]),
        Instr::MemoryGrow => out.extend_from_slice(&[0x40, 0x00]),
        Instr::MemoryCopy => out.extend_from_slice(&[0xFC, 10, 0x00, 0x00]),
        Instr::MemoryFill => out.extend_from_slice(&[0xFC, 11, 0x00]),
        Instr::I32Const(v) => {
            out.push(0x41);
            write_s(out, *v as i64)
        }
        Instr::I64Const(v) => {
            out.push(0x42);
            write_s(out, *v)
        }
        Instr::F32Const(b) => {
            out.push(0x43);
            out.extend_from_slice(&b.to_le_bytes())
        }
        Instr::F64Const(b) => {
            out.push(0x44);
            out.extend_from_slice(&b.to_le_bytes())
        }
        Instr::Num(c) => {
            if *c >= 0xFC00 {
                out.push(0xFC);
                write_u(out, (*c & 0xFF) as u64);
            } else {
                out.push(*c as u8)
            }
        }
    }
}

fn expr(out: &mut Vec<u8>, e: &[Instr]) {
    for i in e {
        instr(out, i);
    }
}

fn section(out: &mut Vec<u8>, id: u8, body: Vec<u8>) {
    out.push(id);
    write_u(out, body.len() as u64);
    out.extend(body);
}

pub fn encode(m: &Module) -> Vec<u8> {
    let mut out = b"\0asm\x01\x00\x00\x00".to_vec();

    if !m.types.is_empty() {
        let mut b = vec![];
        write_u(&mut b, m.types.len() as u64);
        for t in &m.types {
            b.push(0x60);
            write_u(&mut b, t.params.len() as u64);
            for p in &t.params {
                b.push(p.byte());
            }
            write_u(&mut b, t.results.len() as u64);
            for r in &t.results {
                b.push(r.byte());
            }
        }
        section(&mut out, 1, b);
    }
    if !m.imports.is_empty() {
        let mut b = vec![];
        write_u(&mut b, m.imports.len() as u64);
        for i in &m.imports {
            name(&mut b, &i.module);
            name(&mut b, &i.name);
            match &i.desc {
                ImportDesc::Func(t) => {
                    b.push(0);
                    write_u(&mut b, *t as u64)
                }
                ImportDesc::Table(l) => {
                    b.push(1);
                    b.push(0x70);
                    limits(&mut b, l)
                }
                ImportDesc::Mem(l) => {
                    b.push(2);
                    limits(&mut b, l)
                }
                ImportDesc::Global(g) => {
                    b.push(3);
                    b.push(g.ty.byte());
                    b.push(g.mutable as u8)
                }
            }
        }
        section(&mut out, 2, b);
    }
    if !m.funcs.is_empty() {
        let mut b = vec![];
        write_u(&mut b, m.funcs.len() as u64);
        for f in &m.funcs {
            write_u(&mut b, *f as u64);
        }
        section(&mut out, 3, b);
    }
    if !m.tables.is_empty() {
        let mut b = vec![];
        write_u(&mut b, m.tables.len() as u64);
        for t in &m.tables {
            b.push(0x70);
            limits(&mut b, t);
        }
        section(&mut out, 4, b);
    }
    if !m.mems.is_empty() {
        let mut b = vec![];
        write_u(&mut b, m.mems.len() as u64);
        for l in &m.mems {
            limits(&mut b, l);
        }
        section(&mut out, 5, b);
    }
    if !m.globals.is_empty() {
        let mut b = vec![];
        write_u(&mut b, m.globals.len() as u64);
        for g in &m.globals {
            b.push(g.ty.ty.byte());
            b.push(g.ty.mutable as u8);
            expr(&mut b, &g.init);
        }
        section(&mut out, 6, b);
    }
    if !m.exports.is_empty() {
        let mut b = vec![];
        write_u(&mut b, m.exports.len() as u64);
        for e in &m.exports {
            name(&mut b, &e.name);
            b.push(match e.kind {
                ExportKind::Func => 0,
                ExportKind::Table => 1,
                ExportKind::Mem => 2,
                ExportKind::Global => 3,
            });
            write_u(&mut b, e.index as u64);
        }
        section(&mut out, 7, b);
    }
    if let Some(s) = m.start {
        let mut b = vec![];
        write_u(&mut b, s as u64);
        section(&mut out, 8, b);
    }
    if !m.elems.is_empty() {
        let mut b = vec![];
        write_u(&mut b, m.elems.len() as u64);
        for e in &m.elems {
            if e.table == 0 {
                write_u(&mut b, 0);
            } else {
                write_u(&mut b, 2);
                write_u(&mut b, e.table as u64);
            }
            expr(&mut b, &e.offset);
            if e.table != 0 {
                b.push(0x00); // elemkind funcref
            }
            write_u(&mut b, e.funcs.len() as u64);
            for f in &e.funcs {
                write_u(&mut b, *f as u64);
            }
        }
        section(&mut out, 9, b);
    }
    if !m.codes.is_empty() {
        let mut b = vec![];
        write_u(&mut b, m.codes.len() as u64);
        for c in &m.codes {
            let mut body = vec![];
            // run-length encode locals
            let mut runs: Vec<(u32, ValType)> = vec![];
            for l in &c.locals {
                match runs.last_mut() {
                    Some((n, t)) if t == l => *n += 1,
                    _ => runs.push((1, *l)),
                }
            }
            write_u(&mut body, runs.len() as u64);
            for (n, t) in runs {
                write_u(&mut body, n as u64);
                body.push(t.byte());
            }
            expr(&mut body, &c.body);
            write_u(&mut b, body.len() as u64);
            b.extend(body);
        }
        section(&mut out, 10, b);
    }
    if !m.datas.is_empty() {
        let mut b = vec![];
        write_u(&mut b, m.datas.len() as u64);
        for d in &m.datas {
            if d.mem == 0 {
                write_u(&mut b, 0);
            } else {
                write_u(&mut b, 2);
                write_u(&mut b, d.mem as u64);
            }
            expr(&mut b, &d.offset);
            write_u(&mut b, d.bytes.len() as u64);
            b.extend_from_slice(&d.bytes);
        }
        section(&mut out, 11, b);
    }
    if !m.func_names.is_empty() {
        let mut names: Vec<(&u32, &String)> = m.func_names.iter().collect();
        names.sort();
        let mut sub = vec![];
        write_u(&mut sub, names.len() as u64);
        for (i, n) in names {
            write_u(&mut sub, *i as u64);
            name(&mut sub, n);
        }
        let mut b = vec![];
        name(&mut b, "name");
        b.push(1);
        write_u(&mut b, sub.len() as u64);
        b.extend(sub);
        section(&mut out, 0, b);
    }
    out
}
