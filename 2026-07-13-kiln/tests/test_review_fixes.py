"""Regression tests for every finding in REVIEW.md. Each test reproduces
the original bug and asserts the fix holds."""

import subprocess
import sys
import unittest
from pathlib import Path

from .helpers import ROOT, run_pebble, run_kwat
from kiln.pebble.compiler import PebbleCompileError
from kiln.asm.assembler import AssembleError
from kiln.wasm.interpreter import WasmTrap
from kiln import host


class TestReviewFixes(unittest.TestCase):
    def test_disjoint_branch_let_no_longer_collides(self):
        src = """
        fn f(n) -> i32 {
            if (n > 0) { let x = 1; return x; }
            else { let x = 2; return x; }
            return 0;
        }
        """
        self.assertEqual(run_pebble(src, "f", [1]), [1])
        self.assertEqual(run_pebble(src, "f", [0]), [2])

    def test_same_scope_redeclaration_still_rejected(self):
        src = "fn f() -> i32 { let x = 1; let x = 2; return x; }"
        with self.assertRaises(PebbleCompileError):
            run_pebble(src, "f", [])

    def test_deep_recursion_traps_cleanly(self):
        src = """
        fn count(n) -> i32 {
            if (n == 0) { return 0; }
            return 1 + count(n - 1);
        }
        """
        with self.assertRaises(WasmTrap):
            run_pebble(src, "count", [100000])

    def test_writing_immutable_global_rejected_at_assemble_time(self):
        src = """
        (module
          (global $g i32 (i32.const 5))
          (func $f i32.const 99 global.set $g)
          (export "f" (func $f)))
        """
        with self.assertRaises(AssembleError):
            run_kwat(src, "f", [])

    def test_writing_mutable_global_still_works(self):
        src = """
        (module
          (global $g (mut i32) (i32.const 5))
          (func $f i32.const 99 global.set $g)
          (export "f" (func $f)))
        """
        run_kwat(src, "f", [])  # must not raise

    def test_cli_missing_file_is_clean_error_not_traceback(self):
        proc = subprocess.run(
            [sys.executable, "-m", "kiln.cli", "run", "/tmp/kiln-review-does-not-exist.wasm", "main"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("kiln run:", proc.stderr)

    def test_cli_undefined_export_is_clean_error(self):
        wasm = Path(__file__).resolve().parent.parent / "tools"  # any existing dir, just for tmp
        import tempfile
        from .helpers import assemble_bytes
        data = assemble_bytes('(module (func $f (result i32) i32.const 1) (export "f" (func $f)))')
        with tempfile.TemporaryDirectory() as tmp:
            wasm_path = Path(tmp) / "m.wasm"
            wasm_path.write_bytes(data)
            proc = subprocess.run(
                [sys.executable, "-m", "kiln.cli", "run", str(wasm_path), "nosuch"],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertNotIn("Traceback", proc.stderr)
            self.assertIn("no exported function", proc.stderr)

    def test_assembler_missing_immediate_is_clean_error(self):
        with self.assertRaises(AssembleError):
            from kiln.asm.assembler import assemble
            assemble("(module (func $f (result i32) i32.const))")

    def test_fd_write_before_instantiation_traps_cleanly(self):
        imports, holder = host.default_imports()
        fd_write = imports["wasi_snapshot_preview1"]["fd_write"]
        with self.assertRaises(WasmTrap):
            fd_write.fn(1, 0, 0, 0)


if __name__ == "__main__":
    unittest.main()
