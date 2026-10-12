//! In-memory representation of a WebAssembly module.
use std::collections::HashMap;

#[derive(Clone, Copy, PartialEq, Eq, Debug, Hash)]
pub enum ValType {
    I32,
    I64,
    F32,
    F64,
}

impl ValType {
    pub fn name(self) -> &'static str {
        match self {
            ValType::I32 => "i32",
            ValType::I64 => "i64",
            ValType::F32 => "f32",
            ValType::F64 => "f64",
        }
    }
    pub fn parse(s: &str) -> Option<ValType> {
        Some(match s {
            "i32" => ValType::I32,
            "i64" => ValType::I64,
            "f32" => ValType::F32,
            "f64" => ValType::F64,
            _ => return None,
        })
    }
    pub fn byte(self) -> u8 {
        match self {
            ValType::I32 => 0x7f,
            ValType::I64 => 0x7e,
            ValType::F32 => 0x7d,
            ValType::F64 => 0x7c,
        }
    }
    pub fn from_byte(b: u8) -> Option<ValType> {
        Some(match b {
            0x7f => ValType::I32,
            0x7e => ValType::I64,
            0x7d => ValType::F32,
            0x7c => ValType::F64,
            _ => return None,
        })
    }
}

#[derive(Clone, PartialEq, Eq, Debug, Hash, Default)]
pub struct FuncType {
    pub params: Vec<ValType>,
    pub results: Vec<ValType>,
}

impl FuncType {
    pub fn new(params: &[ValType], results: &[ValType]) -> Self {
        FuncType { params: params.to_vec(), results: results.to_vec() }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum BlockType {
    Empty,
    Val(ValType),
    Type(u32),
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Limits {
    pub min: u32,
    pub max: Option<u32>,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct GlobalType {
    pub ty: ValType,
    pub mutable: bool,
}

#[derive(Clone, PartialEq, Debug)]
pub enum ImportDesc {
    Func(u32),
    Table(Limits),
    Mem(Limits),
    Global(GlobalType),
}

#[derive(Clone, PartialEq, Debug)]
pub struct Import {
    pub module: String,
    pub name: String,
    pub desc: ImportDesc,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum ExportKind {
    Func,
    Table,
    Mem,
    Global,
}

#[derive(Clone, PartialEq, Debug)]
pub struct Export {
    pub name: String,
    pub kind: ExportKind,
    pub index: u32,
}

/// Flat instruction form, exactly as laid out in the binary (structured control is
/// delimited by Block/Loop/If … Else … End).
#[derive(Clone, PartialEq, Debug)]
pub enum Instr {
    Unreachable,
    Nop,
    Block(BlockType),
    Loop(BlockType),
    If(BlockType),
    Else,
    End,
    Br(u32),
    BrIf(u32),
    BrTable(Vec<u32>, u32),
    Return,
    Call(u32),
    CallIndirect(u32, u32),
    Drop,
    Select,
    SelectT(ValType),
    LocalGet(u32),
    LocalSet(u32),
    LocalTee(u32),
    GlobalGet(u32),
    GlobalSet(u32),
    /// Load/store: `op` is the binary opcode (0x28..=0x3E); `align` is log2.
    Mem { op: u8, align: u32, offset: u32 },
    MemorySize,
    MemoryGrow,
    MemoryCopy,
    MemoryFill,
    I32Const(i32),
    I64Const(i64),
    F32Const(u32),
    F64Const(u64),
    /// Any plain numeric instruction; code is the opcode, or 0xFC00|sub for saturating truncation.
    Num(u16),
}

#[derive(Clone, PartialEq, Debug)]
pub struct Global {
    pub ty: GlobalType,
    pub init: Vec<Instr>,
}

#[derive(Clone, PartialEq, Debug)]
pub struct Elem {
    pub table: u32,
    pub offset: Vec<Instr>,
    pub funcs: Vec<u32>,
}

#[derive(Clone, PartialEq, Debug)]
pub struct Data {
    pub mem: u32,
    pub offset: Vec<Instr>,
    pub bytes: Vec<u8>,
}

#[derive(Clone, PartialEq, Debug, Default)]
pub struct Code {
    /// Declared locals (not params), one entry per local.
    pub locals: Vec<ValType>,
    /// Body, including the final `End`.
    pub body: Vec<Instr>,
}

#[derive(Clone, Debug, Default)]
pub struct Module {
    pub types: Vec<FuncType>,
    pub imports: Vec<Import>,
    /// Type indices of defined (non-imported) functions.
    pub funcs: Vec<u32>,
    pub tables: Vec<Limits>,
    pub mems: Vec<Limits>,
    pub globals: Vec<Global>,
    pub exports: Vec<Export>,
    pub start: Option<u32>,
    pub elems: Vec<Elem>,
    pub codes: Vec<Code>,
    pub datas: Vec<Data>,
    /// Optional debug names (function index -> name), from WAT `$ids`.
    pub func_names: HashMap<u32, String>,
}

impl Module {
    pub fn imported_funcs(&self) -> Vec<u32> {
        self.imports.iter().filter_map(|i| if let ImportDesc::Func(t) = i.desc { Some(t) } else { None }).collect()
    }
    pub fn num_imported_funcs(&self) -> usize {
        self.imports.iter().filter(|i| matches!(i.desc, ImportDesc::Func(_))).count()
    }
    /// Type index of every function in the function index space.
    pub fn all_func_types(&self) -> Vec<u32> {
        let mut v = self.imported_funcs();
        v.extend(self.funcs.iter().copied());
        v
    }
    pub fn all_tables(&self) -> Vec<Limits> {
        let mut v: Vec<Limits> = self.imports.iter().filter_map(|i| if let ImportDesc::Table(l) = i.desc { Some(l) } else { None }).collect();
        v.extend(self.tables.iter().copied());
        v
    }
    pub fn all_mems(&self) -> Vec<Limits> {
        let mut v: Vec<Limits> = self.imports.iter().filter_map(|i| if let ImportDesc::Mem(l) = i.desc { Some(l) } else { None }).collect();
        v.extend(self.mems.iter().copied());
        v
    }
    pub fn all_globals(&self) -> Vec<GlobalType> {
        let mut v: Vec<GlobalType> = self.imports.iter().filter_map(|i| if let ImportDesc::Global(g) = i.desc { Some(g) } else { None }).collect();
        v.extend(self.globals.iter().map(|g| g.ty));
        v
    }
    pub fn export(&self, name: &str) -> Option<&Export> {
        self.exports.iter().find(|e| e.name == name)
    }
    pub fn func_label(&self, idx: u32) -> String {
        match self.func_names.get(&idx) {
            Some(n) => format!("${n}"),
            None => format!("#{idx}"),
        }
    }
}
