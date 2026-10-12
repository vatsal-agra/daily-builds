;; f32/f64 semantics: signed zeros, NaN propagation, rounding modes, min/max.
(module
  (func (export "f32_min") (param f32 f32) (result f32) (f32.min (local.get 0) (local.get 1)))
  (func (export "f32_max") (param f32 f32) (result f32) (f32.max (local.get 0) (local.get 1)))
  (func (export "f64_min") (param f64 f64) (result f64) (f64.min (local.get 0) (local.get 1)))
  (func (export "f64_max") (param f64 f64) (result f64) (f64.max (local.get 0) (local.get 1)))
  (func (export "f32_nearest") (param f32) (result f32) (f32.nearest (local.get 0)))
  (func (export "f64_nearest") (param f64) (result f64) (f64.nearest (local.get 0)))
  (func (export "f64_ceil") (param f64) (result f64) (f64.ceil (local.get 0)))
  (func (export "f64_floor") (param f64) (result f64) (f64.floor (local.get 0)))
  (func (export "f64_trunc") (param f64) (result f64) (f64.trunc (local.get 0)))
  (func (export "f64_sqrt") (param f64) (result f64) (f64.sqrt (local.get 0)))
  (func (export "f64_copysign") (param f64 f64) (result f64) (f64.copysign (local.get 0) (local.get 1)))
  (func (export "f64_abs") (param f64) (result f64) (f64.abs (local.get 0)))
  (func (export "f64_neg") (param f64) (result f64) (f64.neg (local.get 0)))
  (func (export "f32_add") (param f32 f32) (result f32) (f32.add (local.get 0) (local.get 1)))
  (func (export "f32_div") (param f32 f32) (result f32) (f32.div (local.get 0) (local.get 1)))
  (func (export "f64_div") (param f64 f64) (result f64) (f64.div (local.get 0) (local.get 1)))
  (func (export "f64_eq") (param f64 f64) (result i32) (f64.eq (local.get 0) (local.get 1)))
  (func (export "f64_ne") (param f64 f64) (result i32) (f64.ne (local.get 0) (local.get 1)))
  (func (export "f64_lt") (param f64 f64) (result i32) (f64.lt (local.get 0) (local.get 1)))
  (func (export "f64_ge") (param f64 f64) (result i32) (f64.ge (local.get 0) (local.get 1)))
  (func (export "f32_bits") (param f32) (result i32) (i32.reinterpret_f32 (local.get 0)))
  (func (export "f64_bits") (param f64) (result i64) (i64.reinterpret_f64 (local.get 0)))
)
;; assert f32_min f32:0 f32:-0 => f32:-0
;; assert f32_min f32:-0 f32:0 => f32:-0
;; assert f32_max f32:-0 f32:0 => f32:0
;; assert f32_min f32:nan f32:1 => f32:nan
;; assert f32_max f32:1 f32:nan => f32:nan
;; assert f64_min f64:-inf f64:nan => f64:nan
;; assert f64_min f64:1 f64:2 => f64:1
;; assert f64_max f64:-1 f64:-2 => f64:-1
;; assert f32_nearest f32:0.5 => f32:0
;; assert f32_nearest f32:1.5 => f32:2
;; assert f32_nearest f32:2.5 => f32:2
;; assert f32_nearest f32:-0.5 => f32:-0
;; assert f32_nearest f32:-2.5 => f32:-2
;; assert f32_nearest f32:8388609 => f32:8388609
;; assert f64_nearest f64:-1.5 => f64:-2
;; assert f64_nearest f64:3.5 => f64:4
;; assert f64_nearest f64:4503599627370497.5 => f64:4503599627370498
;; assert f64_nearest f64:inf => f64:inf
;; assert f64_ceil f64:-0.5 => f64:-0
;; assert f64_ceil f64:0.1 => f64:1
;; assert f64_floor f64:-0.5 => f64:-1
;; assert f64_floor f64:-0 => f64:-0
;; assert f64_trunc f64:-0.9 => f64:-0
;; assert f64_trunc f64:2.9 => f64:2
;; assert f64_sqrt f64:4 => f64:2
;; assert f64_sqrt f64:-0 => f64:-0
;; assert f64_sqrt f64:-1 => f64:nan
;; assert f64_copysign f64:1 f64:-0 => f64:-1
;; assert f64_copysign f64:-3 f64:2 => f64:3
;; assert f64_abs f64:-0 => f64:0
;; assert f64_neg f64:0 => f64:-0
;; assert f64_neg f64:-inf => f64:inf
;; assert f32_add f32:16777216 f32:1 => f32:16777216
;; assert f32_add f32:inf f32:-inf => f32:nan
;; assert f32_div f32:1 f32:0 => f32:inf
;; assert f32_div f32:-1 f32:0 => f32:-inf
;; assert f32_div f32:0 f32:0 => f32:nan
;; assert f64_div f64:1 f64:-0 => f64:-inf
;; assert f64_eq f64:nan f64:nan => i32:0
;; assert f64_ne f64:nan f64:nan => i32:1
;; assert f64_eq f64:0 f64:-0 => i32:1
;; assert f64_lt f64:nan f64:1 => i32:0
;; assert f64_ge f64:nan f64:1 => i32:0
;; assert f64_lt f64:-inf f64:inf => i32:1
;; assert f32_bits f32:-0 => i32:-2147483648
;; assert f32_bits f32:1 => i32:1065353216
;; assert f32_bits f32:bits:0x7fc00001 => i32:2143289345
;; assert f64_bits f64:-0 => i64:-9223372036854775808
;; assert f64_bits f64:1 => i64:4607182418800017408
