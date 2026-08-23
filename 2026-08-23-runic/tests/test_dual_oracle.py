"""Wires the dual-oracle differential corpus (verify.py) into the unit test
suite, so `python3 -m unittest discover` alone proves every demo program
agrees between our interpreter and Node's real WebAssembly engine — not
just that our own compiler and interpreter agree with each other."""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import verify


@unittest.skipUnless(shutil.which("node"), "node not available in this environment")
class DualOracleTests(unittest.TestCase):
    def test_full_corpus_agrees_with_node(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            failures = []
            for name, (calls, mem_bytes) in verify.CORPUS.items():
                rn_path = os.path.join(verify.DEMO_DIR, name)
                detail = verify.verify_file(rn_path, calls, mem_bytes, tmpdir)
                if not detail["passed"]:
                    failures.append((name, detail["lines"]))
            if failures:
                msg = "\n".join(f"{name}:\n  " + "\n  ".join(lines) for name, lines in failures)
                self.fail(f"dual-oracle mismatches:\n{msg}")


if __name__ == "__main__":
    unittest.main()
