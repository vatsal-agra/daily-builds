;; Structured control flow: branches carrying values, loops, br_table, block/loop parameters, multi-value.
(module
  (type $pair (func (param i32 i32) (result i32 i32)))
  (type $inc (func (param i32) (result i32)))
  (func (export "block_val") (param i32) (result i32)
    (block (result i32)
      (br_if 0 (i32.const 100) (local.get 0))
      (drop)
      (i32.const 200)))
  (func (export "loop_sum") (param $n i32) (result i32)
    (local $acc i32)
    (block $out
      (loop $top
        (br_if $out (i32.eqz (local.get $n)))
        (local.set $acc (i32.add (local.get $acc) (local.get $n)))
        (local.set $n (i32.sub (local.get $n) (i32.const 1)))
        (br $top)))
    (local.get $acc))
  (func (export "switch") (param i32) (result i32)
    (block $d (block $c (block $b (block $a
      (br_table $a $b $c $d (local.get 0)))
      (return (i32.const 10)))
      (return (i32.const 20)))
      (return (i32.const 30)))
    (i32.const 99))
  (func (export "br_table_default") (param i32) (result i32)
    (block (result i32)
      (block (result i32)
        (i32.const 7)
        (local.get 0)
        (br_table 0 1 0)))
    )
  (func (export "if_else") (param i32) (result i32)
    (if (result i32) (local.get 0)
      (then (i32.const 1))
      (else (i32.const 2))))
  (func (export "if_no_else") (param i32) (result i32)
    (local $r i32)
    (local.set $r (i32.const 5))
    (if (local.get 0) (then (local.set $r (i32.const 6))))
    (local.get $r))
  (func (export "nested_br") (param i32) (result i32)
    (block $outer (result i32)
      (block $inner (result i32)
        (br_if $outer (i32.const 11) (i32.eq (local.get 0) (i32.const 1)))
        (drop)
        (br_if $inner (i32.const 22) (i32.eq (local.get 0) (i32.const 2)))
        (drop)
        (i32.const 33))
      (i32.add (i32.const 1000))))
  (func (export "early_return") (param i32) (result i32)
    (if (local.get 0) (then (return (i32.const 1))))
    (i32.const 2))
  (func (export "block_params") (param i32 i32) (result i32)
    (local.get 0) (local.get 1)
    (block (type $pair) (i32.add) (i32.const 1))
    (i32.add))
  (func $swap (type $pair) (local.get 1) (local.get 0))
  (func (export "multi") (param i32 i32) (result i32)
    (call $swap (local.get 0) (local.get 1))
    (i32.sub))
  (func (export "multi_block") (result i32 i32)
    (block (result i32 i32) (i32.const 3) (i32.const 4)))
  (func (export "select_t") (param i32) (result i64)
    (select (result i64) (i64.const 1) (i64.const 2) (local.get 0)))
  (func (export "unreachable_poly") (result i32)
    (unreachable) (i32.add))
  (func (export "dead_code_after_br") (result i32)
    (block (result i32) (br 0 (i32.const 5)) (i64.const 1) (i64.eqz)))
  (func (export "trap") (unreachable))
)
;; assert block_val i32:1 => i32:100
;; assert block_val i32:0 => i32:200
;; assert loop_sum i32:10 => i32:55
;; assert loop_sum i32:0 => i32:0
;; assert switch i32:0 => i32:10
;; assert switch i32:1 => i32:20
;; assert switch i32:2 => i32:30
;; assert switch i32:3 => i32:99
;; assert switch i32:100 => i32:99
;; assert switch i32:-1 => i32:99
;; assert br_table_default i32:0 => i32:7
;; assert br_table_default i32:1 => i32:7
;; assert br_table_default i32:5 => i32:7
;; assert if_else i32:5 => i32:1
;; assert if_else i32:0 => i32:2
;; assert if_no_else i32:1 => i32:6
;; assert if_no_else i32:0 => i32:5
;; assert nested_br i32:1 => i32:11
;; assert nested_br i32:2 => i32:1022
;; assert nested_br i32:3 => i32:1033
;; assert early_return i32:1 => i32:1
;; assert early_return i32:0 => i32:2
;; assert block_params i32:3 i32:4 => i32:8
;; assert multi i32:10 i32:3 => i32:-7
;; assert multi_block => i32:3 i32:4
;; assert select_t i32:1 => i64:1
;; assert select_t i32:0 => i64:2
;; trap unreachable_poly => unreachable
;; assert dead_code_after_br => i32:5
;; trap trap => unreachable
;; ---
;; Loop with parameters on the operand stack.
(module
  (func (export "count") (param i32) (result i32)
    (local i32)
    (local.get 0)
    (loop $again (param i32) (result i32)
      (local.tee 1)
      (i32.const 1) (i32.sub)
      (local.tee 1)
      (br_if $again (local.get 1)))
    (drop)
    (local.get 1)))
;; assert count i32:5 => i32:0
;; assert count i32:1 => i32:0
