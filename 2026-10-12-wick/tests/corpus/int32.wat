;; i32 arithmetic, bit ops, comparisons — wraparound and trap edge cases.
(module
  (func (export "add") (param i32 i32) (result i32) (i32.add (local.get 0) (local.get 1)))
  (func (export "sub") (param i32 i32) (result i32) (i32.sub (local.get 0) (local.get 1)))
  (func (export "mul") (param i32 i32) (result i32) (i32.mul (local.get 0) (local.get 1)))
  (func (export "div_s") (param i32 i32) (result i32) (i32.div_s (local.get 0) (local.get 1)))
  (func (export "div_u") (param i32 i32) (result i32) (i32.div_u (local.get 0) (local.get 1)))
  (func (export "rem_s") (param i32 i32) (result i32) (i32.rem_s (local.get 0) (local.get 1)))
  (func (export "rem_u") (param i32 i32) (result i32) (i32.rem_u (local.get 0) (local.get 1)))
  (func (export "shl") (param i32 i32) (result i32) (i32.shl (local.get 0) (local.get 1)))
  (func (export "shr_s") (param i32 i32) (result i32) (i32.shr_s (local.get 0) (local.get 1)))
  (func (export "shr_u") (param i32 i32) (result i32) (i32.shr_u (local.get 0) (local.get 1)))
  (func (export "rotl") (param i32 i32) (result i32) (i32.rotl (local.get 0) (local.get 1)))
  (func (export "rotr") (param i32 i32) (result i32) (i32.rotr (local.get 0) (local.get 1)))
  (func (export "clz") (param i32) (result i32) (i32.clz (local.get 0)))
  (func (export "ctz") (param i32) (result i32) (i32.ctz (local.get 0)))
  (func (export "popcnt") (param i32) (result i32) (i32.popcnt (local.get 0)))
  (func (export "eqz") (param i32) (result i32) (i32.eqz (local.get 0)))
  (func (export "lt_s") (param i32 i32) (result i32) (i32.lt_s (local.get 0) (local.get 1)))
  (func (export "lt_u") (param i32 i32) (result i32) (i32.lt_u (local.get 0) (local.get 1)))
  (func (export "ge_s") (param i32 i32) (result i32) (i32.ge_s (local.get 0) (local.get 1)))
  (func (export "ge_u") (param i32 i32) (result i32) (i32.ge_u (local.get 0) (local.get 1)))
  (func (export "ext8") (param i32) (result i32) (i32.extend8_s (local.get 0)))
  (func (export "ext16") (param i32) (result i32) (i32.extend16_s (local.get 0)))
)
;; assert add i32:2147483647 i32:1 => i32:-2147483648
;; assert add i32:-1 i32:-1 => i32:-2
;; assert sub i32:0 i32:1 => i32:-1
;; assert sub i32:-2147483648 i32:1 => i32:2147483647
;; assert mul i32:65536 i32:65536 => i32:0
;; assert mul i32:-2147483648 i32:-1 => i32:-2147483648
;; assert mul i32:123456789 i32:987654321 => i32:-67153019
;; assert div_s i32:-7 i32:2 => i32:-3
;; assert div_s i32:7 i32:-2 => i32:-3
;; trap div_s i32:1 i32:0 => div_zero
;; trap div_s i32:-2147483648 i32:-1 => int_overflow_or_conv
;; assert div_u i32:-1 i32:2 => i32:2147483647
;; trap div_u i32:5 i32:0 => div_zero
;; assert rem_s i32:-7 i32:2 => i32:-1
;; assert rem_s i32:7 i32:-2 => i32:1
;; assert rem_s i32:-2147483648 i32:-1 => i32:0
;; trap rem_s i32:5 i32:0 => div_zero
;; assert rem_u i32:-1 i32:10 => i32:5
;; trap rem_u i32:0 i32:0 => div_zero
;; assert shl i32:1 i32:31 => i32:-2147483648
;; assert shl i32:1 i32:32 => i32:1
;; assert shl i32:1 i32:33 => i32:2
;; assert shl i32:1 i32:-1 => i32:-2147483648
;; assert shr_s i32:-8 i32:1 => i32:-4
;; assert shr_s i32:-2147483648 i32:31 => i32:-1
;; assert shr_u i32:-8 i32:1 => i32:2147483644
;; assert shr_u i32:-1 i32:32 => i32:-1
;; assert rotl i32:-2147483647 i32:1 => i32:3
;; assert rotl i32:1 i32:32 => i32:1
;; assert rotr i32:1 i32:1 => i32:-2147483648
;; assert rotr i32:3 i32:33 => i32:-2147483647
;; assert clz i32:0 => i32:32
;; assert clz i32:1 => i32:31
;; assert clz i32:-1 => i32:0
;; assert ctz i32:0 => i32:32
;; assert ctz i32:-2147483648 => i32:31
;; assert popcnt i32:-1 => i32:32
;; assert popcnt i32:0x55555555 => i32:16
;; assert eqz i32:0 => i32:1
;; assert eqz i32:-1 => i32:0
;; assert lt_s i32:-1 i32:1 => i32:1
;; assert lt_u i32:-1 i32:1 => i32:0
;; assert ge_s i32:-2147483648 i32:2147483647 => i32:0
;; assert ge_u i32:-2147483648 i32:2147483647 => i32:1
;; assert ext8 i32:0x80 => i32:-128
;; assert ext8 i32:0x17f => i32:127
;; assert ext16 i32:0x8000 => i32:-32768
;; assert ext16 i32:0x12345 => i32:9029
