;; Text-format errors must be reported with a clear message (Wick-only: V8 has no text parser).
(module (func (i32.const 4294967296) (drop)))
;; malformed out-of-range i32 literal
;; ---
(module (func (i32.const -2147483649) (drop)))
;; malformed out-of-range i32 literal
;; ---
(module (func (i64.const 18446744073709551616) (drop)))
;; malformed out-of-range i64 literal
;; ---
(module (func (f32.const 1e39) (drop)))
;; malformed invalid f32 literal
;; ---
(module (func (i32.const 0x) (drop)))
;; malformed invalid or out-of-range i32 literal
;; ---
(module (func (i32.const 1__0) (drop)))
;; malformed invalid or out-of-range i32 literal
;; ---
(module (func (i32.frobnicate)))
;; malformed unknown instruction
;; ---
(module (func (local.get $nope)))
;; malformed unknown local $nope
;; ---
(module (func (call $nope)))
;; malformed unknown function $nope
;; ---
(module (func (br $nope)))
;; malformed unknown label $nope
;; ---
(module (func $a) (func $a))
;; malformed duplicate identifier $a
;; ---
(module (func (param $x i32) (param $x i32)))
;; malformed duplicate local name
;; ---
(module (func (block $l (end $m))))
;; malformed does not match label
;; ---
(module (func (end)))
;; malformed `end` without a matching block
;; ---
(module (func (else)))
;; malformed `else` outside
;; ---
(module (func (block (nop)))
;; malformed unclosed `(`
;; ---
(module (func (nop))))
;; malformed unexpected `)`
;; ---
(module (func (nop) "str"))
;; malformed unexpected string
;; ---
(module (data (i32.const 0) "abc)
;; malformed newline in string literal
;; ---
(module (data (i32.const 0) "\zz"))
;; malformed invalid escape
;; ---
(module (func (param i32) (result i32) (local.get 0) (; unterminated comment ))
;; malformed unterminated block comment
;; ---
(module (frob))
;; malformed unknown module field
;; ---
(module (memory 1) (func (drop (i32.load align=3 (i32.const 0)))))
;; malformed alignment must be a power of two
;; ---
(module (func (param i32 $x)))
;; malformed unknown value type
;; ---
(module (func (if (i32.const 1) (nop))))
;; malformed missing its (then
;; ---
(module (func (type 7)))
;; invalid unknown type
;; ---
(module (type $t (func (param i32))) (func (type $t) (param i64)))
;; malformed inline signature does not match
;; ---
;; Valid, unusual text-format features:
(module
  (func (export "lits") (result i64)
    (i64.add (i64.const 0xFFFF_FFFF_FFFF_FFFF) (i64.add (i64.const 1_000) (i64.const +5))))
  (func (export "flits") (result f64)
    (f64.add (f64.const 0x1.8p3) (f64.add (f64.const 1_0.5e1) (f64.const 0.5e0))))
  (func (export "hexf32") (result f32) (f32.const 0x1p-1))
  (func (export "folded") (result i32)
    (i32.add (i32.mul (i32.const 3) (i32.const 4)) (i32.const 5)))
  (func (export "flat") (result i32)
    i32.const 7
    i32.const 6
    i32.mul)
  (func (export "mixed") (param $a i32) (result i32)
    local.get $a
    (i32.const 2)
    i32.shl)
  (func (export "named_labels") (result i32)
    block $b (result i32)
      i32.const 41
      br $b
    end $b
    i32.const 1
    i32.add)
  (func (export "str_escape") (result i32) (i32.load8_u (i32.const 0)))
  (memory 1)
  (data (i32.const 0) "\41\n\t\\\"\u{263a}")
  (func (export "at") (param i32) (result i32) (i32.load8_u (local.get 0)))
  (; nested (; block ;) comment ;)
  (func (export "inline_exp") (export "second_name") (result i32) (i32.const 3)))
;; assert lits => i64:1004
;; assert flits => f64:117.5
;; assert hexf32 => f32:0.5
;; assert folded => i32:17
;; assert flat => i32:42
;; assert mixed i32:5 => i32:20
;; assert named_labels => i32:42
;; assert str_escape => i32:65
;; assert at i32:1 => i32:10
;; assert at i32:2 => i32:9
;; assert at i32:3 => i32:92
;; assert at i32:4 => i32:34
;; assert at i32:5 => i32:226
;; assert inline_exp => i32:3
;; assert second_name => i32:3
