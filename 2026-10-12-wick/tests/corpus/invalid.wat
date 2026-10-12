;; Modules that must be rejected by validation (V8 must reject them too), plus tricky valid ones.
(module (func (result i32) (i32.add (i32.const 1) (i64.const 2))))
;; invalid expected i32, found i64
;; ---
(module (func (result i32)))
;; invalid operand stack underflow
;; ---
(module (func (i32.const 1)))
;; invalid extra value
;; ---
(module (func (result i32) (i32.const 1) (i32.const 2)))
;; invalid extra value
;; ---
(module (func (param i32) (local.get 1) (drop)))
;; invalid unknown local
;; ---
(module (func (call 5)))
;; invalid unknown function
;; ---
(module (func (global.get 0) (drop)))
;; invalid unknown global
;; ---
(module (func (br 1)))
;; invalid unknown label
;; ---
(module (func (result i32) (block (result i32) (br 0))))
;; invalid operand stack underflow
;; ---
(module (func (result i32) (if (result i32) (i32.const 1) (then (i32.const 1)))))
;; invalid without `else`
;; ---
(module (func (result i32) (if (result i32) (i32.const 1) (then (i32.const 1)) (else (i64.const 1)))))
;; invalid expected i32, found i64
;; ---
(module (func (result i32) (select (i32.const 1) (i64.const 2) (i32.const 0))))
;; invalid select operands
;; ---
(module (global $g i32 (i32.const 0)) (func (global.set $g (i32.const 1))))
;; invalid immutable global
;; ---
(module (func (drop (i32.load (i32.const 0)))))
;; invalid no memory
;; ---
(module (memory 1) (func (drop (i32.load align=8 (i32.const 0)))))
;; invalid alignment
;; ---
(module (type $t (func)) (func (call_indirect (type $t) (i32.const 0))))
;; invalid unknown table
;; ---
(module (func (export "a")) (func (export "a")))
;; invalid duplicate export
;; ---
(module (func $s (param i32)) (start $s))
;; invalid start function
;; ---
(module (global i32 (nop)))
;; invalid constant expression
;; ---
(module (global i32 (i64.const 1)))
;; invalid constant expression has type
;; ---
(module (memory 1) (data (i64.const 0) "x"))
;; invalid constant expression has type
;; ---
(module (memory 2 1))
;; invalid maximum
;; ---
(module (memory 65537))
;; invalid exceeds
;; ---
(module (func (unreachable) (i64.const 0) (i32.eqz)))
;; invalid expected i32, found i64
;; ---
(module (func (result i32) (i64.const 0) (return)))
;; invalid expected i32, found i64
;; ---
(module (func (block (br_table 0 2 (i32.const 0)))))
;; invalid unknown label
;; ---
(module (func (block (result i32) (block (result i64) (br_table 0 1 (i32.const 1) (i32.const 0))))))
;; invalid type mismatch
;; ---
(module (func (loop (result i32))))
;; invalid operand stack underflow
;; ---
(module (func (local.set 0 (i32.const 0))))
;; invalid unknown local
;; ---
(module (func (result f32) (f32.demote_f32 (f32.const 0))))
;; malformed unknown instruction
;; ---
(module (func (i32.const 1) (i32.const 2) (select (result f64)) (drop)))
;; invalid expected f64, found i32
;; ---
(module (func (export "e")) (export "e" (func 0)))
;; invalid duplicate export
;; ---
(module (func (param i32) (result i32) (local.get 0) (i64.extend_i32_s) (i32.wrap_i64) (i64.const 0) (drop) (drop)))
;; invalid operand stack underflow
;; ---
;; These are VALID despite looking odd (stack-polymorphism after unreachable/br/return):
(module
  (func (export "a") (result i32) (unreachable))
  (func (export "b") (result i32) (return (i32.const 1)) (i32.add))
  (func (export "c") (result i32) (block (result i32) (br 0 (i32.const 4)) (drop) (drop) (i32.const 9)))
  (func (export "d") (result i32) (unreachable) (i64.const 3) (i64.eqz) (select))
  (func (export "e") (param i32) (result i32) (block (br_table 0 0 (local.get 0))) (i32.const 8)))
;; assert b => i32:1
;; assert c => i32:4
;; trap a => unreachable
;; assert e i32:0 => i32:8
;; assert e i32:77 => i32:8
