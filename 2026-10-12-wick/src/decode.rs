//! .wasm binary -> Module, with bounds-checked reads and offset-carrying errors.
use crate::ast::*;
use crate::leb;
use crate::num;
use std::collections::HashMap;

#[derive(Debug, Clone, PartialEq)]
pub struct DecodeError {
    pub offset: usize,
    pub msg: String,
}
impl std::fmt::Display for DecodeError {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "decode error at byte {:#x}: {}", self.offset, self.msg)
    }
}
impl std::error::Error for DecodeError {}

type R<T> = Result<T, DecodeError>;

struct Rd<'a> {
    d: &'a [u8],
    pos: usize,
    end: usize,
}

const MAX_LOCALS: u64 = 50_000;

impl<'a> Rd<'a> {
    fn err<T>(&self, msg: impl Into<String>) -> R<T> {
        Err(DecodeError { offset: self.pos, msg: msg.into() })
    }
    fn byte(&mut self) -> R<u8> {
        if self.pos >= self.end {
            return self.err("unexpected end of section or function");
        }
        let b = self.d[self.pos];
        self.pos += 1;
        Ok(b)
    }
    fn bytes(&mut self, n: usize) -> R<&'a [u8]> {
        if n > self.end - self.pos {
            return self.err(format!("unexpected end: need {n} bytes"));
        }
        let s = &self.d[self.pos..self.pos + n];
        self.pos += n;
        Ok(s)
    }
    fn u32(&mut self) -> R<u32> {
        let start = self.pos;
        let sub = &self.d[..self.end];
        leb::read_u(sub, &mut self.pos, 32).map(|v| v as u32).map_err(|m| DecodeError { offset: start, msg: m })
    }
    fn s32(&mut self) -> R<i32> {
        let start = self.pos;
        let sub = &self.d[..self.end];
        leb::read_s(sub, &mut self.pos, 32).map(|v| v as i32).map_err(|m| DecodeError { offset: start, msg: m })
    }
    fn s64(&mut self) -> R<i64> {
        let start = self.pos;
        let sub = &self.d[..self.end];
        leb::read_s(sub, &mut self.pos, 64).map_err(|m| DecodeError { offset: start, msg: m })
    }
    fn s33(&mut self) -> R<i64> {
        let start = self.pos;
        let sub = &self.d[..self.end];
        leb::read_s(sub, &mut self.pos, 33).map_err(|m| DecodeError { offset: start, msg: m })
    }
    fn name(&mut self) -> R<String> {
        let n = self.u32()? as usize;
        let at = self.pos;
        let b = self.bytes(n)?;
        String::from_utf8(b.to_vec()).map_err(|_| DecodeError { offset: at, msg: "malformed UTF-8 name".into() })
    }
    fn valtype(&mut self) -> R<ValType> {
        let at = self.pos;
        let b = self.byte()?;
        ValType::from_byte(b).ok_or(DecodeError { offset: at, msg: format!("invalid value type {b:#x}") })
    }
    fn limits(&mut self) -> R<Limits> {
        let at = self.pos;
        let f = self.byte()?;
        match f {
            0 => Ok(Limits { min: self.u32()?, max: None }),
            1 => {
                let min = self.u32()?;
                Ok(Limits { min, max: Some(self.u32()?) })
            }
            _ => Err(DecodeError { offset: at, msg: format!("invalid limits flag {f:#x}") }),
        }
    }
    fn vec_len(&mut self) -> R<usize> {
        let n = self.u32()? as usize;
        // every element needs at least one byte; reject absurd counts before allocating
        if n > self.end - self.pos {
            return self.err(format!("vector length {n} exceeds remaining section size"));
        }
        Ok(n)
    }
    fn block_type(&mut self) -> R<BlockType> {
        let at = self.pos;
        if self.pos >= self.end {
            return self.err("unexpected end in block type");
        }
        let b = self.d[self.pos];
        if b == 0x40 {
            self.pos += 1;
            return Ok(BlockType::Empty);
        }
        if let Some(v) = ValType::from_byte(b) {
            self.pos += 1;
            return Ok(BlockType::Val(v));
        }
        let v = self.s33()?;
        if v < 0 {
            return Err(DecodeError { offset: at, msg: "invalid block type".into() });
        }
        Ok(BlockType::Type(v as u32))
    }
    fn zero_byte(&mut self, what: &str) -> R<()> {
        let at = self.pos;
        if self.byte()? != 0 {
            return Err(DecodeError { offset: at, msg: format!("{what} must be 0x00") });
        }
        Ok(())
    }

    fn instr(&mut self) -> R<Instr> {
        let at = self.pos;
        let op = self.byte()?;
        Ok(match op {
            0x00 => Instr::Unreachable,
            0x01 => Instr::Nop,
            0x02 => Instr::Block(self.block_type()?),
            0x03 => Instr::Loop(self.block_type()?),
            0x04 => Instr::If(self.block_type()?),
            0x05 => Instr::Else,
            0x0B => Instr::End,
            0x0C => Instr::Br(self.u32()?),
            0x0D => Instr::BrIf(self.u32()?),
            0x0E => {
                let n = self.vec_len()?;
                let mut ls = Vec::with_capacity(n);
                for _ in 0..n {
                    ls.push(self.u32()?);
                }
                Instr::BrTable(ls, self.u32()?)
            }
            0x0F => Instr::Return,
            0x10 => Instr::Call(self.u32()?),
            0x11 => {
                let t = self.u32()?;
                Instr::CallIndirect(t, self.u32()?)
            }
            0x1A => Instr::Drop,
            0x1B => Instr::Select,
            0x1C => {
                let n = self.u32()?;
                if n != 1 {
                    return Err(DecodeError { offset: at, msg: "select must have exactly one result type".into() });
                }
                Instr::SelectT(self.valtype()?)
            }
            0x20 => Instr::LocalGet(self.u32()?),
            0x21 => Instr::LocalSet(self.u32()?),
            0x22 => Instr::LocalTee(self.u32()?),
            0x23 => Instr::GlobalGet(self.u32()?),
            0x24 => Instr::GlobalSet(self.u32()?),
            0x28..=0x3E => {
                let align = self.u32()?;
                let offset = self.u32()?;
                Instr::Mem { op, align, offset }
            }
            0x3F => {
                self.zero_byte("memory index")?;
                Instr::MemorySize
            }
            0x40 => {
                self.zero_byte("memory index")?;
                Instr::MemoryGrow
            }
            0x41 => Instr::I32Const(self.s32()?),
            0x42 => Instr::I64Const(self.s64()?),
            0x43 => {
                let b = self.bytes(4)?;
                Instr::F32Const(u32::from_le_bytes(b.try_into().unwrap()))
            }
            0x44 => {
                let b = self.bytes(8)?;
                Instr::F64Const(u64::from_le_bytes(b.try_into().unwrap()))
            }
            0x45..=0xC4 => {
                debug_assert!(num::by_code(op as u16).is_some());
                Instr::Num(op as u16)
            }
            0xFC => {
                let sub = self.u32()?;
                match sub {
                    0..=7 => Instr::Num(0xFC00 | sub as u16),
                    10 => {
                        self.zero_byte("memory index")?;
                        self.zero_byte("memory index")?;
                        Instr::MemoryCopy
                    }
                    11 => {
                        self.zero_byte("memory index")?;
                        Instr::MemoryFill
                    }
                    _ => return Err(DecodeError { offset: at, msg: format!("unsupported 0xFC sub-opcode {sub}") }),
                }
            }
            _ => return Err(DecodeError { offset: at, msg: format!("unknown opcode {op:#04x}") }),
        })
    }

    /// Constant expression: instructions up to and including the first End.
    fn const_expr(&mut self) -> R<Vec<Instr>> {
        let mut v = vec![];
        loop {
            let i = self.instr()?;
            let end = i == Instr::End;
            v.push(i);
            if end {
                return Ok(v);
            }
            if v.len() > 64 {
                return self.err("constant expression too long");
            }
        }
    }
}

pub fn decode(data: &[u8]) -> Result<Module, DecodeError> {
    if data.len() < 8 || &data[0..4] != b"\0asm" {
        return Err(DecodeError { offset: 0, msg: "bad magic number (not a wasm binary)".into() });
    }
    if data[4..8] != [1, 0, 0, 0] {
        return Err(DecodeError { offset: 4, msg: "unsupported binary version".into() });
    }
    let mut m = Module::default();
    let mut pos = 8usize;
    let mut last_id = 0u8;
    let mut func_decl_count: Option<usize> = None;
    let mut have_code = false;
    while pos < data.len() {
        let mut hdr = Rd { d: data, pos, end: data.len() };
        let id = hdr.byte()?;
        let size = hdr.u32()? as usize;
        let start = hdr.pos;
        if size > data.len() - start {
            return Err(DecodeError { offset: start, msg: format!("section {id} size {size} exceeds module") });
        }
        let end = start + size;
        pos = end;
        let mut r = Rd { d: data, pos: start, end };
        if id != 0 {
            if id > 11 {
                return Err(DecodeError { offset: hdr.pos, msg: format!("unknown section id {id}") });
            }
            if id <= last_id {
                return Err(DecodeError { offset: start, msg: format!("section {id} out of order or duplicated") });
            }
            last_id = id;
        }
        match id {
            0 => {
                let nm = r.name();
                if let Ok(nm) = nm {
                    if nm == "name" {
                        parse_names(&mut r, &mut m.func_names);
                    }
                }
                continue; // custom sections are never checked for exact consumption
            }
            1 => {
                for _ in 0..r.vec_len()? {
                    let at = r.pos;
                    if r.byte()? != 0x60 {
                        return Err(DecodeError { offset: at, msg: "expected func type tag 0x60".into() });
                    }
                    let np = r.vec_len()?;
                    let mut params = vec![];
                    for _ in 0..np {
                        params.push(r.valtype()?);
                    }
                    let nr = r.vec_len()?;
                    let mut results = vec![];
                    for _ in 0..nr {
                        results.push(r.valtype()?);
                    }
                    m.types.push(FuncType { params, results });
                }
            }
            2 => {
                for _ in 0..r.vec_len()? {
                    let module = r.name()?;
                    let name = r.name()?;
                    let at = r.pos;
                    let kind = r.byte()?;
                    let desc = match kind {
                        0 => ImportDesc::Func(r.u32()?),
                        1 => {
                            let at = r.pos;
                            if r.byte()? != 0x70 {
                                return Err(DecodeError { offset: at, msg: "table element type must be funcref".into() });
                            }
                            ImportDesc::Table(r.limits()?)
                        }
                        2 => ImportDesc::Mem(r.limits()?),
                        3 => {
                            let ty = r.valtype()?;
                            let mutable = mut_flag(&mut r)?;
                            ImportDesc::Global(GlobalType { ty, mutable })
                        }
                        _ => return Err(DecodeError { offset: at, msg: format!("invalid import kind {kind}") }),
                    };
                    m.imports.push(Import { module, name, desc });
                }
            }
            3 => {
                let n = r.vec_len()?;
                func_decl_count = Some(n);
                for _ in 0..n {
                    m.funcs.push(r.u32()?);
                }
            }
            4 => {
                for _ in 0..r.vec_len()? {
                    let at = r.pos;
                    if r.byte()? != 0x70 {
                        return Err(DecodeError { offset: at, msg: "table element type must be funcref".into() });
                    }
                    m.tables.push(r.limits()?);
                }
            }
            5 => {
                for _ in 0..r.vec_len()? {
                    m.mems.push(r.limits()?);
                }
            }
            6 => {
                for _ in 0..r.vec_len()? {
                    let ty = r.valtype()?;
                    let mutable = mut_flag(&mut r)?;
                    let init = r.const_expr()?;
                    m.globals.push(Global { ty: GlobalType { ty, mutable }, init });
                }
            }
            7 => {
                for _ in 0..r.vec_len()? {
                    let name = r.name()?;
                    let at = r.pos;
                    let kind = match r.byte()? {
                        0 => ExportKind::Func,
                        1 => ExportKind::Table,
                        2 => ExportKind::Mem,
                        3 => ExportKind::Global,
                        k => return Err(DecodeError { offset: at, msg: format!("invalid export kind {k}") }),
                    };
                    m.exports.push(Export { name, kind, index: r.u32()? });
                }
            }
            8 => m.start = Some(r.u32()?),
            9 => {
                for _ in 0..r.vec_len()? {
                    let at = r.pos;
                    let flag = r.u32()?;
                    let (table, offset) = match flag {
                        0 => (0, r.const_expr()?),
                        2 => {
                            let t = r.u32()?;
                            let o = r.const_expr()?;
                            let k = r.byte()?;
                            if k != 0 {
                                return Err(DecodeError { offset: at, msg: "elemkind must be 0x00 (funcref)".into() });
                            }
                            (t, o)
                        }
                        _ => return Err(DecodeError { offset: at, msg: format!("unsupported element segment flag {flag} (only active funcref segments)") }),
                    };
                    let n = r.vec_len()?;
                    let mut funcs = Vec::with_capacity(n);
                    for _ in 0..n {
                        funcs.push(r.u32()?);
                    }
                    m.elems.push(Elem { table, offset, funcs });
                }
            }
            10 => {
                have_code = true;
                let n = r.vec_len()?;
                for _ in 0..n {
                    let size = r.u32()? as usize;
                    let at = r.pos;
                    if size > r.end - r.pos {
                        return Err(DecodeError { offset: at, msg: "function body size exceeds section".into() });
                    }
                    let mut b = Rd { d: data, pos: at, end: at + size };
                    let nruns = b.vec_len()?;
                    let mut locals = vec![];
                    let mut total: u64 = 0;
                    for _ in 0..nruns {
                        let cnt = b.u32()? as u64;
                        let t = b.valtype()?;
                        total += cnt;
                        if total > MAX_LOCALS {
                            return Err(DecodeError { offset: b.pos, msg: "too many locals".into() });
                        }
                        locals.extend(std::iter::repeat(t).take(cnt as usize));
                    }
                    let mut body = vec![];
                    while b.pos < b.end {
                        body.push(b.instr()?);
                    }
                    r.pos = at + size;
                    m.codes.push(Code { locals, body });
                }
            }
            11 => {
                for _ in 0..r.vec_len()? {
                    let at = r.pos;
                    let flag = r.u32()?;
                    let (mem, offset) = match flag {
                        0 => (0, r.const_expr()?),
                        2 => {
                            let mi = r.u32()?;
                            (mi, r.const_expr()?)
                        }
                        _ => return Err(DecodeError { offset: at, msg: format!("unsupported data segment flag {flag} (only active segments)") }),
                    };
                    let n = r.u32()? as usize;
                    let bytes = r.bytes(n)?.to_vec();
                    m.datas.push(Data { mem, offset, bytes });
                }
            }
            _ => unreachable!(),
        }
        if r.pos != end {
            return Err(DecodeError { offset: r.pos, msg: format!("section {id} size mismatch: {} unread bytes", end - r.pos) });
        }
    }
    let ndecl = func_decl_count.unwrap_or(0);
    if ndecl != m.codes.len() || (ndecl > 0 && !have_code) {
        return Err(DecodeError { offset: data.len(), msg: format!("function and code section have inconsistent lengths ({ndecl} declared, {} bodies)", m.codes.len()) });
    }
    Ok(m)
}

fn mut_flag(r: &mut Rd) -> R<bool> {
    let at = r.pos;
    match r.byte()? {
        0 => Ok(false),
        1 => Ok(true),
        b => Err(DecodeError { offset: at, msg: format!("invalid mutability flag {b:#x}") }),
    }
}

/// Best-effort name-section parse (function names only). Malformed names are ignored,
/// as the spec says engines may ignore malformed custom sections.
fn parse_names(r: &mut Rd, out: &mut HashMap<u32, String>) {
    while r.pos < r.end {
        let id = match r.byte() {
            Ok(i) => i,
            Err(_) => return,
        };
        let size = match r.u32() {
            Ok(s) => s as usize,
            Err(_) => return,
        };
        if size > r.end - r.pos {
            return;
        }
        let sub_end = r.pos + size;
        if id == 1 {
            let mut sub = Rd { d: r.d, pos: r.pos, end: sub_end };
            let mut tmp = HashMap::new();
            let ok = (|| -> R<()> {
                for _ in 0..sub.vec_len()? {
                    let idx = sub.u32()?;
                    let nm = sub.name()?;
                    tmp.insert(idx, nm);
                }
                Ok(())
            })();
            if ok.is_ok() {
                out.extend(tmp);
            }
        }
        r.pos = sub_end;
    }
}
