//! Plain numeric instructions: the opcode table (names + signatures) and exact semantics.
use crate::ast::ValType;
use crate::ast::ValType::*;
use crate::trap::Trap;
use std::collections::HashMap;
use std::sync::OnceLock;

pub struct NumOp {
    pub code: u16,
    pub name: &'static str,
    pub params: &'static [ValType],
    pub result: ValType,
}

const P1_I32: &[ValType] = &[I32];
const P1_I64: &[ValType] = &[I64];
const P1_F32: &[ValType] = &[F32];
const P1_F64: &[ValType] = &[F64];
const P2_I32: &[ValType] = &[I32, I32];
const P2_I64: &[ValType] = &[I64, I64];
const P2_F32: &[ValType] = &[F32, F32];
const P2_F64: &[ValType] = &[F64, F64];

fn p1(t: ValType) -> &'static [ValType] {
    match t {
        I32 => P1_I32,
        I64 => P1_I64,
        F32 => P1_F32,
        F64 => P1_F64,
    }
}
fn p2(t: ValType) -> &'static [ValType] {
    match t {
        I32 => P2_I32,
        I64 => P2_I64,
        F32 => P2_F32,
        F64 => P2_F64,
    }
}

fn build() -> Vec<NumOp> {
    let mut v: Vec<NumOp> = Vec::new();
    let mut add = |code: u16, name: String, params: &'static [ValType], result: ValType| {
        v.push(NumOp { code, name: Box::leak(name.into_boxed_str()), params, result });
    };
    let icmp = ["eq", "ne", "lt_s", "lt_u", "gt_s", "gt_u", "le_s", "le_u", "ge_s", "ge_u"];
    let fcmp = ["eq", "ne", "lt", "gt", "le", "ge"];
    let ibin = ["add", "sub", "mul", "div_s", "div_u", "rem_s", "rem_u", "and", "or", "xor", "shl", "shr_s", "shr_u", "rotl", "rotr"];
    let iun = ["clz", "ctz", "popcnt"];
    let fun = ["abs", "neg", "ceil", "floor", "trunc", "nearest", "sqrt"];
    let fbin = ["add", "sub", "mul", "div", "min", "max", "copysign"];

    add(0x45, "i32.eqz".into(), P1_I32, I32);
    for (i, n) in icmp.iter().enumerate() {
        add(0x46 + i as u16, format!("i32.{n}"), P2_I32, I32);
    }
    add(0x50, "i64.eqz".into(), P1_I64, I32);
    for (i, n) in icmp.iter().enumerate() {
        add(0x51 + i as u16, format!("i64.{n}"), P2_I64, I32);
    }
    for (i, n) in fcmp.iter().enumerate() {
        add(0x5B + i as u16, format!("f32.{n}"), P2_F32, I32);
        add(0x61 + i as u16, format!("f64.{n}"), P2_F64, I32);
    }
    for (i, n) in iun.iter().enumerate() {
        add(0x67 + i as u16, format!("i32.{n}"), P1_I32, I32);
        add(0x79 + i as u16, format!("i64.{n}"), P1_I64, I64);
    }
    for (i, n) in ibin.iter().enumerate() {
        add(0x6A + i as u16, format!("i32.{n}"), P2_I32, I32);
        add(0x7C + i as u16, format!("i64.{n}"), P2_I64, I64);
    }
    for (i, n) in fun.iter().enumerate() {
        add(0x8B + i as u16, format!("f32.{n}"), P1_F32, F32);
        add(0x99 + i as u16, format!("f64.{n}"), P1_F64, F64);
    }
    for (i, n) in fbin.iter().enumerate() {
        add(0x92 + i as u16, format!("f32.{n}"), P2_F32, F32);
        add(0xA0 + i as u16, format!("f64.{n}"), P2_F64, F64);
    }
    let conv: &[(u16, &str, ValType, ValType)] = &[
        (0xA7, "i32.wrap_i64", I64, I32),
        (0xA8, "i32.trunc_f32_s", F32, I32),
        (0xA9, "i32.trunc_f32_u", F32, I32),
        (0xAA, "i32.trunc_f64_s", F64, I32),
        (0xAB, "i32.trunc_f64_u", F64, I32),
        (0xAC, "i64.extend_i32_s", I32, I64),
        (0xAD, "i64.extend_i32_u", I32, I64),
        (0xAE, "i64.trunc_f32_s", F32, I64),
        (0xAF, "i64.trunc_f32_u", F32, I64),
        (0xB0, "i64.trunc_f64_s", F64, I64),
        (0xB1, "i64.trunc_f64_u", F64, I64),
        (0xB2, "f32.convert_i32_s", I32, F32),
        (0xB3, "f32.convert_i32_u", I32, F32),
        (0xB4, "f32.convert_i64_s", I64, F32),
        (0xB5, "f32.convert_i64_u", I64, F32),
        (0xB6, "f32.demote_f64", F64, F32),
        (0xB7, "f64.convert_i32_s", I32, F64),
        (0xB8, "f64.convert_i32_u", I32, F64),
        (0xB9, "f64.convert_i64_s", I64, F64),
        (0xBA, "f64.convert_i64_u", I64, F64),
        (0xBB, "f64.promote_f32", F32, F64),
        (0xBC, "i32.reinterpret_f32", F32, I32),
        (0xBD, "i64.reinterpret_f64", F64, I64),
        (0xBE, "f32.reinterpret_i32", I32, F32),
        (0xBF, "f64.reinterpret_i64", I64, F64),
        (0xC0, "i32.extend8_s", I32, I32),
        (0xC1, "i32.extend16_s", I32, I32),
        (0xC2, "i64.extend8_s", I64, I64),
        (0xC3, "i64.extend16_s", I64, I64),
        (0xC4, "i64.extend32_s", I64, I64),
        (0xFC00, "i32.trunc_sat_f32_s", F32, I32),
        (0xFC01, "i32.trunc_sat_f32_u", F32, I32),
        (0xFC02, "i32.trunc_sat_f64_s", F64, I32),
        (0xFC03, "i32.trunc_sat_f64_u", F64, I32),
        (0xFC04, "i64.trunc_sat_f32_s", F32, I64),
        (0xFC05, "i64.trunc_sat_f32_u", F32, I64),
        (0xFC06, "i64.trunc_sat_f64_s", F64, I64),
        (0xFC07, "i64.trunc_sat_f64_u", F64, I64),
    ];
    for &(c, n, from, to) in conv {
        add(c, n.to_string(), p1(from), to);
    }
    let _ = p2;
    v
}

fn table() -> &'static Vec<NumOp> {
    static T: OnceLock<Vec<NumOp>> = OnceLock::new();
    T.get_or_init(build)
}

pub fn all() -> &'static [NumOp] {
    table()
}

pub fn by_code(code: u16) -> Option<&'static NumOp> {
    static M: OnceLock<HashMap<u16, usize>> = OnceLock::new();
    let m = M.get_or_init(|| table().iter().enumerate().map(|(i, o)| (o.code, i)).collect());
    m.get(&code).map(|&i| &table()[i])
}

pub fn by_name(name: &str) -> Option<&'static NumOp> {
    static M: OnceLock<HashMap<&'static str, usize>> = OnceLock::new();
    let m = M.get_or_init(|| table().iter().enumerate().map(|(i, o)| (o.name, i)).collect());
    m.get(name).map(|&i| &table()[i])
}

/// Load/store opcode table: (opcode, name, value type, access width in bytes).
pub const MEM_OPS: &[(u8, &str, ValType, u32)] = &[
    (0x28, "i32.load", I32, 4),
    (0x29, "i64.load", I64, 8),
    (0x2A, "f32.load", F32, 4),
    (0x2B, "f64.load", F64, 8),
    (0x2C, "i32.load8_s", I32, 1),
    (0x2D, "i32.load8_u", I32, 1),
    (0x2E, "i32.load16_s", I32, 2),
    (0x2F, "i32.load16_u", I32, 2),
    (0x30, "i64.load8_s", I64, 1),
    (0x31, "i64.load8_u", I64, 1),
    (0x32, "i64.load16_s", I64, 2),
    (0x33, "i64.load16_u", I64, 2),
    (0x34, "i64.load32_s", I64, 4),
    (0x35, "i64.load32_u", I64, 4),
    (0x36, "i32.store", I32, 4),
    (0x37, "i64.store", I64, 8),
    (0x38, "f32.store", F32, 4),
    (0x39, "f64.store", F64, 8),
    (0x3A, "i32.store8", I32, 1),
    (0x3B, "i32.store16", I32, 2),
    (0x3C, "i64.store8", I64, 1),
    (0x3D, "i64.store16", I64, 2),
    (0x3E, "i64.store32", I64, 4),
];

pub fn mem_op(op: u8) -> Option<&'static (u8, &'static str, ValType, u32)> {
    MEM_OPS.iter().find(|m| m.0 == op)
}
pub fn mem_op_by_name(name: &str) -> Option<&'static (u8, &'static str, ValType, u32)> {
    MEM_OPS.iter().find(|m| m.1 == name)
}
pub fn is_store(op: u8) -> bool {
    op >= 0x36
}

// ---- raw value-slot helpers (all values live in u64 slots) ----
#[inline(always)]
pub fn pop_i32(s: &mut Vec<u64>) -> i32 {
    s.pop().unwrap() as u32 as i32
}
#[inline(always)]
pub fn pop_i64(s: &mut Vec<u64>) -> i64 {
    s.pop().unwrap() as i64
}
#[inline(always)]
pub fn pop_f32(s: &mut Vec<u64>) -> f32 {
    f32::from_bits(s.pop().unwrap() as u32)
}
#[inline(always)]
pub fn pop_f64(s: &mut Vec<u64>) -> f64 {
    f64::from_bits(s.pop().unwrap())
}
#[inline(always)]
pub fn push_i32(s: &mut Vec<u64>, v: i32) {
    s.push(v as u32 as u64)
}
#[inline(always)]
pub fn push_i64(s: &mut Vec<u64>, v: i64) {
    s.push(v as u64)
}
#[inline(always)]
pub fn push_f32(s: &mut Vec<u64>, v: f32) {
    s.push(v.to_bits() as u64)
}
#[inline(always)]
pub fn push_f64(s: &mut Vec<u64>, v: f64) {
    s.push(v.to_bits())
}

pub fn fmin32(a: f32, b: f32) -> f32 {
    if a.is_nan() || b.is_nan() {
        f32::NAN
    } else if a == b {
        if a.is_sign_negative() { a } else { b }
    } else if a < b {
        a
    } else {
        b
    }
}
pub fn fmax32(a: f32, b: f32) -> f32 {
    if a.is_nan() || b.is_nan() {
        f32::NAN
    } else if a == b {
        if a.is_sign_negative() { b } else { a }
    } else if a > b {
        a
    } else {
        b
    }
}
pub fn fmin64(a: f64, b: f64) -> f64 {
    if a.is_nan() || b.is_nan() {
        f64::NAN
    } else if a == b {
        if a.is_sign_negative() { a } else { b }
    } else if a < b {
        a
    } else {
        b
    }
}
pub fn fmax64(a: f64, b: f64) -> f64 {
    if a.is_nan() || b.is_nan() {
        f64::NAN
    } else if a == b {
        if a.is_sign_negative() { b } else { a }
    } else if a > b {
        a
    } else {
        b
    }
}

fn check_nan(x: f64) -> Result<(), Trap> {
    if x.is_nan() { Err(Trap::InvalidConversion) } else { Ok(()) }
}
pub fn trunc_i32_s(x: f64) -> Result<i32, Trap> {
    check_nan(x)?;
    let t = x.trunc();
    if t >= -2147483648.0 && t < 2147483648.0 { Ok(t as i32) } else { Err(Trap::IntOverflow) }
}
pub fn trunc_i32_u(x: f64) -> Result<u32, Trap> {
    check_nan(x)?;
    let t = x.trunc();
    if t > -1.0 && t < 4294967296.0 { Ok(t as u32) } else { Err(Trap::IntOverflow) }
}
pub fn trunc_i64_s(x: f64) -> Result<i64, Trap> {
    check_nan(x)?;
    let t = x.trunc();
    if t >= -9223372036854775808.0 && t < 9223372036854775808.0 { Ok(t as i64) } else { Err(Trap::IntOverflow) }
}
pub fn trunc_i64_u(x: f64) -> Result<u64, Trap> {
    check_nan(x)?;
    let t = x.trunc();
    if t > -1.0 && t < 18446744073709551616.0 { Ok(t as u64) } else { Err(Trap::IntOverflow) }
}

macro_rules! bin {
    ($s:ident, $pop:ident, $push:ident, $a:ident, $b:ident, $e:expr) => {{
        let $b = $pop($s);
        let $a = $pop($s);
        $push($s, $e);
    }};
}
macro_rules! cmp {
    ($s:ident, $pop:ident, $a:ident, $b:ident, $e:expr) => {{
        let $b = $pop($s);
        let $a = $pop($s);
        push_i32($s, ($e) as i32);
    }};
}
macro_rules! un {
    ($s:ident, $pop:ident, $push:ident, $a:ident, $e:expr) => {{
        let $a = $pop($s);
        $push($s, $e);
    }};
}

/// Execute one plain numeric instruction against the value stack.
pub fn exec(code: u16, s: &mut Vec<u64>) -> Result<(), Trap> {
    match code {
        // i32 comparisons
        0x45 => un!(s, pop_i32, push_i32, a, (a == 0) as i32),
        0x46 => cmp!(s, pop_i32, a, b, a == b),
        0x47 => cmp!(s, pop_i32, a, b, a != b),
        0x48 => cmp!(s, pop_i32, a, b, a < b),
        0x49 => cmp!(s, pop_i32, a, b, (a as u32) < (b as u32)),
        0x4A => cmp!(s, pop_i32, a, b, a > b),
        0x4B => cmp!(s, pop_i32, a, b, (a as u32) > (b as u32)),
        0x4C => cmp!(s, pop_i32, a, b, a <= b),
        0x4D => cmp!(s, pop_i32, a, b, (a as u32) <= (b as u32)),
        0x4E => cmp!(s, pop_i32, a, b, a >= b),
        0x4F => cmp!(s, pop_i32, a, b, (a as u32) >= (b as u32)),
        // i64 comparisons
        0x50 => {
            let a = pop_i64(s);
            push_i32(s, (a == 0) as i32)
        }
        0x51 => cmp!(s, pop_i64, a, b, a == b),
        0x52 => cmp!(s, pop_i64, a, b, a != b),
        0x53 => cmp!(s, pop_i64, a, b, a < b),
        0x54 => cmp!(s, pop_i64, a, b, (a as u64) < (b as u64)),
        0x55 => cmp!(s, pop_i64, a, b, a > b),
        0x56 => cmp!(s, pop_i64, a, b, (a as u64) > (b as u64)),
        0x57 => cmp!(s, pop_i64, a, b, a <= b),
        0x58 => cmp!(s, pop_i64, a, b, (a as u64) <= (b as u64)),
        0x59 => cmp!(s, pop_i64, a, b, a >= b),
        0x5A => cmp!(s, pop_i64, a, b, (a as u64) >= (b as u64)),
        // float comparisons
        0x5B => cmp!(s, pop_f32, a, b, a == b),
        0x5C => cmp!(s, pop_f32, a, b, a != b),
        0x5D => cmp!(s, pop_f32, a, b, a < b),
        0x5E => cmp!(s, pop_f32, a, b, a > b),
        0x5F => cmp!(s, pop_f32, a, b, a <= b),
        0x60 => cmp!(s, pop_f32, a, b, a >= b),
        0x61 => cmp!(s, pop_f64, a, b, a == b),
        0x62 => cmp!(s, pop_f64, a, b, a != b),
        0x63 => cmp!(s, pop_f64, a, b, a < b),
        0x64 => cmp!(s, pop_f64, a, b, a > b),
        0x65 => cmp!(s, pop_f64, a, b, a <= b),
        0x66 => cmp!(s, pop_f64, a, b, a >= b),
        // i32 arithmetic
        0x67 => un!(s, pop_i32, push_i32, a, a.leading_zeros() as i32),
        0x68 => un!(s, pop_i32, push_i32, a, a.trailing_zeros() as i32),
        0x69 => un!(s, pop_i32, push_i32, a, a.count_ones() as i32),
        0x6A => bin!(s, pop_i32, push_i32, a, b, a.wrapping_add(b)),
        0x6B => bin!(s, pop_i32, push_i32, a, b, a.wrapping_sub(b)),
        0x6C => bin!(s, pop_i32, push_i32, a, b, a.wrapping_mul(b)),
        0x6D => {
            let b = pop_i32(s);
            let a = pop_i32(s);
            if b == 0 {
                return Err(Trap::IntDivZero);
            }
            if a == i32::MIN && b == -1 {
                return Err(Trap::IntOverflow);
            }
            push_i32(s, a / b)
        }
        0x6E => {
            let b = pop_i32(s) as u32;
            let a = pop_i32(s) as u32;
            if b == 0 {
                return Err(Trap::IntDivZero);
            }
            push_i32(s, (a / b) as i32)
        }
        0x6F => {
            let b = pop_i32(s);
            let a = pop_i32(s);
            if b == 0 {
                return Err(Trap::IntDivZero);
            }
            push_i32(s, a.wrapping_rem(b))
        }
        0x70 => {
            let b = pop_i32(s) as u32;
            let a = pop_i32(s) as u32;
            if b == 0 {
                return Err(Trap::IntDivZero);
            }
            push_i32(s, (a % b) as i32)
        }
        0x71 => bin!(s, pop_i32, push_i32, a, b, a & b),
        0x72 => bin!(s, pop_i32, push_i32, a, b, a | b),
        0x73 => bin!(s, pop_i32, push_i32, a, b, a ^ b),
        0x74 => bin!(s, pop_i32, push_i32, a, b, a.wrapping_shl(b as u32)),
        0x75 => bin!(s, pop_i32, push_i32, a, b, a.wrapping_shr(b as u32)),
        0x76 => bin!(s, pop_i32, push_i32, a, b, ((a as u32).wrapping_shr(b as u32)) as i32),
        0x77 => bin!(s, pop_i32, push_i32, a, b, (a as u32).rotate_left(b as u32 & 31) as i32),
        0x78 => bin!(s, pop_i32, push_i32, a, b, (a as u32).rotate_right(b as u32 & 31) as i32),
        // i64 arithmetic
        0x79 => un!(s, pop_i64, push_i64, a, a.leading_zeros() as i64),
        0x7A => un!(s, pop_i64, push_i64, a, a.trailing_zeros() as i64),
        0x7B => un!(s, pop_i64, push_i64, a, a.count_ones() as i64),
        0x7C => bin!(s, pop_i64, push_i64, a, b, a.wrapping_add(b)),
        0x7D => bin!(s, pop_i64, push_i64, a, b, a.wrapping_sub(b)),
        0x7E => bin!(s, pop_i64, push_i64, a, b, a.wrapping_mul(b)),
        0x7F => {
            let b = pop_i64(s);
            let a = pop_i64(s);
            if b == 0 {
                return Err(Trap::IntDivZero);
            }
            if a == i64::MIN && b == -1 {
                return Err(Trap::IntOverflow);
            }
            push_i64(s, a / b)
        }
        0x80 => {
            let b = pop_i64(s) as u64;
            let a = pop_i64(s) as u64;
            if b == 0 {
                return Err(Trap::IntDivZero);
            }
            push_i64(s, (a / b) as i64)
        }
        0x81 => {
            let b = pop_i64(s);
            let a = pop_i64(s);
            if b == 0 {
                return Err(Trap::IntDivZero);
            }
            push_i64(s, a.wrapping_rem(b))
        }
        0x82 => {
            let b = pop_i64(s) as u64;
            let a = pop_i64(s) as u64;
            if b == 0 {
                return Err(Trap::IntDivZero);
            }
            push_i64(s, (a % b) as i64)
        }
        0x83 => bin!(s, pop_i64, push_i64, a, b, a & b),
        0x84 => bin!(s, pop_i64, push_i64, a, b, a | b),
        0x85 => bin!(s, pop_i64, push_i64, a, b, a ^ b),
        0x86 => bin!(s, pop_i64, push_i64, a, b, a.wrapping_shl(b as u32)),
        0x87 => bin!(s, pop_i64, push_i64, a, b, a.wrapping_shr(b as u32)),
        0x88 => bin!(s, pop_i64, push_i64, a, b, ((a as u64).wrapping_shr(b as u32)) as i64),
        0x89 => bin!(s, pop_i64, push_i64, a, b, (a as u64).rotate_left(b as u32 & 63) as i64),
        0x8A => bin!(s, pop_i64, push_i64, a, b, (a as u64).rotate_right(b as u32 & 63) as i64),
        // f32
        0x8B => un!(s, pop_f32, push_f32, a, a.abs()),
        0x8C => un!(s, pop_f32, push_f32, a, -a),
        0x8D => un!(s, pop_f32, push_f32, a, a.ceil()),
        0x8E => un!(s, pop_f32, push_f32, a, a.floor()),
        0x8F => un!(s, pop_f32, push_f32, a, a.trunc()),
        0x90 => un!(s, pop_f32, push_f32, a, a.round_ties_even()),
        0x91 => un!(s, pop_f32, push_f32, a, a.sqrt()),
        0x92 => bin!(s, pop_f32, push_f32, a, b, a + b),
        0x93 => bin!(s, pop_f32, push_f32, a, b, a - b),
        0x94 => bin!(s, pop_f32, push_f32, a, b, a * b),
        0x95 => bin!(s, pop_f32, push_f32, a, b, a / b),
        0x96 => bin!(s, pop_f32, push_f32, a, b, fmin32(a, b)),
        0x97 => bin!(s, pop_f32, push_f32, a, b, fmax32(a, b)),
        0x98 => bin!(s, pop_f32, push_f32, a, b, a.copysign(b)),
        // f64
        0x99 => un!(s, pop_f64, push_f64, a, a.abs()),
        0x9A => un!(s, pop_f64, push_f64, a, -a),
        0x9B => un!(s, pop_f64, push_f64, a, a.ceil()),
        0x9C => un!(s, pop_f64, push_f64, a, a.floor()),
        0x9D => un!(s, pop_f64, push_f64, a, a.trunc()),
        0x9E => un!(s, pop_f64, push_f64, a, a.round_ties_even()),
        0x9F => un!(s, pop_f64, push_f64, a, a.sqrt()),
        0xA0 => bin!(s, pop_f64, push_f64, a, b, a + b),
        0xA1 => bin!(s, pop_f64, push_f64, a, b, a - b),
        0xA2 => bin!(s, pop_f64, push_f64, a, b, a * b),
        0xA3 => bin!(s, pop_f64, push_f64, a, b, a / b),
        0xA4 => bin!(s, pop_f64, push_f64, a, b, fmin64(a, b)),
        0xA5 => bin!(s, pop_f64, push_f64, a, b, fmax64(a, b)),
        0xA6 => bin!(s, pop_f64, push_f64, a, b, a.copysign(b)),
        // conversions
        0xA7 => {
            let a = pop_i64(s);
            push_i32(s, a as i32)
        }
        0xA8 => {
            let a = pop_f32(s);
            push_i32(s, trunc_i32_s(a as f64)?)
        }
        0xA9 => {
            let a = pop_f32(s);
            push_i32(s, trunc_i32_u(a as f64)? as i32)
        }
        0xAA => {
            let a = pop_f64(s);
            push_i32(s, trunc_i32_s(a)?)
        }
        0xAB => {
            let a = pop_f64(s);
            push_i32(s, trunc_i32_u(a)? as i32)
        }
        0xAC => {
            let a = pop_i32(s);
            push_i64(s, a as i64)
        }
        0xAD => {
            let a = pop_i32(s);
            push_i64(s, a as u32 as i64)
        }
        0xAE => {
            let a = pop_f32(s);
            push_i64(s, trunc_i64_s(a as f64)?)
        }
        0xAF => {
            let a = pop_f32(s);
            push_i64(s, trunc_i64_u(a as f64)? as i64)
        }
        0xB0 => {
            let a = pop_f64(s);
            push_i64(s, trunc_i64_s(a)?)
        }
        0xB1 => {
            let a = pop_f64(s);
            push_i64(s, trunc_i64_u(a)? as i64)
        }
        0xB2 => {
            let a = pop_i32(s);
            push_f32(s, a as f32)
        }
        0xB3 => {
            let a = pop_i32(s);
            push_f32(s, a as u32 as f32)
        }
        0xB4 => {
            let a = pop_i64(s);
            push_f32(s, a as f32)
        }
        0xB5 => {
            let a = pop_i64(s);
            push_f32(s, a as u64 as f32)
        }
        0xB6 => {
            let a = pop_f64(s);
            push_f32(s, a as f32)
        }
        0xB7 => {
            let a = pop_i32(s);
            push_f64(s, a as f64)
        }
        0xB8 => {
            let a = pop_i32(s);
            push_f64(s, a as u32 as f64)
        }
        0xB9 => {
            let a = pop_i64(s);
            push_f64(s, a as f64)
        }
        0xBA => {
            let a = pop_i64(s);
            push_f64(s, a as u64 as f64)
        }
        0xBB => {
            let a = pop_f32(s);
            push_f64(s, a as f64)
        }
        // reinterpret: the slot representation already holds the bits; just normalise width.
        0xBC => {
            let a = pop_f32(s);
            push_i32(s, a.to_bits() as i32)
        }
        0xBD => {
            let a = pop_f64(s);
            push_i64(s, a.to_bits() as i64)
        }
        0xBE => {
            let a = pop_i32(s);
            push_f32(s, f32::from_bits(a as u32))
        }
        0xBF => {
            let a = pop_i64(s);
            push_f64(s, f64::from_bits(a as u64))
        }
        0xC0 => un!(s, pop_i32, push_i32, a, a as i8 as i32),
        0xC1 => un!(s, pop_i32, push_i32, a, a as i16 as i32),
        0xC2 => un!(s, pop_i64, push_i64, a, a as i8 as i64),
        0xC3 => un!(s, pop_i64, push_i64, a, a as i16 as i64),
        0xC4 => un!(s, pop_i64, push_i64, a, a as i32 as i64),
        // saturating truncation (Rust `as` saturates and maps NaN to 0, as the spec requires)
        0xFC00 => {
            let a = pop_f32(s);
            push_i32(s, a as i32)
        }
        0xFC01 => {
            let a = pop_f32(s);
            push_i32(s, (a as u32) as i32)
        }
        0xFC02 => {
            let a = pop_f64(s);
            push_i32(s, a as i32)
        }
        0xFC03 => {
            let a = pop_f64(s);
            push_i32(s, (a as u32) as i32)
        }
        0xFC04 => {
            let a = pop_f32(s);
            push_i64(s, a as i64)
        }
        0xFC05 => {
            let a = pop_f32(s);
            push_i64(s, (a as u64) as i64)
        }
        0xFC06 => {
            let a = pop_f64(s);
            push_i64(s, a as i64)
        }
        0xFC07 => {
            let a = pop_f64(s);
            push_i64(s, (a as u64) as i64)
        }
        _ => unreachable!("unknown numeric opcode {code:#x}"),
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn run1(code: u16, args: &[u64]) -> Result<u64, Trap> {
        let mut s = args.to_vec();
        exec(code, &mut s)?;
        Ok(s.pop().unwrap())
    }

    #[test]
    fn table_is_complete_and_consistent() {
        for op in all() {
            assert_eq!(by_code(op.code).unwrap().name, op.name);
            assert_eq!(by_name(op.name).unwrap().code, op.code);
        }
        // every opcode in 0x45..=0xC4 is covered exactly once; plus 8 sat ops
        assert_eq!(all().len(), (0xC4 - 0x45 + 1) + 8);
        let mut codes: Vec<u16> = all().iter().map(|o| o.code).collect();
        codes.sort();
        codes.dedup();
        assert_eq!(codes.len(), all().len());
    }

    #[test]
    fn division_edge_cases() {
        assert_eq!(run1(0x6D, &[1, 0]), Err(Trap::IntDivZero));
        assert_eq!(run1(0x6D, &[0x8000_0000, 0xFFFF_FFFF]), Err(Trap::IntOverflow));
        assert_eq!(run1(0x6F, &[0x8000_0000, 0xFFFF_FFFF]), Ok(0));
        assert_eq!(run1(0x7F, &[i64::MIN as u64, u64::MAX]), Err(Trap::IntOverflow));
        assert_eq!(run1(0x81, &[i64::MIN as u64, u64::MAX]), Ok(0));
        assert_eq!(run1(0x6E, &[0xFFFF_FFFF, 2]), Ok(0x7FFF_FFFF));
    }

    #[test]
    fn float_semantics() {
        assert!(fmin32(f32::NAN, 1.0).is_nan());
        assert!(fmin32(0.0, -0.0).is_sign_negative());
        assert!(fmin32(-0.0, 0.0).is_sign_negative());
        assert!(fmax32(0.0, -0.0).is_sign_positive());
        assert!(fmax64(-0.0, 0.0).is_sign_positive());
        // nearest: ties to even
        assert_eq!(f64::from_bits(run1(0x9E, &[2.5f64.to_bits()]).unwrap()), 2.0);
        assert_eq!(f64::from_bits(run1(0x9E, &[3.5f64.to_bits()]).unwrap()), 4.0);
        assert_eq!(f64::from_bits(run1(0x9E, &[(-0.5f64).to_bits()]).unwrap()).to_bits(), (-0.0f64).to_bits());
    }

    #[test]
    fn truncation_boundaries() {
        assert_eq!(trunc_i32_s(2147483647.9), Ok(i32::MAX));
        assert_eq!(trunc_i32_s(2147483648.0), Err(Trap::IntOverflow));
        assert_eq!(trunc_i32_s(-2147483648.9), Ok(i32::MIN));
        assert_eq!(trunc_i32_s(-2147483649.0), Err(Trap::IntOverflow));
        assert_eq!(trunc_i32_u(-0.9), Ok(0));
        assert_eq!(trunc_i32_u(-1.0), Err(Trap::IntOverflow));
        assert_eq!(trunc_i32_s(f64::NAN), Err(Trap::InvalidConversion));
        assert_eq!(trunc_i64_u(18446744073709551615.0), Err(Trap::IntOverflow)); // rounds to 2^64
        assert_eq!(trunc_i64_s(-9223372036854775808.0), Ok(i64::MIN));
        // saturating
        assert_eq!(run1(0xFC00, &[f32::NAN.to_bits() as u64]), Ok(0));
        assert_eq!(run1(0xFC02, &[1e20f64.to_bits()]), Ok(i32::MAX as u32 as u64));
        assert_eq!(run1(0xFC03, &[(-5.0f64).to_bits()]), Ok(0));
    }

    #[test]
    fn shifts_and_rotates_mask_counts() {
        assert_eq!(run1(0x74, &[1, 33]), Ok(2));
        assert_eq!(run1(0x77, &[0x8000_0001, 1]), Ok(3));
        assert_eq!(run1(0x86, &[1, 65]), Ok(2));
        assert_eq!(run1(0x75, &[0x8000_0000, 31]), Ok(0xFFFF_FFFF));
    }
}
