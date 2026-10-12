;; Instantiation-time failures.
(module (memory 1) (data (i32.const 65535) "ab"))
;; init-trap memory_oob
;; ---
(module (table 2 funcref) (func $f) (elem (i32.const 1) $f $f))
;; init-trap table_oob
;; ---
(module (func $t unreachable) (start $t))
;; init-trap unreachable
;; ---
(module (import "nope" "missing" (func)))
;; link-error missing function import
;; ---
(module (memory 65536))
;; link-error exceeds
;; ---
(module (memory 1) (data (i32.const 0) "hello") (data (i32.const 3) "LO") (func (export "b") (param i32) (result i32) (i32.load8_u (local.get 0))))
;; assert b i32:0 => i32:104
;; assert b i32:3 => i32:76
;; assert b i32:4 => i32:79
