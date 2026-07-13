import unittest

from .helpers import run_kwat, instantiate, assemble_bytes
from kiln.asm.assembler import assemble, AssembleError
from kiln.wasm.interpreter import WasmTrap


class TestAssembler(unittest.TestCase):
    def test_named_locals_and_labels(self):
        src = """
        (module
          (func $count_down (param $n i32) (result i32)
            (local $acc i32)
            block $done
              loop $again
                local.get $n
                i32.eqz
                br_if $done
                local.get $acc
                local.get $n
                i32.add
                local.set $acc
                local.get $n
                i32.const 1
                i32.sub
                local.set $n
                br $again
              end
            end
            local.get $acc)
          (export "count_down" (func $count_down)))
        """
        self.assertEqual(run_kwat(src, "count_down", [5]), [15])

    def test_forward_reference_call(self):
        src = """
        (module
          (func $even (param i32) (result i32)
            local.get 0
            i32.eqz
            if (result i32)
              i32.const 1
            else
              local.get 0
              i32.const 1
              i32.sub
              call $odd
            end)
          (func $odd (param i32) (result i32)
            local.get 0
            i32.eqz
            if (result i32)
              i32.const 0
            else
              local.get 0
              i32.const 1
              i32.sub
              call $even
            end)
          (export "even" (func $even)))
        """
        self.assertEqual(run_kwat(src, "even", [10]), [1])
        self.assertEqual(run_kwat(src, "even", [7]), [0])

    def test_global_export_and_mutation(self):
        src = """
        (module
          (global $g (mut i32) (i32.const 41))
          (func $bump (result i32)
            global.get $g
            i32.const 1
            i32.add
            global.set $g
            global.get $g)
          (export "bump" (func $bump))
          (export "g" (global $g)))
        """
        inst = instantiate(assemble_bytes(src))
        self.assertEqual(inst.call("bump", []), [42])
        self.assertEqual(inst.read_global("g"), 42)

    def test_data_segment_populates_memory(self):
        src = """
        (module
          (memory 1)
          (data (i32.const 0) "hi!")
          (func $byte_at (param i32) (result i32)
            local.get 0
            i32.load8_u)
          (export "byte_at" (func $byte_at)))
        """
        inst = instantiate(assemble_bytes(src))
        self.assertEqual(inst.call("byte_at", [0]), [ord("h")])
        self.assertEqual(inst.call("byte_at", [2]), [ord("!")])

    def test_undefined_function_reference_raises(self):
        src = """
        (module
          (func $f (result i32)
            call $nope)
          (export "f" (func $f)))
        """
        with self.assertRaises(AssembleError):
            assemble(src)

    def test_import_and_call_host_function(self):
        src = """
        (module
          (import "env" "print" (func $print (param i32)))
          (func $f (param i32) (result i32)
            local.get 0
            call $print
            local.get 0
            i32.const 2
            i32.mul)
          (export "f" (func $f)))
        """
        seen = []
        from kiln.wasm.interpreter import HostFunc, Instance
        from kiln.wasm.decoder import decode_module
        module = decode_module(assemble_bytes(src))
        imports = {"env": {"print": HostFunc(lambda x: (seen.append(x), [])[1], [0x7F], [])}}
        inst = Instance(module, imports)
        self.assertEqual(inst.call("f", [21]), [42])
        self.assertEqual(seen, [21])

    def test_unbalanced_paren_raises(self):
        with self.assertRaises(Exception):
            assemble("(module (func $f (result i32) i32.const 1)")


if __name__ == "__main__":
    unittest.main()
