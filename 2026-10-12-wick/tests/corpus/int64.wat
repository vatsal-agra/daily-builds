;; i64 arithmetic and conversions between widths.
(module
  (func (export "add") (param i64 i64) (result i64) (i64.add (local.get 0) (local.get 1)))
  (func (export "mul") (param i64 i64) (result i64) (i64.mul (local.get 0) (local.get 1)))
  (func (export "div_s") (param i64 i64) (result i64) (i64.div_s (local.get 0) (local.get 1)))
  (func (export "div_u") (param i64 i64) (result i64) (i64.div_u (local.get 0) (local.get 1)))
  (func (export "rem_s") (param i64 i64) (result i64) (i64.rem_s (local.get 0) (local.get 1)))
  (func (export "rem_u") (param i64 i64) (result i64) (i64.rem_u (local.get 0) (local.get 1)))
  (func (export "shl") (param i64 i64) (result i64) (i64.shl (local.get 0) (local.get 1)))
  (func (export "shr_s") (param i64 i64) (result i64) (i64.shr_s (local.get 0) (local.get 1)))
  (func (export "shr_u") (param i64 i64) (result i64) (i64.shr_u (local.get 0) (local.get 1)))
  (func (export "rotl") (param i64 i64) (result i64) (i64.rotl (local.get 0) (local.get 1)))
  (func (export "rotr") (param i64 i64) (result i64) (i64.rotr (local.get 0) (local.get 1)))
  (func (export "clz") (param i64) (result i64) (i64.clz (local.get 0)))
  (func (export "ctz") (param i64) (result i64) (i64.ctz (local.get 0)))
  (func (export "popcnt") (param i64) (result i64) (i64.popcnt (local.get 0)))
  (func (export "eqz") (param i64) (result i32) (i64.eqz (local.get 0)))
  (func (export "lt_u") (param i64 i64) (result i32) (i64.lt_u (local.get 0) (local.get 1)))
  (func (export "lt_s") (param i64 i64) (result i32) (i64.lt_s (local.get 0) (local.get 1)))
  (func (export "wrap") (param i64) (result i32) (i32.wrap_i64 (local.get 0)))
  (func (export "ext_s") (param i32) (result i64) (i64.extend_i32_s (local.get 0)))
  (func (export "ext_u") (param i32) (result i64) (i64.extend_i32_u (local.get 0)))
  (func (export "ext8") (param i64) (result i64) (i64.extend8_s (local.get 0)))
  (func (export "ext16") (param i64) (result i64) (i64.extend16_s (local.get 0)))
  (func (export "ext32") (param i64) (result i64) (i64.extend32_s (local.get 0)))
)
;; assert add i64:9223372036854775807 i64:1 => i64:-9223372036854775808
;; assert mul i64:4294967296 i64:4294967296 => i64:0
;; assert mul i64:-9223372036854775808 i64:-1 => i64:-9223372036854775808
;; assert div_s i64:-7 i64:2 => i64:-3
;; trap div_s i64:-9223372036854775808 i64:-1 => int_overflow_or_conv
;; trap div_s i64:1 i64:0 => div_zero
;; assert div_u i64:-1 i64:2 => i64:9223372036854775807
;; assert rem_s i64:-9223372036854775808 i64:-1 => i64:0
;; assert rem_s i64:-7 i64:2 => i64:-1
;; assert rem_u i64:-1 i64:10 => i64:5
;; trap rem_u i64:1 i64:0 => div_zero
;; assert shl i64:1 i64:63 => i64:-9223372036854775808
;; assert shl i64:1 i64:64 => i64:1
;; assert shr_s i64:-8 i64:1 => i64:-4
;; assert shr_u i64:-1 i64:63 => i64:1
;; assert rotl i64:-9223372036854775807 i64:1 => i64:3
;; assert rotr i64:1 i64:1 => i64:-9223372036854775808
;; assert clz i64:0 => i64:64
;; assert clz i64:1 => i64:63
;; assert ctz i64:0 => i64:64
;; assert ctz i64:-9223372036854775808 => i64:63
;; assert popcnt i64:-1 => i64:64
;; assert eqz i64:0 => i32:1
;; assert eqz i64:4294967296 => i32:0
;; assert lt_u i64:-1 i64:1 => i32:0
;; assert lt_s i64:-1 i64:1 => i32:1
;; assert wrap i64:0x1ffffffff => i32:-1
;; assert wrap i64:0x100000000 => i32:0
;; assert ext_s i32:-1 => i64:-1
;; assert ext_u i32:-1 => i64:4294967295
;; assert ext8 i64:0x80 => i64:-128
;; assert ext16 i64:0xffff => i64:-1
;; assert ext32 i64:0x80000000 => i64:-2147483648
;; assert ext32 i64:0x17fffffff => i64:2147483647
