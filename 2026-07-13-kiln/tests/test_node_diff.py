"""Cross-checks Kiln's interpreter against Node's real, spec-compliant
WebAssembly engine: the same module bytes, produced by Kiln's own
encoder/assembler/Pebble compiler, are executed by both engines and the
results must match exactly. Skipped (not failed) if Node isn't on PATH."""

import tempfile
import unittest
from pathlib import Path

from .helpers import assemble_bytes, compile_pebble, instantiate, node_available, run_in_node


def _normalize_int(v):
    if v < 0:
        return v + (1 << 32 if -v <= (1 << 32) else 1 << 64)
    return v


@unittest.skipUnless(node_available(), "node is not on PATH")
class TestNodeDifferential(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _check(self, wasm_bytes, func, args):
        kiln_result = instantiate(wasm_bytes).call(func, args)
        node_result = run_in_node(wasm_bytes, func, args, self.tmp_path)
        self.assertNotIn("trap", node_result, f"node trapped: {node_result}")
        node_values = node_result["results"]
        self.assertEqual(len(kiln_result), len(node_values))
        # Kiln's i32/i64 values are canonical unsigned integers; JS's
        # WebAssembly ABI surfaces i32 as a signed Number (and i64 as a
        # signed BigInt), so negative JS results are the same bit pattern
        # under a different sign convention. Use Kiln's own result to know
        # whether a given return slot is float or integer valued, since a
        # whole-number float (e.g. -1.0) is indistinguishable from an int
        # once round-tripped through JSON.
        normalized_node = [
            float(nv) if isinstance(kv, float) else _normalize_int(int(nv))
            for kv, nv in zip(kiln_result, node_values)
        ]
        self.assertEqual(kiln_result, normalized_node)

    def test_fib_matches_node(self):
        wasm = assemble_bytes("""
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
        """)
        for n in range(12):
            self._check(wasm, "fib", [n])

    def test_i32_arithmetic_matches_node(self):
        for op in ["i32.add", "i32.sub", "i32.mul", "i32.div_u", "i32.rem_u",
                   "i32.and", "i32.or", "i32.xor", "i32.shl", "i32.shr_u",
                   "i32.rotl", "i32.rotr", "i32.lt_s", "i32.ge_u"]:
            wasm = assemble_bytes(f"""
            (module
              (func $f (param i32 i32) (result i32)
                local.get 0
                local.get 1
                {op})
              (export "f" (func $f)))
            """)
            for a, b in [(7, 3), (0xFFFFFFFF, 1), (0x80000000, 2), (12345, 6789)]:
                with self.subTest(op=op, a=a, b=b):
                    self._check(wasm, "f", [a, b])

    def test_i32_div_s_matches_node_including_overflow(self):
        from kiln.wasm.interpreter import WasmTrap
        wasm = assemble_bytes("""
        (module
          (func $f (param i32 i32) (result i32)
            local.get 0
            local.get 1
            i32.div_s)
          (export "f" (func $f)))
        """)
        for a, b in [(7, 3), (-7, 3), (7, -3), (-7, -3)]:
            self._check(wasm, "f", [a & 0xFFFFFFFF, b & 0xFFFFFFFF])

        # INT32_MIN / -1 overflows the representable range: both engines
        # must trap rather than silently produce a wrong value.
        with self.assertRaises(WasmTrap):
            instantiate(wasm).call("f", [0x80000000, 0xFFFFFFFF])
        node_result = run_in_node(wasm, "f", [0x80000000, 0xFFFFFFFF], self.tmp_path)
        self.assertIn("trap", node_result)

    def test_f64_arithmetic_matches_node(self):
        for op in ["f64.add", "f64.sub", "f64.mul", "f64.div", "f64.min", "f64.max"]:
            wasm = assemble_bytes(f"""
            (module
              (func $f (param f64 f64) (result f64)
                local.get 0
                local.get 1
                {op})
              (export "f" (func $f)))
            """)
            for a, b in [(1.5, 2.5), (-3.25, 7.0), (0.1, 0.2)]:
                with self.subTest(op=op, a=a, b=b):
                    self._check(wasm, "f", [a, b])

    def test_memory_ops_match_node(self):
        wasm = assemble_bytes("""
        (module
          (memory 1)
          (func $f (param i32 i32) (result i32)
            local.get 0
            local.get 1
            i32.store
            local.get 0
            i32.load8_u)
          (export "f" (func $f)))
        """)
        self._check(wasm, "f", [0, 0x11223344])

    def test_pebble_program_matches_node(self):
        wasm, _ = compile_pebble("""
        fn collatz_steps(n) -> i32 {
            let steps = 0;
            while (n != 1) {
                if (n % 2 == 0) {
                    n = n / 2;
                } else {
                    n = 3 * n + 1;
                }
                steps = steps + 1;
            }
            return steps;
        }
        """)
        for n in [1, 2, 7, 27, 97]:
            self._check(wasm, "collatz_steps", [n])


if __name__ == "__main__":
    unittest.main()
