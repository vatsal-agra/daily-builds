;; Linear memory: loads/stores of every width, sign extension, bounds, growth, bulk operations, data segments.
(module
  (memory (export "mem") 1 3)
  (data (i32.const 0) "\01\02\03\04\ff\fe\fd\fc")
  (data (i32.const 65532) "\aa\bb\cc\dd")
  (func (export "i32_load") (param i32) (result i32) (i32.load (local.get 0)))
  (func (export "i32_load_off") (param i32) (result i32) (i32.load offset=4 (local.get 0)))
  (func (export "i32_load8_s") (param i32) (result i32) (i32.load8_s (local.get 0)))
  (func (export "i32_load8_u") (param i32) (result i32) (i32.load8_u (local.get 0)))
  (func (export "i32_load16_s") (param i32) (result i32) (i32.load16_s (local.get 0)))
  (func (export "i32_load16_u") (param i32) (result i32) (i32.load16_u (local.get 0)))
  (func (export "i64_load") (param i32) (result i64) (i64.load (local.get 0)))
  (func (export "i64_load8_s") (param i32) (result i64) (i64.load8_s (local.get 0)))
  (func (export "i64_load16_u") (param i32) (result i64) (i64.load16_u (local.get 0)))
  (func (export "i64_load32_s") (param i32) (result i64) (i64.load32_s (local.get 0)))
  (func (export "i64_load32_u") (param i32) (result i64) (i64.load32_u (local.get 0)))
  (func (export "f32_load") (param i32) (result f32) (f32.load (local.get 0)))
  (func (export "f64_load") (param i32) (result f64) (f64.load (local.get 0)))
  (func (export "i32_store") (param i32 i32) (i32.store (local.get 0) (local.get 1)))
  (func (export "i32_store8") (param i32 i32) (i32.store8 (local.get 0) (local.get 1)))
  (func (export "i32_store16") (param i32 i32) (i32.store16 (local.get 0) (local.get 1)))
  (func (export "i64_store") (param i32 i64) (i64.store (local.get 0) (local.get 1)))
  (func (export "i64_store32") (param i32 i64) (i64.store32 (local.get 0) (local.get 1)))
  (func (export "f64_store") (param i32 f64) (f64.store (local.get 0) (local.get 1)))
  (func (export "size") (result i32) (memory.size))
  (func (export "grow") (param i32) (result i32) (memory.grow (local.get 0)))
  (func (export "fill") (param i32 i32 i32) (memory.fill (local.get 0) (local.get 1) (local.get 2)))
  (func (export "copy") (param i32 i32 i32) (memory.copy (local.get 0) (local.get 1) (local.get 2)))
  (func (export "unaligned") (param i32) (result i32) (i32.load align=1 (local.get 0)))
)
;; assert i32_load i32:0 => i32:67305985
;; assert i32_load i32:1 => i32:-16514302
;; assert i32_load_off i32:0 => i32:-50462977
;; assert i32_load8_s i32:4 => i32:-1
;; assert i32_load8_u i32:4 => i32:255
;; assert i32_load16_s i32:4 => i32:-257
;; assert i32_load16_u i32:4 => i32:65279
;; assert i64_load i32:0 => i64:-216736835806494207
;; assert i64_load8_s i32:5 => i64:-2
;; assert i64_load16_u i32:6 => i64:64765
;; assert i64_load32_s i32:4 => i64:-50462977
;; assert i64_load32_u i32:4 => i64:4244504319
;; assert i32_load i32:65532 => i32:-573785174
;; trap i32_load i32:65533 => memory_oob
;; trap i32_load i32:65536 => memory_oob
;; trap i32_load i32:-1 => memory_oob
;; assert i32_load_off i32:65528 => i32:-573785174
;; trap i32_load_off i32:65529 => memory_oob
;; assert i32_load8_u i32:65535 => i32:221
;; trap i32_load8_u i32:65536 => memory_oob
;; trap i64_load i32:65529 => memory_oob
;; assert i64_load i32:65528 => i64:-2464388557259669504
;; assert unaligned i32:1 => i32:-16514302
;; assert i32_store i32:100 i32:-1
;; assert i32_load i32:100 => i32:-1
;; assert i32_store8 i32:100 i32:0x1234
;; assert i32_load i32:100 => i32:-204
;; assert i32_store16 i32:200 i32:0x12345678
;; assert i32_load i32:200 => i32:22136
;; assert i64_store i32:300 i64:0x0102030405060708
;; assert i32_load i32:300 => i32:84281096
;; assert i32_load i32:304 => i32:16909060
;; assert i64_store32 i32:400 i64:0x1ffffffff
;; assert i64_load i32:400 => i64:4294967295
;; assert f64_store i32:500 f64:-2.5
;; assert f64_load i32:500 => f64:-2.5
;; assert f32_load i32:504 => f32:-2.0625
;; trap i32_store i32:65533 i32:1 => memory_oob
;; assert i32_load8_u i32:65533 => i32:187
;; assert size => i32:1
;; assert grow i32:1 => i32:1
;; assert size => i32:2
;; assert i32_load i32:65536 => i32:0
;; assert grow i32:5 => i32:-1
;; assert size => i32:2
;; assert grow i32:0 => i32:2
;; assert grow i32:1 => i32:2
;; assert grow i32:1 => i32:-1
;; assert size => i32:3
;; assert fill i32:1000 i32:0xab i32:4
;; assert i32_load i32:1000 => i32:-1414812757
;; assert fill i32:196608 i32:0 i32:0
;; trap fill i32:196609 i32:0 i32:0 => memory_oob
;; trap fill i32:196600 i32:1 i32:9 => memory_oob
;; assert i32_store8 i32:2000 i32:1
;; assert i32_store8 i32:2001 i32:2
;; assert i32_store8 i32:2002 i32:3
;; assert copy i32:2001 i32:2000 i32:3
;; assert i32_load i32:2000 => i32:50462977
;; assert copy i32:2000 i32:2001 i32:3
;; assert i32_load i32:2000 => i32:50528769
;; trap copy i32:196600 i32:0 i32:9 => memory_oob
;; trap copy i32:0 i32:196600 i32:9 => memory_oob
;; assert copy i32:196608 i32:196608 i32:0
