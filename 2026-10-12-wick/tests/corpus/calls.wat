;; Direct, recursive, mutually recursive and indirect calls; table traps.
(module
  (type $binop (func (param i32 i32) (result i32)))
  (type $unop (func (param i32) (result i32)))
  (type $nullary (func (result i32)))
  (table 8 funcref)
  (elem (i32.const 0) $add $sub $neg)
  (elem (i32.const 5) $even)
  (func $add (type $binop) (i32.add (local.get 0) (local.get 1)))
  (func $sub (type $binop) (i32.sub (local.get 0) (local.get 1)))
  (func $neg (type $unop) (i32.sub (i32.const 0) (local.get 0)))
  (func $even (type $unop)
    (if (result i32) (i32.eqz (local.get 0)) (then (i32.const 1))
      (else (call $odd (i32.sub (local.get 0) (i32.const 1))))))
  (func $odd (type $unop)
    (if (result i32) (i32.eqz (local.get 0)) (then (i32.const 0))
      (else (call $even (i32.sub (local.get 0) (i32.const 1))))))
  (func (export "apply2") (param i32 i32 i32) (result i32)
    (call_indirect (type $binop) (local.get 1) (local.get 2) (local.get 0)))
  (func (export "apply1") (param i32 i32) (result i32)
    (call_indirect (type $unop) (local.get 1) (local.get 0)))
  (func (export "wrong_type") (param i32) (result i32)
    (call_indirect (type $nullary) (local.get 0)))
  (func (export "is_even") (param i32) (result i32) (call $even (local.get 0)))
  (func $fac (export "fac") (param i64) (result i64)
    (if (result i64) (i64.eqz (local.get 0)) (then (i64.const 1))
      (else (i64.mul (local.get 0) (call $fac (i64.sub (local.get 0) (i64.const 1)))))))
  (func $forever (export "forever") (result i32) (call $forever))
)
;; assert apply2 i32:0 i32:5 i32:3 => i32:8
;; assert apply2 i32:1 i32:5 i32:3 => i32:2
;; trap apply2 i32:2 i32:5 i32:3 => indirect
;; trap apply2 i32:3 i32:5 i32:3 => indirect
;; trap apply2 i32:4 i32:5 i32:3 => indirect
;; trap apply2 i32:8 i32:5 i32:3 => table_oob
;; trap apply2 i32:-1 i32:5 i32:3 => table_oob
;; assert apply1 i32:2 i32:9 => i32:-9
;; assert apply1 i32:5 i32:10 => i32:1
;; assert apply1 i32:5 i32:7 => i32:0
;; trap apply1 i32:0 i32:9 => indirect
;; trap wrong_type i32:0 => indirect
;; trap wrong_type i32:2 => indirect
;; assert is_even i32:100 => i32:1
;; assert is_even i32:7 => i32:0
;; assert fac i64:20 => i64:2432902008176640000
;; assert fac i64:21 => i64:-4249290049419214848
;; trap forever => stack
