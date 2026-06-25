#!/usr/bin/env python3
"""Run all qsim tests and report results."""
import sys
import os
import importlib

sys.path.insert(0, os.path.dirname(__file__))

TEST_MODULES = [
    "qsim.tests.test_gates",
    "qsim.tests.test_measure",
    "qsim.tests.test_algorithms",
    "qsim.tests.test_noise",
    "qsim.tests.test_visualize",
]

total_pass = 0
total_fail = 0
total_error = 0

for mod_name in TEST_MODULES:
    mod = importlib.import_module(mod_name)
    tests = [(k, v) for k, v in sorted(vars(mod).items()) if k.startswith("test_")]
    module_pass = 0
    module_fail = 0

    print(f"\n{'─' * 55}")
    print(f"  {mod_name}")
    print(f"{'─' * 55}")

    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
            module_pass += 1
        except AssertionError as e:
            print(f"  FAIL  {name}")
            print(f"        {e}")
            module_fail += 1
        except Exception as e:
            print(f"  ERROR {name}: {type(e).__name__}: {e}")
            module_fail += 1

    total_pass += module_pass
    total_fail += module_fail
    print(f"\n  {module_pass}/{module_pass + module_fail} passed in this module")

print(f"\n{'=' * 55}")
print(f"  TOTAL: {total_pass} passed, {total_fail} failed")
print(f"{'=' * 55}")
sys.exit(0 if total_fail == 0 else 1)
