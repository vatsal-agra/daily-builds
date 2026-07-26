import unittest

from .helpers import run_kwat, instantiate, assemble_bytes
from kiln.wasm.interpreter import WasmTrap


class TestControlFlow(unittest.TestCase):
    def test_recursive_fib(self):
        src = """
        (module
          (func $fib (param i32) (result i32)
            local.get 0
            i32.const 2
            i32.lt_s
            if (result i32)
              local.get 0
            else
              local.get 0
              i32.const 1
              i32.sub
              call $fib
              local.get 0
              i32.const 2
              i32.sub
              call $fib
              i32.add
            end)
          (export "fib" (func $fib)))
        """
        expected = [0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55]
        for i, want in enumerate(expected):
            self.assertEqual(run_kwat(src, "fib", [i]), [want])

    def test_loop_with_nested_break(self):
        # Sums 0..n-1, but breaks out of BOTH loops (br 2) once the
        # running total exceeds 10 -- exercises multi-level br.
        src = """
        (module
          (func $f (param i32) (result i32)
            (local i32 i32)
            block
              loop
                local.get 1
                local.get 0
                i32.ge_s
                br_if 1
                local.get 2
                i32.const 10
                i32.gt_s
                if
                  br 2
                end
                local.get 2
                local.get 1
                i32.add
                local.set 2
                local.get 1
                i32.const 1
                i32.add
                local.set 1
                br 0
              end
            end
            local.get 2)
          (export "f" (func $f)))
        """
        self.assertEqual(run_kwat(src, "f", [3]), [3])  # 0+1+2, never exceeds 10
        self.assertEqual(run_kwat(src, "f", [100]), [15])  # 0+1+2+3+4+5=15 > 10, breaks

    def test_br_table(self):
        src = """
        (module
          (func $f (param i32) (result i32)
            block
              block
                block
                  local.get 0
                  br_table (0 1 2 2)
                end
                i32.const 100
                return
              end
              i32.const 200
              return
            end
            i32.const 300
            return)
          (export "f" (func $f)))
        """
        self.assertEqual(run_kwat(src, "f", [0]), [100])
        self.assertEqual(run_kwat(src, "f", [1]), [200])
        self.assertEqual(run_kwat(src, "f", [2]), [300])
        self.assertEqual(run_kwat(src, "f", [99]), [300])  # out of range -> default


class TestMemory(unittest.TestCase):
    SRC = """
    (module
      (memory 1)
      (func $store8 (param i32 i32)
        local.get 0
        local.get 1
        i32.store8)
      (func $load8_u (param i32) (result i32)
        local.get 0
        i32.load8_u)
      (func $load8_s (param i32) (result i32)
        local.get 0
        i32.load8_s)
      (func $grow (param i32) (result i32)
        local.get 0
        memory.grow)
      (func $size (result i32)
        memory.size)
      (export "store8" (func $store8))
      (export "load8_u" (func $load8_u))
      (export "load8_s" (func $load8_s))
      (export "grow" (func $grow))
      (export "size" (func $size)))
    """

    def test_store_load_roundtrip(self):
        inst = instantiate(assemble_bytes(self.SRC))
        inst.call("store8", [0, 0xFF])
        self.assertEqual(inst.call("load8_u", [0]), [255])
        self.assertEqual(inst.call("load8_s", [0]), [4294967295])  # -1 as u32 bit pattern

    def test_out_of_bounds_traps(self):
        inst = instantiate(assemble_bytes(self.SRC))
        with self.assertRaises(WasmTrap):
            inst.call("load8_u", [70000])

    def test_memory_grow(self):
        inst = instantiate(assemble_bytes(self.SRC))
        self.assertEqual(inst.call("size", []), [1])
        self.assertEqual(inst.call("grow", [2]), [1])  # returns previous size
        self.assertEqual(inst.call("size", []), [3])


class TestNumerics(unittest.TestCase):
    def _binop(self, op, a, b):
        src = f"""
        (module
          (func $f (param i32 i32) (result i32)
            local.get 0
            local.get 1
            {op})
          (export "f" (func $f)))
        """
        return run_kwat(src, "f", [a & 0xFFFFFFFF, b & 0xFFFFFFFF])[0]

    def test_div_by_zero_traps(self):
        with self.assertRaises(WasmTrap):
            self._binop("i32.div_s", 1, 0)
        with self.assertRaises(WasmTrap):
            self._binop("i32.div_u", 1, 0)
        with self.assertRaises(WasmTrap):
            self._binop("i32.rem_s", 1, 0)

    def test_signed_division_overflow_traps(self):
        with self.assertRaises(WasmTrap):
            self._binop("i32.div_s", -2**31, -1)

    def test_wraparound_add(self):
        self.assertEqual(self._binop("i32.add", 0xFFFFFFFF, 1), 0)

    def test_signed_vs_unsigned_comparison(self):
        # 0xFFFFFFFF is -1 signed, but the max u32 value unsigned.
        self.assertEqual(self._binop("i32.lt_s", -1, 1), 1)
        self.assertEqual(self._binop("i32.lt_u", -1, 1), 0)

    def test_unreachable_traps(self):
        src = """
        (module
          (func $f
            unreachable)
          (export "f" (func $f)))
        """
        with self.assertRaises(WasmTrap):
            run_kwat(src, "f", [])

    def test_shift_and_rotate(self):
        self.assertEqual(self._binop("i32.shl", 1, 31), 0x80000000)
        self.assertEqual(self._binop("i32.rotl", 0x80000000, 1), 1)
        self.assertEqual(self._binop("i32.rotr", 1, 1), 0x80000000)


class TestFunctionTable(unittest.TestCase):
    def test_call_indirect(self):
        src = """
        (module
          (type $binop (func (param i32 i32) (result i32)))
          (table 2 funcref)
          (func $add (param i32 i32) (result i32)
            local.get 0
            local.get 1
            i32.add)
          (func $mul (param i32 i32) (result i32)
            local.get 0
            local.get 1
            i32.mul)
          (elem (i32.const 0) $add $mul)
          (func $dispatch (param i32 i32 i32) (result i32)
            local.get 0
            local.get 1
            local.get 2
            call_indirect (type $binop))
          (export "dispatch" (func $dispatch)))
        """
        self.assertEqual(run_kwat(src, "dispatch", [3, 4, 0]), [7])
        self.assertEqual(run_kwat(src, "dispatch", [3, 4, 1]), [12])

    def test_call_indirect_out_of_bounds_traps(self):
        src = """
        (module
          (type $binop (func (param i32 i32) (result i32)))
          (table 1 funcref)
          (func $add (param i32 i32) (result i32)
            local.get 0 local.get 1 i32.add)
          (elem (i32.const 0) $add)
          (func $dispatch (param i32 i32 i32) (result i32)
            local.get 0 local.get 1 local.get 2 call_indirect (type $binop))
          (export "dispatch" (func $dispatch)))
        """
        with self.assertRaises(WasmTrap):
            run_kwat(src, "dispatch", [1, 2, 5])


if __name__ == "__main__":
    unittest.main()
