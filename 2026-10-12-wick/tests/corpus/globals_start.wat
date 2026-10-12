;; Globals (mutable/immutable, init from imported global) and start function ordering.
(module
  (import "env" "print_i32" (func $print (param i32)))
  (global $counter (mut i32) (i32.const 10))
  (global $k i64 (i64.const -7))
  (global (export "pi") f64 (f64.const 3.25))
  (global (export "g") (mut f32) (f32.const 1.5))
  (func $init
    (global.set $counter (i32.add (global.get $counter) (i32.const 5)))
    (call $print (global.get $counter)))
  (start $init)
  (func (export "bump") (result i32)
    (global.set $counter (i32.add (global.get $counter) (i32.const 1)))
    (global.get $counter))
  (func (export "k") (result i64) (global.get $k))
  (func (export "setg") (param f32) (global.set 3 (local.get 0)))
)
;; assert bump => i32:16
;; assert bump => i32:17
;; assert k => i64:-7
;; global pi => f64:3.25
;; global g => f32:1.5
;; assert setg f32:-0 
;; global g => f32:-0
