;; Numeric conversions: trapping and saturating truncation, int->float rounding, demote/promote.
(module
  (func (export "i32_trunc_f32_s") (param f32) (result i32) (i32.trunc_f32_s (local.get 0)))
  (func (export "i32_trunc_f32_u") (param f32) (result i32) (i32.trunc_f32_u (local.get 0)))
  (func (export "i32_trunc_f64_s") (param f64) (result i32) (i32.trunc_f64_s (local.get 0)))
  (func (export "i32_trunc_f64_u") (param f64) (result i32) (i32.trunc_f64_u (local.get 0)))
  (func (export "i64_trunc_f32_s") (param f32) (result i64) (i64.trunc_f32_s (local.get 0)))
  (func (export "i64_trunc_f64_s") (param f64) (result i64) (i64.trunc_f64_s (local.get 0)))
  (func (export "i64_trunc_f64_u") (param f64) (result i64) (i64.trunc_f64_u (local.get 0)))
  (func (export "i32_sat_f32_s") (param f32) (result i32) (i32.trunc_sat_f32_s (local.get 0)))
  (func (export "i32_sat_f64_u") (param f64) (result i32) (i32.trunc_sat_f64_u (local.get 0)))
  (func (export "i64_sat_f64_s") (param f64) (result i64) (i64.trunc_sat_f64_s (local.get 0)))
  (func (export "i64_sat_f32_u") (param f32) (result i64) (i64.trunc_sat_f32_u (local.get 0)))
  (func (export "f32_conv_i32_s") (param i32) (result f32) (f32.convert_i32_s (local.get 0)))
  (func (export "f32_conv_i32_u") (param i32) (result f32) (f32.convert_i32_u (local.get 0)))
  (func (export "f32_conv_i64_u") (param i64) (result f32) (f32.convert_i64_u (local.get 0)))
  (func (export "f64_conv_i64_s") (param i64) (result f64) (f64.convert_i64_s (local.get 0)))
  (func (export "f64_conv_i64_u") (param i64) (result f64) (f64.convert_i64_u (local.get 0)))
  (func (export "demote") (param f64) (result f32) (f32.demote_f64 (local.get 0)))
  (func (export "promote") (param f32) (result f64) (f64.promote_f32 (local.get 0)))
  (func (export "i32_from_f32_bits") (param i32) (result f32) (f32.reinterpret_i32 (local.get 0)))
  (func (export "i64_from_f64_bits") (param i64) (result f64) (f64.reinterpret_i64 (local.get 0)))
)
;; assert i32_trunc_f32_s f32:2147483520 => i32:2147483520
;; trap i32_trunc_f32_s f32:2147483648 => conv
;; assert i32_trunc_f32_s f32:-2147483648 => i32:-2147483648
;; trap i32_trunc_f32_s f32:-2147483904 => conv
;; trap i32_trunc_f32_s f32:nan => conv
;; trap i32_trunc_f32_s f32:inf => conv
;; assert i32_trunc_f32_s f32:-0.9 => i32:0
;; assert i32_trunc_f32_s f32:1.9 => i32:1
;; assert i32_trunc_f32_u f32:-0.9 => i32:0
;; trap i32_trunc_f32_u f32:-1 => conv
;; assert i32_trunc_f32_u f32:4294967040 => i32:-256
;; trap i32_trunc_f32_u f32:4294967296 => conv
;; assert i32_trunc_f64_s f64:2147483647.9 => i32:2147483647
;; trap i32_trunc_f64_s f64:2147483648 => conv
;; assert i32_trunc_f64_s f64:-2147483648.9 => i32:-2147483648
;; trap i32_trunc_f64_s f64:-2147483649 => conv
;; assert i32_trunc_f64_u f64:4294967295.9 => i32:-1
;; trap i32_trunc_f64_u f64:4294967296 => conv
;; assert i32_trunc_f64_u f64:-0.99 => i32:0
;; assert i64_trunc_f32_s f32:-9223372036854775808 => i64:-9223372036854775808
;; trap i64_trunc_f32_s f32:9223372036854775808 => conv
;; assert i64_trunc_f64_s f64:9223372036854774784 => i64:9223372036854774784
;; trap i64_trunc_f64_s f64:9223372036854775808 => conv
;; assert i64_trunc_f64_u f64:18446744073709549568 => i64:-2048
;; trap i64_trunc_f64_u f64:18446744073709551616 => conv
;; trap i64_trunc_f64_u f64:-1 => conv
;; assert i64_trunc_f64_u f64:-0.5 => i64:0
;; assert i32_sat_f32_s f32:nan => i32:0
;; assert i32_sat_f32_s f32:3e9 => i32:2147483647
;; assert i32_sat_f32_s f32:-3e9 => i32:-2147483648
;; assert i32_sat_f32_s f32:-inf => i32:-2147483648
;; assert i32_sat_f64_u f64:-5 => i32:0
;; assert i32_sat_f64_u f64:1e20 => i32:-1
;; assert i32_sat_f64_u f64:3000000000.5 => i32:-1294967296
;; assert i64_sat_f64_s f64:1e30 => i64:9223372036854775807
;; assert i64_sat_f64_s f64:-1e30 => i64:-9223372036854775808
;; assert i64_sat_f64_s f64:nan => i64:0
;; assert i64_sat_f32_u f32:1e30 => i64:-1
;; assert f32_conv_i32_s i32:16777217 => f32:16777216
;; assert f32_conv_i32_s i32:16777219 => f32:16777220
;; assert f32_conv_i32_s i32:-1 => f32:-1
;; assert f32_conv_i32_u i32:-1 => f32:4294967296
;; assert f32_conv_i64_u i64:-1 => f32:18446744073709551616
;; assert f32_conv_i64_u i64:9223372036854775807 => f32:9223372036854775808
;; assert f64_conv_i64_s i64:9007199254740993 => f64:9007199254740992
;; assert f64_conv_i64_s i64:9007199254740995 => f64:9007199254740996
;; assert f64_conv_i64_u i64:-1 => f64:18446744073709551616
;; assert demote f64:1e300 => f32:inf
;; assert demote f64:-1e300 => f32:-inf
;; assert demote f64:1e-300 => f32:0
;; assert demote f64:-1e-300 => f32:-0
;; assert demote f64:16777217 => f32:16777216
;; assert demote f64:nan => f32:nan
;; assert promote f32:0.1 => f64:0.10000000149011612
;; assert promote f32:-inf => f64:-inf
;; assert promote f32:-0 => f64:-0
;; assert i32_from_f32_bits i32:0x3fc00000 => f32:1.5
;; assert i32_from_f32_bits i32:0x7f800000 => f32:inf
;; assert i64_from_f64_bits i64:0x3ff8000000000000 => f64:1.5
;; assert i64_from_f64_bits i64:0x8000000000000000 => f64:-0
