"""Braid test suite — stdlib `unittest` only (no pytest dependency, to
stay consistent with the rest of the project's zero-third-party-deps
stance). Run with `python3 -m unittest discover -s tests -t .` from the
project root, or `python3 -m tests.test_rga` etc. for a single file."""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
