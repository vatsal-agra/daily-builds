"""The WASM MVP instruction set: opcode <-> mnemonic tables plus the shape
of each instruction's immediate operands, shared by the decoder, encoder
and disassembler."""

# immediate kind tags
NONE = None
BLOCKTYPE = "blocktype"
LOCALIDX = "localidx"
GLOBALIDX = "globalidx"
FUNCIDX = "funcidx"
LABELIDX = "labelidx"
BR_TABLE = "br_table"
CALL_INDIRECT = "call_indirect"
MEMARG = "memarg"
I32 = "i32"
I64 = "i64"
F32 = "f32"
F64 = "f64"
MEMORY_IMM = "memory_imm"  # single 0x00 reserved byte (memory.size / memory.grow)

# (mnemonic, opcode, immediate_kind)
_TABLE = [
    ("unreachable", 0x00, NONE),
    ("nop", 0x01, NONE),
    ("block", 0x02, BLOCKTYPE),
    ("loop", 0x03, BLOCKTYPE),
    ("if", 0x04, BLOCKTYPE),
    ("else", 0x05, NONE),
    ("end", 0x0B, NONE),
    ("br", 0x0C, LABELIDX),
    ("br_if", 0x0D, LABELIDX),
    ("br_table", 0x0E, BR_TABLE),
    ("return", 0x0F, NONE),
    ("call", 0x10, FUNCIDX),
    ("call_indirect", 0x11, CALL_INDIRECT),

    ("drop", 0x1A, NONE),
    ("select", 0x1B, NONE),

    ("local.get", 0x20, LOCALIDX),
    ("local.set", 0x21, LOCALIDX),
    ("local.tee", 0x22, LOCALIDX),
    ("global.get", 0x23, GLOBALIDX),
    ("global.set", 0x24, GLOBALIDX),

    ("i32.load", 0x28, MEMARG), ("i64.load", 0x29, MEMARG),
    ("f32.load", 0x2A, MEMARG), ("f64.load", 0x2B, MEMARG),
    ("i32.load8_s", 0x2C, MEMARG), ("i32.load8_u", 0x2D, MEMARG),
    ("i32.load16_s", 0x2E, MEMARG), ("i32.load16_u", 0x2F, MEMARG),
    ("i64.load8_s", 0x30, MEMARG), ("i64.load8_u", 0x31, MEMARG),
    ("i64.load16_s", 0x32, MEMARG), ("i64.load16_u", 0x33, MEMARG),
    ("i64.load32_s", 0x34, MEMARG), ("i64.load32_u", 0x35, MEMARG),
    ("i32.store", 0x36, MEMARG), ("i64.store", 0x37, MEMARG),
    ("f32.store", 0x38, MEMARG), ("f64.store", 0x39, MEMARG),
    ("i32.store8", 0x3A, MEMARG), ("i32.store16", 0x3B, MEMARG),
    ("i64.store8", 0x3C, MEMARG), ("i64.store16", 0x3D, MEMARG),
    ("i64.store32", 0x3E, MEMARG),
    ("memory.size", 0x3F, MEMORY_IMM), ("memory.grow", 0x40, MEMORY_IMM),

    ("i32.const", 0x41, I32), ("i64.const", 0x42, I64),
    ("f32.const", 0x43, F32), ("f64.const", 0x44, F64),

    ("i32.eqz", 0x45, NONE), ("i32.eq", 0x46, NONE), ("i32.ne", 0x47, NONE),
    ("i32.lt_s", 0x48, NONE), ("i32.lt_u", 0x49, NONE),
    ("i32.gt_s", 0x4A, NONE), ("i32.gt_u", 0x4B, NONE),
    ("i32.le_s", 0x4C, NONE), ("i32.le_u", 0x4D, NONE),
    ("i32.ge_s", 0x4E, NONE), ("i32.ge_u", 0x4F, NONE),

    ("i64.eqz", 0x50, NONE), ("i64.eq", 0x51, NONE), ("i64.ne", 0x52, NONE),
    ("i64.lt_s", 0x53, NONE), ("i64.lt_u", 0x54, NONE),
    ("i64.gt_s", 0x55, NONE), ("i64.gt_u", 0x56, NONE),
    ("i64.le_s", 0x57, NONE), ("i64.le_u", 0x58, NONE),
    ("i64.ge_s", 0x59, NONE), ("i64.ge_u", 0x5A, NONE),

    ("f32.eq", 0x5B, NONE), ("f32.ne", 0x5C, NONE),
    ("f32.lt", 0x5D, NONE), ("f32.gt", 0x5E, NONE),
    ("f32.le", 0x5F, NONE), ("f32.ge", 0x60, NONE),

    ("f64.eq", 0x61, NONE), ("f64.ne", 0x62, NONE),
    ("f64.lt", 0x63, NONE), ("f64.gt", 0x64, NONE),
    ("f64.le", 0x65, NONE), ("f64.ge", 0x66, NONE),

    ("i32.clz", 0x67, NONE), ("i32.ctz", 0x68, NONE), ("i32.popcnt", 0x69, NONE),
    ("i32.add", 0x6A, NONE), ("i32.sub", 0x6B, NONE), ("i32.mul", 0x6C, NONE),
    ("i32.div_s", 0x6D, NONE), ("i32.div_u", 0x6E, NONE),
    ("i32.rem_s", 0x6F, NONE), ("i32.rem_u", 0x70, NONE),
    ("i32.and", 0x71, NONE), ("i32.or", 0x72, NONE), ("i32.xor", 0x73, NONE),
    ("i32.shl", 0x74, NONE), ("i32.shr_s", 0x75, NONE), ("i32.shr_u", 0x76, NONE),
    ("i32.rotl", 0x77, NONE), ("i32.rotr", 0x78, NONE),

    ("i64.clz", 0x79, NONE), ("i64.ctz", 0x7A, NONE), ("i64.popcnt", 0x7B, NONE),
    ("i64.add", 0x7C, NONE), ("i64.sub", 0x7D, NONE), ("i64.mul", 0x7E, NONE),
    ("i64.div_s", 0x7F, NONE), ("i64.div_u", 0x80, NONE),
    ("i64.rem_s", 0x81, NONE), ("i64.rem_u", 0x82, NONE),
    ("i64.and", 0x83, NONE), ("i64.or", 0x84, NONE), ("i64.xor", 0x85, NONE),
    ("i64.shl", 0x86, NONE), ("i64.shr_s", 0x87, NONE), ("i64.shr_u", 0x88, NONE),
    ("i64.rotl", 0x89, NONE), ("i64.rotr", 0x8A, NONE),

    ("f32.abs", 0x8B, NONE), ("f32.neg", 0x8C, NONE), ("f32.ceil", 0x8D, NONE),
    ("f32.floor", 0x8E, NONE), ("f32.trunc", 0x8F, NONE), ("f32.nearest", 0x90, NONE),
    ("f32.sqrt", 0x91, NONE), ("f32.add", 0x92, NONE), ("f32.sub", 0x93, NONE),
    ("f32.mul", 0x94, NONE), ("f32.div", 0x95, NONE), ("f32.min", 0x96, NONE),
    ("f32.max", 0x97, NONE), ("f32.copysign", 0x98, NONE),

    ("f64.abs", 0x99, NONE), ("f64.neg", 0x9A, NONE), ("f64.ceil", 0x9B, NONE),
    ("f64.floor", 0x9C, NONE), ("f64.trunc", 0x9D, NONE), ("f64.nearest", 0x9E, NONE),
    ("f64.sqrt", 0x9F, NONE), ("f64.add", 0xA0, NONE), ("f64.sub", 0xA1, NONE),
    ("f64.mul", 0xA2, NONE), ("f64.div", 0xA3, NONE), ("f64.min", 0xA4, NONE),
    ("f64.max", 0xA5, NONE), ("f64.copysign", 0xA6, NONE),

    ("i32.wrap_i64", 0xA7, NONE),
    ("i32.trunc_f32_s", 0xA8, NONE), ("i32.trunc_f32_u", 0xA9, NONE),
    ("i32.trunc_f64_s", 0xAA, NONE), ("i32.trunc_f64_u", 0xAB, NONE),
    ("i64.extend_i32_s", 0xAC, NONE), ("i64.extend_i32_u", 0xAD, NONE),
    ("i64.trunc_f32_s", 0xAE, NONE), ("i64.trunc_f32_u", 0xAF, NONE),
    ("i64.trunc_f64_s", 0xB0, NONE), ("i64.trunc_f64_u", 0xB1, NONE),
    ("f32.convert_i32_s", 0xB2, NONE), ("f32.convert_i32_u", 0xB3, NONE),
    ("f32.convert_i64_s", 0xB4, NONE), ("f32.convert_i64_u", 0xB5, NONE),
    ("f32.demote_f64", 0xB6, NONE),
    ("f64.convert_i32_s", 0xB7, NONE), ("f64.convert_i32_u", 0xB8, NONE),
    ("f64.convert_i64_s", 0xB9, NONE), ("f64.convert_i64_u", 0xBA, NONE),
    ("f64.promote_f32", 0xBB, NONE),
    ("i32.reinterpret_f32", 0xBC, NONE), ("i64.reinterpret_f64", 0xBD, NONE),
    ("f32.reinterpret_i32", 0xBE, NONE), ("f64.reinterpret_i64", 0xBF, NONE),
]

BY_NAME = {name: (opcode, imm) for name, opcode, imm in _TABLE}
BY_OPCODE = {opcode: (name, imm) for name, opcode, imm in _TABLE}

# Opcodes that open a nested block and must be balanced by a matching `end`
# (and, for `if`, an optional `else`).
BLOCK_OPENERS = {0x02, 0x03, 0x04}
END_OPCODE = 0x0B
ELSE_OPCODE = 0x05
