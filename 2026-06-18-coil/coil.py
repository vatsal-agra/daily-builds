#!/usr/bin/env python3
"""Launcher for the Coil interpreter: `python3 coil.py [file] [options]`.

(The `coil/` package takes import precedence over this file, so `from coil...`
resolves to the package, not this launcher.)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from coil.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
