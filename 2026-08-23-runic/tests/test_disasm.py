import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.frontend import compile_source
from compiler.disasm import disassemble


class DisasmTests(unittest.TestCase):
    def test_disassembles_without_error(self):
        src = "array buf[4]; fn f(a) { let i = 0; while (i < a) { buf[i] = i; i = i + 1; } return 0; }"
        wasm = compile_source(src).wasm_bytes
        text = disassemble(wasm)
        self.assertIn("(module", text)
        self.assertIn("$f", text)  # some function label present
        self.assertIn("(memory", text)  # memory section present since array declared

    def test_function_names_resolved_via_exports(self):
        wasm = compile_source("fn add(a, b) { return a + b; }").wasm_bytes
        text = disassemble(wasm)
        self.assertIn("$add", text)

    def test_calls_resolved_to_names(self):
        wasm = compile_source("fn g() { return 1; } fn f() { return g(); }").wasm_bytes
        text = disassemble(wasm)
        self.assertIn("call $g", text)

    def test_no_memory_section_when_no_arrays(self):
        wasm = compile_source("fn f() { return 1; }").wasm_bytes
        text = disassemble(wasm)
        self.assertNotIn("(memory", text)


if __name__ == "__main__":
    unittest.main()
